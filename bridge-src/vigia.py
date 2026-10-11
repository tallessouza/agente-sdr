"""Vigia dos follow-ups (Talles, 11/10/2026: "não me faça passar vergonha; arma um monitor para ver se todos os
follow-ups estão sendo devidamente armados para o momento mais adequado").

Every VIGIA_SECONDS it compares what the brain planned (GET /plano: the 4 touches of each conversation, text inside
the 23 h 30 window and template after it) with what the bridge actually did, and records each problem once
(vigia_achados) until it goes away:
  vencido       a touch whose time passed (in sending hours) and the brain did not decide;
  nao_saiu      a text touch decided but still pending, or failed;
  template      a template touch / retomada waiting past its time (no 80/20 slot, not approved) or expired/failed;
  rajada        two touches less than 2 h apart;
  fora_de_hora  a touch sent outside 9h–20h;
  plano         fewer than 4 touches planned for a conversation that should have them;
  esperando     the lead wrote and nobody answered for 10 minutes (not paused, no outcome);
  sem_cadencia  the 4 touches ended before the daily cadence existed: it will not go out unless Talles decides;
  sem_acompanhamento  a business answered and the brain does not track the conversation (no touch would ever go);
  vaga          template touches due in the next 24 h and no UTILITY retomada approved (the retomadas' own 80/20 needs one).
New problems reach Talles in ONE message per hour, 8h–21h (alertas.notify_batch); the panel shows them all.
"""
import logging
import os
import sqlite3
import time
from datetime import datetime
from typing import Any

import httpx

import sdr

logger = logging.getLogger("bridge.vigia")

VIGIA_SECONDS = int(os.getenv("VIGIA_SECONDS", "600"))
LATE = 20 * 60          # a planned touch this late without a decision is a problem
PENDING_LATE = 15 * 60  # a decided text touch still pending this long after its time
TEMPLATE_LATE = 3600    # a template touch waiting this long for its slot
WAITING = 10 * 60       # a lead waiting this long for our answer
MIN_GAP = 2 * 3600 - 60
SEND_HOURS = (9, 20)


def connect() -> sqlite3.Connection:
    c = sdr.connect()
    c.execute("CREATE TABLE IF NOT EXISTS vigia_achados (chave TEXT PRIMARY KEY, tipo TEXT NOT NULL, conversation INTEGER, detalhe TEXT NOT NULL, "
              "primeira_vez REAL NOT NULL, ultima_vez REAL NOT NULL, resolvido REAL)")
    return c


def local(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, sdr.BUSINESS_TZ)


def hhmm(ts: float) -> str:
    return local(ts).strftime("%d/%m %H:%M")


def in_send_hours(ts: float) -> bool:
    return SEND_HOURS[0] <= local(ts).hour < SEND_HOURS[1]


async def fetch_plan() -> dict[str, Any]:
    url = os.getenv("SDR_BRAIN_URL", "").rstrip("/")
    if not url:
        return {}
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.get(f"{url}/plano", headers={"Authorization": f"Bearer {os.getenv('SDR_BRAIN_TOKEN', '')}"})
        r.raise_for_status()
        return r.json().get("conversas") or {}


