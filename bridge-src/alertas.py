"""Alerts to the owner (Talles), each sent once (panel next steps of 09/10: "aviso no seu WhatsApp ou Telegram quando
aparecer alguém em 'Para ligar' ou uma call marcada" and "alerta se o número cair").

On 11/10 the escalation alerts went through Evolution, which was disconnected: the call booked with the Ademir (#82)
never reached Talles. Channels now, in order:
  1. Telegram, when TELEGRAM_ALERT_BOT_TOKEN and TELEGRAM_ALERT_CHAT_ID are set (Talles picks the bot; token in the vault);
  2. the official number: the approved UTILITY template alerta_interno_* to the owner's number (outside any 24 h
     window), counted apart from the prospect 80/20;
  3. Evolution, when it is connected.
What the patrol checks every ALERT_SECONDS: calls booked by the agent, people to call (a person answered, no outcome,
quiet for an hour after our message), and the channels (official number state and quality, Evolution session).
"""
import logging
import os
import sqlite3
import time
from typing import Any

import httpx

import sdr

logger = logging.getLogger("bridge.alertas")

ALERT_SECONDS = int(os.getenv("ALERT_SECONDS", "300"))
CALL_AFTER = int(os.getenv("ALERT_CALL_AFTER_SECONDS", "3600"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_ALERT_BOT_TOKEN", "")
TELEGRAM_CHAT = os.getenv("TELEGRAM_ALERT_CHAT_ID", "")
TELEGRAM_THREAD = os.getenv("TELEGRAM_ALERT_THREAD_ID", "")
CHATWOOT_LINK = "https://chatwoot.talles.dev/app/accounts/1/inbox/2/conversations/"
# The internal alert template: the alert text rides in {{1}}, fixed text around it (never a variable at the edges).
ALERT_TEMPLATE = ("alerta_interno_01", "Aviso da prospecção do Talles: {{1}}. Os detalhes estão no painel e no Chatwoot.",
                  ["call marcada com a Clínica Sorriso na terça às 10h, conversa 82"])


def connect() -> sqlite3.Connection:
    c = sdr.connect()
    c.execute("CREATE TABLE IF NOT EXISTS alertas_enviados (chave TEXT PRIMARY KEY, tipo TEXT NOT NULL, conversation INTEGER, texto TEXT NOT NULL, "
              "canal TEXT, erro TEXT, criado REAL NOT NULL)")
    return c


def delivered(chave: str) -> bool:
    with connect() as c:
        row = c.execute("SELECT canal FROM alertas_enviados WHERE chave=?", (chave,)).fetchone()
    return bool(row and row[0])


def claim(chave: str, tipo: str, texto: str, conversation: int | None = None) -> bool:
    """True while this alert has not been delivered yet: an alert goes out once, and one that found no channel is
    tried again on the next patrol instead of being lost."""
    if delivered(chave):
        return False
    with connect() as c:
        c.execute("INSERT INTO alertas_enviados(chave,tipo,conversation,texto,criado) VALUES (?,?,?,?,?) "
                  "ON CONFLICT(chave) DO UPDATE SET texto=excluded.texto", (chave, tipo, conversation, texto, time.time()))
    return True


def mark(chave: str, canal: str | None, erro: str = "") -> None:
    with connect() as c:
        c.execute("UPDATE alertas_enviados SET canal=?, erro=? WHERE chave=?", (canal, erro[:300] or None, chave))


async def via_telegram(texto: str) -> bool:
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT):
        return False
    body: dict[str, Any] = {"chat_id": TELEGRAM_CHAT, "text": texto, "disable_web_page_preview": True}
    if TELEGRAM_THREAD:
        body["message_thread_id"] = int(TELEGRAM_THREAD)
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json=body)
        r.raise_for_status()
    return True


def owner_conversation() -> int | None:
    import prospeccao
    stored = prospeccao.kv_get("alerta_conversa")
    return int(stored) if stored else None


