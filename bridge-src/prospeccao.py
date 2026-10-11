"""Prospecção ativa: teste de atendimento em negócios da lista.

A business from the prospect list gets one neutral message inside a time window.
Whoever answers talks to the agent as a lead of the "atendimento" offer, with a
trusted origin (who the business is, what we sent, how long it took to answer).
Whoever stays silent, or only sends an automatic greeting, gets one follow-up on
the next business day, through the regular follow-up worker, which drops it if
the business writes first. See 17-prospeccao/PLANO.md in the screener workspace.
"""
import json
import os
import random
import re
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any

import leads
import sdr

PROSPECT_ENABLED = os.getenv("PROSPECT_ENABLED", "0") == "1"
# Variants separated by "|" so the same sentence is not sent dozens of times (anti-ban); {saudacao} = Bom dia/Boa tarde/Boa noite.
PROSPECT_TEST_TEXTS = [t.strip() for t in os.getenv(
    "PROSPECT_TEST_TEXTS",
    "{saudacao}! Vocês estão atendendo pelo WhatsApp? Queria tirar uma dúvida."
    "|Oi, {saudacao_min}! Vocês atendem por aqui? Queria tirar uma dúvida."
    "|Olá, {saudacao_min}! Consigo falar com alguém por aqui? Tenho uma dúvida."
    "|{saudacao}, tudo bem? Vocês respondem pelo WhatsApp? Queria uma informação.",
).split("|") if t.strip()]
# "dias@HH:MM-HH:MM" separated by commas; days 0=segunda .. 6=domingo and 7=feriado, ranges allowed.
# On Saturday only businesses open on Saturday get the test; on Sunday and holidays, only those open on Sunday.
PROSPECT_WINDOWS = os.getenv("PROSPECT_WINDOWS", "0-4@18:30-21:00,5@09:30-12:30,6@10:00-13:00,7@10:00-13:00")
# Follow-up only for whoever answered (Talles, 09/10): the silent ones get no pitch. Kept as a switch.
PROSPECT_PITCH_SILENT = os.getenv("PROSPECT_PITCH_SILENT", "0") == "1"
# Only an automatic greeting and then silence: one differential message the next business morning (Talles, 09/10).
PROSPECT_PITCH_AUTOMATIC = os.getenv("PROSPECT_PITCH_AUTOMATIC", "1") == "1"
# Ramp per sending day (1st day 40, then 60...; the last value repeats) and a random
# gap between sends: a regular burst from an unofficial WhatsApp session gets banned.
PROSPECT_RAMP = [int(v) for v in os.getenv("PROSPECT_RAMP", "40,60,80,100,120").split(",") if v.strip()]
PROSPECT_MIN_GAP = int(os.getenv("PROSPECT_MIN_GAP_SECONDS", "10"))
PROSPECT_MAX_GAP = int(os.getenv("PROSPECT_MAX_GAP_SECONDS", "240"))
PROSPECT_PITCH_WINDOW = os.getenv("PROSPECT_PITCH_WINDOW", "09:30-12:00")
PROSPECT_LABEL = os.getenv("PROSPECT_LABEL", "prospeccao")
# National holidays: no test and no follow-up on these dates (YYYY-MM-DD, comma separated).
PROSPECT_SKIP_DATES = {d.strip() for d in os.getenv("PROSPECT_SKIP_DATES", "2026-10-12,2026-11-02,2026-11-15,2026-11-20,2026-12-25,2027-01-01").split(",") if d.strip()}
OFFER = "atendimento"
# What the agent may know about the business (from the Maps list and the site enrichment). The data itself lives
# in the lead tables (leads.py, the central database); sdr_prospects.dados is still written during the transition
# but nothing here reads it.
FIELDS = leads.FIELDS
WEEKDAY_NAMES = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
WEEKDAY_ON = ["na segunda", "na terça", "na quarta", "na quinta", "na sexta", "no sábado", "no domingo"]


def connect() -> sqlite3.Connection:
    c = sdr.connect()
    c.execute("CREATE TABLE IF NOT EXISTS sdr_prospects (numero TEXT PRIMARY KEY, dados TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'fila', "
              "enfileirado REAL NOT NULL, jid TEXT, lid TEXT, conversation INTEGER, nome_whatsapp TEXT, texto TEXT, "
              "enviado_em REAL, respondeu_em REAL, automatica INTEGER NOT NULL DEFAULT 0, erro TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS sdr_kv (key TEXT PRIMARY KEY, value TEXT)")
    c.commit()
    leads.ensure_schema(c)
    return c