def findings(plan: dict[str, Any], now: float | None = None, utility_slots_ahead: int | None = None) -> list[dict[str, Any]]:
    """Every problem seen now: {chave, tipo, conversation, detalhe}."""
    now = time.time() if now is None else now
    out: list[dict[str, Any]] = []

    def add(chave: str, tipo: str, conv: int | None, detalhe: str) -> None:
        out.append({"chave": chave, "tipo": tipo, "conversation": conv, "detalhe": detalhe})

    with connect() as c:
        c.row_factory = sqlite3.Row
        followups: dict[int, list[sqlite3.Row]] = {}
        for r in c.execute("SELECT * FROM sdr_followups ORDER BY id"):
            followups.setdefault(int(r["conversation"]), []).append(r)
        has_ret = c.execute("SELECT 1 FROM sqlite_master WHERE name='sdr_retomadas'").fetchone()
        retomadas = [dict(r) for r in c.execute("SELECT * FROM sdr_retomadas")] if has_ret else []
        activity = {int(r["conversation"]): (float(r["last_lead_ts"] or 0), float(r["last_agent_ts"] or 0))
                    for r in c.execute("SELECT * FROM sdr_activity")}
        has_prospects = c.execute("SELECT 1 FROM sqlite_master WHERE name='sdr_prospects'").fetchone()
        answered = [int(r[0]) for r in c.execute("SELECT conversation FROM sdr_prospects WHERE jid LIKE '%@cloud' AND conversation IS NOT NULL "
                                                  "AND status IN ('respondeu','automatica')")] if has_prospects else []
    templates_due = 0
    for key, item in plan.items():
        conv = int(key)
        stops = item.get("pausada") or item.get("para_toques") or item.get("objecao")
        rows = followups.get(conv, [])
        # Two touches too close, or one sent out of hours: these happened, they are reported even if the lead stopped.
        sent = sorted(float(r["sent_at"]) for r in rows if r["status"] == "sent" and r["sent_at"])
        for a, b in zip(sent, sent[1:]):
            if b - a < MIN_GAP:
                add(f"rajada:{conv}:{int(b)}", "rajada", conv, f"#{conv}: dois toques com {int((b - a) // 60)} min de intervalo ({hhmm(a)} e {hhmm(b)})")
        for ts in sent:
            if not in_send_hours(ts):
                add(f"fora:{conv}:{int(ts)}", "fora_de_hora", conv, f"#{conv}: toque enviado às {hhmm(ts)}, fora das 9h–20h")
        if stops or item.get("lead_falou_por_ultimo"):
            continue
        plano = item.get("plano") or []
        if item.get("encerrada") == "completa" and any(p["estagio"].startswith("c") and not p.get("decidido") for p in plano):
            # Sequences finished before the daily cadence existed (11/10): Talles decides one by one whether they get it.
            add(f"sem_cadencia:{conv}", "sem_cadencia", conv, f"#{conv}: os 4 toques terminaram e a cadência diária não vai sair (sequência encerrada)")
            continue
        if plano and len(plano) < 4:
            add(f"plano:{conv}:{len(plano)}", "plano", conv, f"#{conv}: só {len(plano)} toques no plano (esperado 4)")
        for p in plano:
            when, stage = float(p["quando"]), p["estagio"]
            decided = p.get("decidido")
            if not decided and when <= now - LATE and in_send_hours(now):
                add(f"vencido:{conv}:{stage}:{int(when)}", "vencido", conv, f"#{conv}: toque {stage} ({p['canal']}) era às {hhmm(when)} e não foi decidido")
            if p["canal"] == "template" and not decided and now <= when <= now + 86400:
                templates_due += 1
        for r in rows:
            if r["status"] == "pending" and float(r["send_at"]) <= now - PENDING_LATE and in_send_hours(now):
                add(f"nao_saiu:{r['id']}", "nao_saiu", conv, f"#{conv}: toque {r['stage']} decidido para {hhmm(float(r['send_at']))} ainda não saiu")
            if r["status"] == "failed":
                add(f"falhou:{r['id']}", "nao_saiu", conv, f"#{conv}: toque {r['stage']} falhou ({(r['reason'] or '')[:80]})")
    for r in retomadas:
        conv = int(r["conversation"])
        if r["status"] == "pendente":
            templates_due += 1
            if float(r["send_at"]) <= now - TEMPLATE_LATE:
                add(f"template:{r['id']}", "template", conv, f"#{conv}: template {r['template']} esperando desde {hhmm(float(r['send_at']))} (sem vaga no 80/20 ou fila parada)")
        elif r["status"] in {"expirada", "falhou"}:
            add(f"template_{r['status']}:{r['id']}", "template", conv, f"#{conv}: template {r['template']} {r['status']}{(': ' + r['erro'][:60]) if r.get('erro') else ''}")
    for conv, (last_lead, last_agent) in activity.items():
        item = plan.get(str(conv))
        if not item or item.get("pausada") or item.get("para_toques") or item.get("robo"):
            continue
        if last_lead > last_agent and now - last_lead >= WAITING:
            add(f"esperando:{conv}:{int(last_lead)}", "esperando", conv, f"#{conv}: o lead escreveu às {hhmm(last_lead)} e ninguém respondeu")
    if plan:
        for conv in answered:
            if str(conv) not in plan and not sdr.outcome_stops_touches(conv):
                # 10/10: #71 answered and the brain never tracked it, so it would get no touch at all.
                add(f"sem_brain:{conv}", "sem_acompanhamento", conv, f"#{conv}: respondeu e o brain não acompanha a conversa (sem nenhum toque)")
    if utility_slots_ahead is not None and templates_due and not utility_slots_ahead:
        dia = local(now).strftime("%Y-%m-%d")
        add(f"vaga:{dia}", "vaga", None, f"{templates_due} toques por template nas próximas 24 h e nenhum template de retomada utility aprovado"
                                           " (pelo 80/20 das retomadas, nada sai até a Meta aprovar um utility do farm)")
    return out