async def via_oficial(texto: str) -> bool:
    """The approved internal template to the owner's number, on the owner's alert conversation of the official inbox."""
    import cloud
    import prospeccao
    import templates_db
    if not (cloud.enabled() and sdr.NOTIFY_NUMBER):
        return False
    template = next(iter(templates_db.pool("interno")), None)
    if not template:
        return False
    conversation = owner_conversation()
    if conversation is None:
        _, conversation, _internal = await cloud.open_conversation(cloud.canonical_number(sdr.NOTIFY_NUMBER), "Talles (alertas)")
        prospeccao.kv_set("alerta_conversa", str(conversation))
    value = " ".join(texto.split())[:900]
    params = {"name": template["name"], "category": template.get("category") or "UTILITY", "language": template.get("language", "pt_BR"),
              "processed_params": {"1": value}}
    await cloud.post_message(conversation, template["text"].replace("{{1}}", value), template=params, attributes={"bridge_alerta": True})
    return True


async def via_evolution(texto: str, send_evolution: Any) -> bool:
    if not (sdr.NOTIFY_NUMBER and send_evolution):
        return False
    await send_evolution(sdr.NOTIFY_NUMBER, texto)
    return True


async def send_text(texto: str, send_evolution: Any = None) -> tuple[str | None, str]:
    """(channel used, errors) through the first channel that works."""
    erros = []
    for canal, enviar in (("telegram", lambda: via_telegram(texto)), ("oficial", lambda: via_oficial(texto)),
                          ("evolution", lambda: via_evolution(texto, send_evolution))):
        try:
            if await enviar():
                logger.warning("Alert sent via %s: %s", canal, texto[:120])
                return canal, ""
        except Exception as exc:
            erros.append(f"{canal}: {str(exc)[:120]}")
    logger.warning("Alert NOT delivered (%s): %s", "; ".join(erros) or "no channel", texto[:120])
    return None, "; ".join(erros) or "nenhum canal configurado"


async def notify(chave: str, tipo: str, texto: str, conversation: int | None = None, send_evolution: Any = None) -> bool:
    """Send one alert once. Returns True when it went out now."""
    if not claim(chave, tipo, texto, conversation):
        return False
    canal, erro = await send_text(texto, send_evolution)
    mark(chave, canal, erro)
    return bool(canal)


async def notify_batch(itens: list[tuple[str, str, int | None]], tipo: str, titulo: str, send_evolution: Any = None) -> int:
    """Several pending alerts in ONE message (no burst on the owner's phone); each key is marked delivered."""
    pend = [(k, t, conv) for k, t, conv in itens if claim(k, tipo, t, conv)]
    if not pend:
        return 0
    texto = f"{titulo} ({len(pend)}): " + " | ".join(t for _, t, _ in pend) + ". O número é a conversa no Chatwoot"
    canal, erro = await send_text(texto, send_evolution)
    for k, _t, _c in pend:
        mark(k, canal, erro)
    return len(pend) if canal else 0


def curto(nome: str) -> str:
    """The business name without the SEO tail of Google Maps ("Clínica X | Implantes | ..." -> "Clínica X")."""
    import re
    return (re.split(r"\s[-–|(]\s?|\|", str(nome or ""))[0].strip() or "lead")[:40]


def calls_marcadas(now: float | None = None) -> list[tuple[str, str, int | None]]:
    """(key, text, conversation) for every 20-minute call the agent booked that is still ahead."""
    out = []
    for item in sdr.busy_times(now):
        o_que = item["o_que"]
        if not o_que.startswith("call com"):
            continue
        conv = None
        if "(conversa " in o_que:
            try:
                conv = int(o_que.rsplit("(conversa ", 1)[1].rstrip(")"))
            except ValueError:
                conv = None
        quando = item["quando"].replace("T", " às ")
        nome = curto(o_que.replace("call com ", "").split(" (conversa ")[0])
        out.append((f"call:{conv}:{item['quando']}", f"{nome} em {quando}" + (f" (#{conv})" if conv else ""), conv))
    return out