def kv_get(key: str) -> str | None:
    with connect() as c:
        row = c.execute("SELECT value FROM sdr_kv WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def kv_set(key: str, value: str) -> None:
    with connect() as c:
        c.execute("INSERT INTO sdr_kv VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def enabled() -> bool:
    """The deploy switch (PROSPECT_ENABLED) and the runtime pause (POST /prospeccao/pausar) must both allow."""
    return PROSPECT_ENABLED and kv_get("prospeccao_pausada") != "1"


def normalize_number(raw: Any) -> str | None:
    """Brazilian number as 55 + DDD + number; anything else is rejected."""
    return leads.normalize_number(raw)


def _lead_item(item: dict[str, Any]) -> dict[str, Any]:
    """The business fields of a queue item, empty ones left out (an API call never clears what the database knows)."""
    return {k: v for k, v in (item or {}).items() if k not in ("telefone_e164", "numero", "telefone") and v not in (None, "")}


def _dados(c: sqlite3.Connection, number: str) -> str:
    """sdr_prospects.dados, kept in step with the lead tables during the transition (nothing reads it)."""
    return json.dumps(leads.lead(number, c) or {}, ensure_ascii=False)


def enqueue(items: list[dict[str, Any]], now: float | None = None) -> dict[str, int]:
    """Queue businesses for the test. A new number also writes its data to the lead tables (merged with what they
    already know); a number already in the queue is left as it is."""
    now = time.time() if now is None else now
    result = {"novos": 0, "repetidos": 0, "invalidos": 0}
    with connect() as c:
        for index, item in enumerate(items or []):
            item = item or {}
            number = normalize_number(item.get("telefone_e164") or item.get("numero") or item.get("telefone"))
            if not number:
                result["invalidos"] += 1
                continue
            if c.execute("SELECT 1 FROM sdr_prospects WHERE numero=?", (number,)).fetchone():
                result["repetidos"] += 1
                continue
            leads.save(number, _lead_item(item), fonte="fila", c=c, now=now)
            c.execute("INSERT INTO sdr_prospects(numero,dados,status,enfileirado) VALUES (?,?,?,?)",
                      (number, _dados(c, number), "fila", now + index * 1e-3))
            result["novos"] += 1
    return result


def minutes(hhmm: str) -> int:
    hour, _, minute = hhmm.strip().partition(":")
    return int(hour) * 60 + int(minute or 0)


def _windows(spec: str) -> list[tuple[set[int], int, int]]:
    windows = []
    for part in (spec or "").split(","):
        if "@" not in part:
            continue
        days, hours = part.strip().split("@", 1)
        first, _, last = days.partition("-")
        start, _, end = hours.partition("-")
        windows.append((set(range(int(first), int(last or first) + 1)), minutes(start), minutes(end)))
    return windows


def only_24h() -> bool:
    """Runtime filter (kv prospeccao_filtro = 24h): the queue picks only businesses open 24 h on that weekday, at any
    hour (Talles, 11/10/2026: test the 47 that say they answer around the clock, tonight). Off: kv deleted or empty."""
    return kv_get("prospeccao_filtro") == "24h"


def in_window(local: datetime, spec: str | None = None) -> bool:
    if spec is None and only_24h():
        return True  # those businesses say they are open at any hour: that is exactly what the test measures
    minute = local.hour * 60 + local.minute
    day = day_key(local)
    return any(day in days and start <= minute < end for days, start, end in _windows(spec or PROSPECT_WINDOWS))


def day_key(local: datetime) -> int:
    """0..6 for the weekday, 7 for a national holiday."""
    return 7 if local.strftime("%Y-%m-%d") in PROSPECT_SKIP_DATES else local.weekday()


def open_on(data: dict[str, Any], local: datetime) -> bool:
    """Weekday: everyone. Saturday: open on Saturday. Sunday or holiday: open on Sunday (the proxy for working
    on holidays). No opening hours known: weekdays only."""
    day = day_key(local)
    if day <= 4:
        return True
    days = data.get("dias_abertos")
    if not isinstance(days, list):
        return False
    return (5 in days) if day == 5 else (6 in days)


def day_start(now: float) -> float:
    return datetime.fromtimestamp(now, sdr.BUSINESS_TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def daily_cap(now: float | None = None) -> int:
    """Cap of today: the ramp step for the number of earlier days that already had sends."""
    now = time.time() if now is None else now
    with connect() as c:
        days = {datetime.fromtimestamp(r[0], sdr.BUSINESS_TZ).date() for r in c.execute("SELECT enviado_em FROM sdr_prospects WHERE enviado_em IS NOT NULL AND enviado_em<?", (day_start(now),))}
    return PROSPECT_RAMP[min(len(days), len(PROSPECT_RAMP) - 1)] if PROSPECT_RAMP else 0


def sent_today(now: float | None = None) -> int:
    now = time.time() if now is None else now
    with connect() as c:
        return c.execute("SELECT COUNT(*) FROM sdr_prospects WHERE enviado_em>=?", (day_start(now),)).fetchone()[0]


def next_queued(numero: str | None = None, local: datetime | None = None) -> tuple[str, dict[str, Any]] | None:
    """The next queued business; with `local`, the first one open that day (weekends and holidays).
    The data comes from the lead tables; the open-day filter is open_on() written in SQL over lead_horarios."""
    with connect() as c:
        if numero:
            row = c.execute("SELECT numero FROM sdr_prospects WHERE numero=? AND status='fila'", (numero,)).fetchone()
        elif only_24h():
            weekday = (local or datetime.now(sdr.BUSINESS_TZ)).weekday()
            row = c.execute("SELECT p.numero FROM sdr_prospects p WHERE p.status='fila' AND EXISTS (SELECT 1 FROM lead_horarios h "
                            "WHERE h.numero=p.numero AND h.dia=? AND h.aberto_24h=1) ORDER BY p.enfileirado LIMIT 1", (weekday,)).fetchone()
        else:
            day = None if local is None else day_key(local)
            if day is None or day <= 4:
                row = c.execute("SELECT numero FROM sdr_prospects WHERE status='fila' ORDER BY enfileirado LIMIT 1").fetchone()
            else:  # Saturday: open on Saturday; Sunday or holiday: open on Sunday
                row = c.execute("SELECT p.numero FROM sdr_prospects p WHERE p.status='fila' AND EXISTS (SELECT 1 FROM lead_horarios h "
                                "WHERE h.numero=p.numero AND h.dia=? AND h.fechado=0) ORDER BY p.enfileirado LIMIT 1",
                                (5 if day == 5 else 6,)).fetchone()
        return (row[0], leads.lead(row[0], c) or {}) if row else None


def refresh_data(items: list[dict[str, Any]]) -> int:
    """Update the data of businesses still in the queue (e.g. opening days added after the first load)."""
    changed = 0
    with connect() as c:
        for item in items or []:
            number = normalize_number((item or {}).get("telefone_e164") or (item or {}).get("numero"))
            if not number or not c.execute("SELECT 1 FROM sdr_prospects WHERE numero=? AND status='fila'", (number,)).fetchone():
                continue
            leads.save(number, _lead_item(item), fonte="fila", c=c)
            changed += c.execute("UPDATE sdr_prospects SET dados=? WHERE numero=? AND status='fila'", (_dados(c, number), number)).rowcount
    return changed


def claim(numero: str, now: float | None = None) -> bool:
    """Atomic fila → processando: only the caller that wins sends, so a number never gets the test twice
    (worker and manual send racing, restarts). A crash leaves it in 'processando': at most once, never twice."""
    now = time.time() if now is None else now
    with connect() as c:
        return c.execute("UPDATE sdr_prospects SET status='processando', erro=NULL WHERE numero=? AND status='fila'",
                         (numero,)).rowcount == 1


UPDATABLE = {"status", "jid", "lid", "conversation", "nome_whatsapp", "texto", "enviado_em", "respondeu_em", "automatica", "erro"}


def update(numero: str, **fields: Any) -> None:
    fields = {k: v for k, v in fields.items() if k in UPDATABLE}
    if fields:
        with connect() as c:
            c.execute("UPDATE sdr_prospects SET " + ",".join(f"{k}=?" for k in fields) + " WHERE numero=?", (*fields.values(), numero))


def _row(column: str, value: Any) -> dict[str, Any] | None:
    with connect() as c:
        c.row_factory = sqlite3.Row
        row = c.execute(f"SELECT * FROM sdr_prospects WHERE {column}=? AND enviado_em IS NOT NULL ORDER BY enviado_em DESC LIMIT 1", (value,)).fetchone()
    return dict(row) if row else None


def for_jid(jid: str) -> dict[str, Any] | None:
    bare = re.sub(r":\d+(?=@)", "", jid or "")
    return (_row("jid", bare) or _row("lid", bare)) if bare else None


def local_label(ts: float) -> str:
    local = datetime.fromtimestamp(ts, sdr.BUSINESS_TZ)
    return f"{local:%Y-%m-%d %H:%M} ({WEEKDAY_NAMES[local.weekday()]})"


def origin(jid: str) -> dict[str, Any] | None:
    """Trusted origin of a tested business: who it is, what we sent and how long it took to answer."""
    row = for_jid(jid)
    if not row:
        return None
    data = leads.lead(row["numero"]) or {}
    if row.get("nome_whatsapp"):
        data["nome_no_whatsapp"] = row["nome_whatsapp"]
    result: dict[str, Any] = {
        "canal": "prospeccao",
        "oferta": OFFER,
        "negocio": data,
        "teste": {"enviado_em": local_label(row["enviado_em"]), "texto": row.get("texto") or ""},
    }
    if row.get("respondeu_em"):
        result["respondeu_em"] = local_label(row["respondeu_em"])
        result["minutos_para_responder"] = int((row["respondeu_em"] - row["enviado_em"]) // 60)
        # Seconds tell a robot apart: 4 lines in 7 s is a template or an AI, not someone typing.
        result["segundos_para_responder"] = int(row["respondeu_em"] - row["enviado_em"])
    if row.get("automatica"):
        result["houve_resposta_automatica"] = True
    return result


def owner_test_persona(rng: random.Random | None = None) -> dict[str, Any]:
    """Data of a real business still in the queue, copied (never touched) to dress the owner's test."""
    with connect() as c:
        row = c.execute("SELECT p.numero FROM sdr_prospects p JOIN leads l ON l.numero=p.numero WHERE p.status='fila' "
                        "AND l.nome IS NOT NULL AND l.nome<>'' AND l.fonte<>? ORDER BY RANDOM() LIMIT 1", (leads.TEST_SOURCE,)).fetchone()
        data = leads.lead(row[0], c) if row else None
    if data:
        return data
    return {"nome": "Clínica Sorriso (teste)", "nicho": "clínica odontológica", "cidade": "São José", "uf": "SC",
            "horario_resumo": "seg a sex 8h–18h, sáb 8h–12h"}


def simulate_owner_test(numero: str, jid: str, conversation: int, data: dict[str, Any], text: str, now: float | None = None) -> None:
    """The owner plays a tested business: a prospect row as if the test had just gone out to them. The persona is
    copied to the lead tables under the owner's number (fonte 'teste_do_dono'), never over a real lead."""
    now = time.time() if now is None else now
    with connect() as c:
        c.execute("DELETE FROM sdr_prospects WHERE numero=?", (numero,))
        leads.delete(numero, fonte=leads.TEST_SOURCE, c=c)
        if not c.execute("SELECT 1 FROM leads WHERE numero=?", (numero,)).fetchone():
            leads.save(numero, {k: v for k, v in (data or {}).items() if k in FIELDS and v not in (None, "")}, fonte=leads.TEST_SOURCE, c=c, now=now)
        c.execute("INSERT INTO sdr_prospects(numero,dados,status,enfileirado,jid,conversation,texto,enviado_em,erro) VALUES (?,?,?,?,?,?,?,?,?)",
                  (numero, json.dumps({**data, "teste_do_dono": True}, ensure_ascii=False), "enviado", now, jid, conversation, text, now, "simulação do dono"))


def clear_owner_test(numero: str) -> None:
    with connect() as c:
        c.execute("DELETE FROM sdr_prospects WHERE numero=? AND erro='simulação do dono'", (numero,))
        leads.delete(numero, fonte=leads.TEST_SOURCE, c=c)


def replied(jid: str, ts: float | None = None) -> bool:
    """First message of a tested business after the test: keep the time (the agent may later say it was automatic)."""
    row = for_jid(jid)
    if not row or row.get("respondeu_em"):
        return False
    update(row["numero"], respondeu_em=time.time() if ts is None else ts, status="respondeu")
    return True


def greeting(local: datetime) -> str:
    return "Bom dia" if local.hour < 12 else "Boa tarde" if local.hour < 18 else "Boa noite"


def test_text(local: datetime, rng: random.Random | None = None) -> str:
    template = (rng or random).choice(PROSPECT_TEST_TEXTS)
    hello = greeting(local)
    return template.format(saudacao=hello, saudacao_min=hello.lower())


def pitch_send_at(after_ts: float, seed: float | None = None) -> float:
    """Next business day (Mon-Fri) after `after_ts`, at a random minute of PROSPECT_PITCH_WINDOW."""
    rng = random.Random(after_ts if seed is None else seed)
    day = datetime.fromtimestamp(after_ts, sdr.BUSINESS_TZ) + timedelta(days=1)
    while day.weekday() >= 5 or day.strftime("%Y-%m-%d") in PROSPECT_SKIP_DATES:
        day += timedelta(days=1)
    start, _, end = PROSPECT_PITCH_WINDOW.partition("-")
    first, last = minutes(start), max(minutes(start), minutes(end) - 1)
    minute = rng.randint(first, last)
    return day.replace(hour=minute // 60, minute=minute % 60, second=rng.randint(0, 59), microsecond=0).timestamp()


def when_label(sent_ts: float, pitch_ts: float) -> str:
    """'ontem às 20h12' or 'na sexta às 20h12', seen from the day of the follow-up."""
    sent = datetime.fromtimestamp(sent_ts, sdr.BUSINESS_TZ)
    pitch = datetime.fromtimestamp(pitch_ts, sdr.BUSINESS_TZ)
    hour = f"{sent.hour}h{sent.minute:02d}"
    days = (pitch.date() - sent.date()).days
    if days <= 0:
        return f"hoje às {hour}"
    if days == 1:
        return f"ontem às {hour}"
    return f"{WEEKDAY_ON[sent.weekday()]} às {hour}"


def pitch_text(sent_ts: float, pitch_ts: float, automatic: bool = False, gancho: str = "", seconds: int | None = None) -> str:
    """The single follow-up: the real day and hour of the test, no blame, a true detail of the business
    (`gancho`, from the enriched list), the agent as the demo, and an exit."""
    when = when_label(sent_ts, pitch_ts)
    when = when[0].upper() + when[1:]
    if automatic:
        speed = f" em {seconds} segundos" if seconds is not None and seconds < 120 else ""
        fact = (f"{when} mandei uma pergunta e a boas-vindas automática de vocês chegou{speed}, ótimo. "
                "Mas depois dela ninguém continuou a conversa, e é aí que o cliente desiste: a boas-vindas segura um minuto, "
                "não a noite inteira. Confesso que era um teste.")
    else:
        fact = (f"{when} mandei uma mensagem perguntando se vocês estavam atendendo e ela ficou sem resposta, "
                "o que é normal: a essa hora a equipe já foi pra casa. Confesso que era um teste.")
    detail = (gancho.strip().rstrip(".") + ". ") if gancho and gancho.strip() else ""
    return (
        "Oi! Aqui é o Talles, de Florianópolis. " + fact + "\n\n"
        + detail
        + "Eu instalo um atendente de IA que responde nessa hora, no número de vocês, faz as perguntas que a equipe faria "
        "e passa o contato pronto, com resumo, pra quem fecha.\n\n"
        "Se você responder aqui, quem te atende é ele, pra você ver como ficaria aí. "
        "Se não fizer sentido, me avisa que eu não mando mais nada."
    )


def schedule_pitch(conversation: int, sent_ts: float, automatic: bool = False, now: float | None = None,
                   seconds: int | None = None) -> int | None:
    """The single follow-up of a test; the follow-up worker drops it if the business writes after `now`."""
    now = time.time() if now is None else now
    with connect() as c:
        done = c.execute("SELECT 1 FROM sdr_followups WHERE conversation=? AND stage='prospeccao' AND status IN ('pending','sent')",
                         (conversation,)).fetchone()
    if done:
        return None
    send_at = pitch_send_at(max(sent_ts, now) if automatic else sent_ts, seed=sent_ts)
    with connect() as c:
        row = c.execute("SELECT numero FROM sdr_prospects WHERE conversation=?", (conversation,)).fetchone()
        gancho = str((leads.lead(row[0], c) or {}).get("gancho") or "") if row else ""
    return sdr.add_followup(conversation, send_at, pitch_text(sent_ts, send_at, automatic, gancho, seconds), "retomada única do teste de atendimento",
                            after_ts=now, stage="prospeccao")


def automatic_reply(conversation: int, now: float | None = None) -> int | None:
    """The agent recorded that the answer was an automatic greeting: no human answered, so the follow-up goes back to the queue."""
    with connect() as c:
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT * FROM sdr_prospects WHERE conversation=? AND enviado_em IS NOT NULL", (conversation,)).fetchone()
    if not row:
        return None
    seconds = int(row["respondeu_em"] - row["enviado_em"]) if row["respondeu_em"] else None
    update(row["numero"], automatica=1, respondeu_em=None, status="automatica")
    if not PROSPECT_PITCH_AUTOMATIC:
        return None
    # Only a greeting and then silence (Talles, 09/10): one differential message, the next business morning.
    return schedule_pitch(conversation, row["enviado_em"], automatic=True, now=now, seconds=seconds)


BOT_LOOP_WINDOW = int(os.getenv("PROSPECT_BOT_LOOP_WINDOW_SECONDS", "600"))
BOT_LOOP_LIMIT = int(os.getenv("PROSPECT_BOT_LOOP_LIMIT", "4"))


def bot_loop(conversation: int, now: float | None = None) -> bool:
    """A prospect conversation where the agent already replied BOT_LOOP_LIMIT times in BOT_LOOP_WINDOW:
    the other side is probably a bot answering in seconds. The bridge pauses before sending again."""
    now = time.time() if now is None else now
    with connect() as c:
        if not c.execute("SELECT 1 FROM sdr_prospects WHERE conversation=?", (conversation,)).fetchone():
            return False
        replies = c.execute("SELECT COUNT(*) FROM sdr_corrections WHERE conversation=? AND created>=?",
                            (conversation, now - BOT_LOOP_WINDOW)).fetchone()[0]
    return replies >= BOT_LOOP_LIMIT


def next_gap() -> float:
    return random.uniform(PROSPECT_MIN_GAP, max(PROSPECT_MIN_GAP, PROSPECT_MAX_GAP))


def stats(now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    with connect() as c:
        by_status = dict(c.execute("SELECT status, COUNT(*) FROM sdr_prospects GROUP BY status").fetchall())
        answered = sorted(r[0] for r in c.execute("SELECT (respondeu_em-enviado_em)/60.0 FROM sdr_prospects WHERE respondeu_em IS NOT NULL"))
        pitches = dict(c.execute("SELECT status, COUNT(*) FROM sdr_followups WHERE stage='prospeccao' GROUP BY status").fetchall())
        convs = [r[0] for r in c.execute("SELECT conversation FROM sdr_prospects WHERE conversation IS NOT NULL")]
        marks = ",".join("?" * len(convs))
        talks = c.execute(f"SELECT COUNT(*) FROM sdr_leads WHERE conversation IN ({marks})", convs).fetchone()[0] if convs else 0
        next_step = c.execute(f"SELECT COUNT(DISTINCT conversation) FROM sdr_records WHERE field='proximo_passo' AND conversation IN ({marks})",
                              convs).fetchone()[0] if convs else 0
    return {
        "ligada": enabled(),
        "na_janela_agora": in_window(datetime.fromtimestamp(now, sdr.BUSINESS_TZ)),
        "janela": PROSPECT_WINDOWS,
        "teto_hoje": daily_cap(now),
        "rampa": PROSPECT_RAMP,
        "intervalo_segundos": [PROSPECT_MIN_GAP, PROSPECT_MAX_GAP],
        "enviados_hoje": sent_today(now),
        "por_status": by_status,
        "responderam": len(answered),
        "mediana_minutos_resposta": round(answered[len(answered) // 2], 1) if answered else None,
        "retomadas": pitches,
        "conversas": talks,
        "com_proximo_passo": next_step,
    }