def store(found: list[dict[str, Any]], now: float | None = None) -> list[dict[str, Any]]:
    """Upsert what is seen now, resolve what disappeared; returns the NEW ones (first time seen)."""
    now = time.time() if now is None else now
    new = []
    with connect() as c:
        seen = set()
        for f in found:
            seen.add(f["chave"])
            row = c.execute("SELECT resolvido FROM vigia_achados WHERE chave=?", (f["chave"],)).fetchone()
            if row is None:
                c.execute("INSERT INTO vigia_achados(chave,tipo,conversation,detalhe,primeira_vez,ultima_vez) VALUES (?,?,?,?,?,?)",
                          (f["chave"], f["tipo"], f["conversation"], f["detalhe"], now, now))
                new.append(f)
            else:
                c.execute("UPDATE vigia_achados SET ultima_vez=?, detalhe=?, resolvido=NULL WHERE chave=?", (now, f["detalhe"], f["chave"]))
        for (chave,) in c.execute("SELECT chave FROM vigia_achados WHERE resolvido IS NULL").fetchall():
            if chave not in seen:
                c.execute("UPDATE vigia_achados SET resolvido=? WHERE chave=?", (now, chave))
    return new


def open_findings(limit: int = 200) -> list[dict[str, Any]]:
    with connect() as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute("SELECT * FROM vigia_achados WHERE resolvido IS NULL ORDER BY primeira_vez DESC LIMIT ?", (limit,))]


def utility_slots(now: float | None = None) -> int:
    """UTILITY retomada templates approved: the retomadas' own 80/20 (Talles 11/10) sends nothing without one."""
    import template_health
    return sum(t.get("category") == "UTILITY" for t in template_health.retomada_pool())


async def patrol(send_evolution: Any = None, now: float | None = None) -> int:
    """One round: compare, store, and tell Talles about the new problems (one message, at most hourly, 8h–21h)."""
    import alertas
    import prospeccao
    now = time.time() if now is None else now
    plan = await fetch_plan()
    new = store(findings(plan, now, utility_slots(now)), now)
    if new:
        logger.warning("Vigia: %d new problem(s): %s", len(new), "; ".join(f["detalhe"] for f in new[:5]))
    pending = [f for f in open_findings() if not alertas.delivered(f"vigia:{f['chave']}")]
    if not pending or not (alertas.ALERT_HOURS[0] <= local(now).hour < alertas.ALERT_HOURS[1]):
        return 0
    if now - float(prospeccao.kv_get("vigia_ultimo_aviso") or 0) < 3600:
        return 0
    prospeccao.kv_set("vigia_ultimo_aviso", str(now))
    itens = [(f"vigia:{f['chave']}", f["detalhe"], f["conversation"]) for f in pending[:15]]
    return await alertas.notify_batch(itens, "vigia", "🔎 Vigia dos follow-ups", send_evolution)