def para_ligar(now: float | None = None) -> list[tuple[str, str, int]]:
    """A person (not a robot) answered the test, has no outcome nor opt-out, and went quiet for CALL_AFTER after our message."""
    now = time.time() if now is None else now
    out = []
    with sdr.connect() as c:
        c.row_factory = sqlite3.Row
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='sdr_prospects'").fetchone():
            return out
        rows = c.execute("SELECT p.conversation, p.numero, a.last_lead_ts, a.last_agent_ts FROM sdr_prospects p "
                         "JOIN sdr_activity a ON a.conversation=p.conversation WHERE p.status='respondeu' AND p.conversation IS NOT NULL").fetchall()
        has_leads = c.execute("SELECT 1 FROM sqlite_master WHERE name='leads'").fetchone()
        for r in rows:
            rec = sdr.records_of(r["conversation"])
            if sdr.robot_records(rec) or rec.get("desfecho") or str(rec.get("opt_out") or "").lower() == "sim":
                continue
            last_lead, last_agent = float(r["last_lead_ts"] or 0), float(r["last_agent_ts"] or 0)
            if not last_agent or last_lead > last_agent or now - last_agent < CALL_AFTER:
                continue
            nome = None
            if has_leads:
                found = c.execute("SELECT nome FROM leads WHERE numero=?", (r["numero"],)).fetchone()
                nome = found[0] if found else None
            out.append((f"ligar:{r['conversation']}:{int(last_agent)}", f"{curto(nome or 'lead')} (#{r['conversation']})", int(r["conversation"])))
    return out


async def canais() -> list[tuple[str, str]]:
    """Official number state and quality, and the Evolution session: an alert on each change for the worse."""
    import prospeccao
    import template_health
    out = []
    try:
        numero = await template_health.guard_number()
        alarme = numero.get("alarme")
        if alarme:
            out.append((f"numero:{alarme}:{time.strftime('%Y-%m-%d')}", f"⚠️ Número oficial: {alarme}. A fila de prospecção foi pausada."))
    except Exception as exc:
        out.append((f"numero:erro:{time.strftime('%Y-%m-%d')}", f"⚠️ Não consegui ler o estado do número oficial na Meta: {str(exc)[:150]}"))
    url = os.getenv("EVOLUTION_URL", "").rstrip("/")
    if url:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(url + "/instance/status", headers={"apikey": os.getenv("EVOLUTION_API_KEY", "")})
            data = (r.json() or {}).get("data") or {}
            ok = bool(data.get("Connected")) and bool(data.get("LoggedIn"))
        except Exception:
            ok = False
        before = prospeccao.kv_get("alerta_evolution_ok")
        prospeccao.kv_set("alerta_evolution_ok", "1" if ok else "0")
        if not ok and before != "0":
            out.append((f"evolution:caiu:{int(time.time())}", "⚠️ O WhatsApp antigo (Evolution) está desconectado: os avisos de escalada por ele não chegam."))
    return out


ALERT_HOURS = (int(os.getenv("ALERT_START_HOUR", "8")), int(os.getenv("ALERT_END_HOUR", "21")))


async def patrol(send_evolution: Any = None, now: float | None = None) -> int:
    """Calls and people to call: one message per patrol, only between ALERT_HOURS. Channel alerts: any hour."""
    from datetime import datetime
    now = time.time() if now is None else now
    sent = 0
    in_hours = ALERT_HOURS[0] <= datetime.fromtimestamp(now, sdr.BUSINESS_TZ).hour < ALERT_HOURS[1]
    if in_hours:
        sent += await notify_batch(calls_marcadas(now), "call", "📅 Calls marcadas", send_evolution)
        sent += await notify_batch(para_ligar(now), "ligar", "📞 Para ligar", send_evolution)
    for chave, texto in await canais():
        if chave.startswith("evolution:") and not in_hours:
            continue  # the old number is known to be down; only the official number's alarm wakes the owner
        sent += await notify(chave, "canal", texto, None, send_evolution)
    return sent


def recent(limit: int = 50) -> list[dict[str, Any]]:
    with connect() as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute("SELECT * FROM alertas_enviados ORDER BY criado DESC LIMIT ?", (limit,))]
