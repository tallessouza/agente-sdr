"""Retomadas: templates to leads whose 24 h window is closed (Talles, 10/10/2026).

"Temos fup de janela aberta e depois de retomada durante a semana, em todos os casos é quebrando objeções,
removendo incertezas." Three families: `sem_resposta` (never answered the test), `robo` (only a robot answered),
`conversa` (a person talked and went quiet). The bridge lists who may get one (candidates), the brain writes the
variables for each lead (the layer of Hormozi's onion) and schedules it inside the business's hours, and the
prospect worker sends it in the MARKETING slot of the 80/20 ("conta no 80/20", Talles 10/10): it only moves
together with the first contacts. One per working day, RETOMADA_MAX in total, only for the businesses that never answered
(the others follow the brain's sequence).
"""
import json
import os
from datetime import datetime
import random
import sqlite3
import time
from typing import Any

import cloud
import leads
import prospeccao
import sdr
import template_health

# Talles 11/10: "cadência diária dos próximos dias durante a semana": one a working day, at most RETOMADA_MAX.
RETOMADA_EVERY_SECONDS = int(os.getenv("RETOMADA_EVERY_SECONDS", str(20 * 3600)))
RETOMADA_MAX = int(os.getenv("RETOMADA_MAX", "3"))
# Who talked and went quiet (conversa) and robots follow the brain's sequence (4 touches + c1..c3); the bridge's
# candidates are only the businesses that never answered the test.
RETOMADA_FAMILIES = set(os.getenv("RETOMADA_FAMILIES", "sem_resposta").split(","))
# The never-answered get their first retomada only the next day.
RETOMADA_FIRST_AFTER = int(os.getenv("RETOMADA_FIRST_AFTER_SECONDS", str(18 * 3600)))
PARAM_MAX = 300
# No weekly retomada while the 4-touch sequence of the conversation is still going (text or template touches).
SEQUENCE_QUIET = int(os.getenv("RETOMADA_SEQUENCE_QUIET_SECONDS", str(4 * 86400)))


# Talles 11/10: whoever got the opening and did not answer gets 3 more touches by template (retomadas) inside 24 h of
# it: 6 h apart, 2 h when 6 h falls outside the business's hours, only while it is open (9h–20h at most).
SLOTS = 3
IDEAL_GAP, MIN_GAP = 6 * 3600, 2 * 3600
SEND_HOURS = (9.0, 20.0)
DEFAULT_HOURS = {d: [(9.0, 18.0)] for d in range(5)}  # no hours on file: weekdays 9h–18h


def business_hours(numero: str) -> dict[int, list[tuple[float, float]]]:
    out: dict[int, list[tuple[float, float]]] = {}
    for h in leads.horarios(numero):
        if h["fechado"]:
            out.setdefault(int(h["dia"]), [])
        elif h["aberto_24h"]:
            out.setdefault(int(h["dia"]), []).append((0.0, 24.0))
        elif h.get("abre") and h.get("fecha"):
            a = int(h["abre"][:2]) + int(h["abre"][3:5]) / 60
            b = int(h["fecha"][:2]) + int(h["fecha"][3:5]) / 60
            out.setdefault(int(h["dia"]), []).append((a, b if b > a else 24.0))
    return out or DEFAULT_HOURS


def open_spans(numero: str, start: float, end: float) -> list[tuple[float, float]]:
    hours = business_hours(numero)
    spans = []
    day = datetime.fromtimestamp(start, sdr.BUSINESS_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    while day.timestamp() < end:
        if day.strftime("%Y-%m-%d") not in prospeccao.PROSPECT_SKIP_DATES:
            for a, b in hours.get(day.weekday(), []):
                a, b = max(a, SEND_HOURS[0]), min(b, SEND_HOURS[1])
                if b > a:
                    spans.append((day.timestamp() + a * 3600, day.timestamp() + b * 3600))
        day = datetime.fromtimestamp(day.timestamp() + 26 * 3600, sdr.BUSINESS_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    return [(max(a, start), min(b, end)) for a, b in spans if b > start and a < end]


def _first_open(t: float, end: float, spans: list[tuple[float, float]]) -> float | None:
    return next((max(a, t) for a, b in spans if b > t and max(a, t) <= end), None)


def _fits(t: float, end: float, spans: list[tuple[float, float]], n: int) -> bool:
    for _ in range(n):
        t = _first_open(t + MIN_GAP, end, spans)
        if t is None:
            return False
    return True


def slot_times(numero: str, opened: float) -> list[float]:
    """When the 3 retomadas after the opening go: inside 24 h of it, each as close to 6 h after the previous one as
    still lets the rest fit, never under 2 h, only in the business's open hours. What does not fit in 24 h goes at the
    next openings after it (the touches matter more than the 24 h, Talles 10/10)."""
    for end in (opened + 24 * 3600, opened + 7 * 86400):
        spans = open_spans(numero, opened, end)
        out, previous = [], opened
        for left in range(SLOTS, 0, -1):
            chosen = None
            # 6 h while it is open; closer (down to 2 h) while it is still open; else the next opening.
            for gap in range(IDEAL_GAP, MIN_GAP - 1, -1800):
                t = previous + gap
                if t <= end and any(a <= t < b for a, b in spans) and _fits(t, end, spans, left - 1):
                    chosen = t
                    break
            if chosen is None:
                first = _first_open(previous + MIN_GAP, end, spans)
                if first is not None and _fits(first, end, spans, left - 1):
                    chosen = first
            if chosen is None:
                break
            out.append(chosen)
            previous = chosen
        if len(out) == SLOTS:
            return out
    return out


def connect() -> sqlite3.Connection:
    c = sdr.connect()
    c.execute("CREATE TABLE IF NOT EXISTS sdr_retomadas (id INTEGER PRIMARY KEY, conversation INTEGER NOT NULL, familia TEXT NOT NULL, "
              "template TEXT NOT NULL, params TEXT NOT NULL, send_at REAL NOT NULL, send_until REAL NOT NULL, motivo TEXT, "
              "status TEXT NOT NULL DEFAULT 'pendente', erro TEXT, criado REAL NOT NULL, enviado_em REAL)")
    return c


def history(conversation: int) -> list[dict[str, Any]]:
    with connect() as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute("SELECT * FROM sdr_retomadas WHERE conversation=? ORDER BY id", (conversation,))]


def family_of(row: dict[str, Any], records: dict[str, Any], last_lead: float | None) -> str:
    if not last_lead and not row.get("respondeu_em"):
        return "sem_resposta"
    return "robo" if sdr.robot_records(records) else "conversa"


def eligible(row: dict[str, Any], now: float) -> str | None:
    """The family of the retomada this prospect may get now, or None."""
    conversation = row.get("conversation")
    if not conversation or not str(row.get("jid") or "").endswith("@cloud") or row.get("status") not in {"enviado", "respondeu", "automatica"}:
        return None
    if sdr.is_owner(str(row.get("jid") or "")):
        return None
    last_lead, _ = sdr.activity(int(conversation))
    if last_lead and cloud.window_open(last_lead, now):
        return None  # free text still possible: the touches handle it
    records = sdr.records_of(int(conversation))
    if str(records.get("opt_out") or "").strip().lower() == "sim" or sdr.outcome_stops_touches(int(conversation)):
        return None
    family = family_of(row, records, last_lead)
    if family not in RETOMADA_FAMILIES:
        return None
    if family == "sem_resposta":
        # The 3 touches after the opening, at slot_times (Talles 11/10), not one a working day.
        past = history(int(conversation))
        if any(r["status"] in {"pendente", "enviando"} for r in past):
            return None
        sent = [r for r in past if r["status"] == "enviada"]
        slots = slot_times(str(row.get("numero") or ""), float(row.get("enviado_em") or now))
        if len(sent) >= min(SLOTS, len(slots)) or now < slots[len(sent)]:
            return None
        if sent and now - float(sent[-1]["enviado_em"] or 0) < MIN_GAP:
            return None
        return family
    today = datetime.fromtimestamp(now, sdr.BUSINESS_TZ)
    holidays = set(((sdr.offers().get("atendimento") or {}).get("feriados")) or [])
    if today.weekday() >= 5 or today.strftime("%Y-%m-%d") in holidays:
        return None  # working days only
    if family == "sem_resposta" and now - float(row.get("enviado_em") or now) < RETOMADA_FIRST_AFTER:
        return None
    past = history(int(conversation))
    if any(r["status"] == "pendente" for r in past):
        return None
    with connect() as c:
        recent_touch = c.execute("SELECT MAX(sent_at) FROM sdr_followups WHERE conversation=? AND status='sent'", (int(conversation),)).fetchone()[0]
    if recent_touch and now - float(recent_touch) < SEQUENCE_QUIET:
        return None  # the 4-touch sequence is still running (its later touches come as templates from the brain)
    if any(r["status"] in {"enviada", "enviando"} and now - float(r["enviado_em"] or r["criado"]) < SEQUENCE_QUIET for r in past):
        return None
    sent = [r for r in past if r["status"] == "enviada"]
    if len(sent) >= RETOMADA_MAX or (sent and now - float(sent[-1]["enviado_em"] or 0) < RETOMADA_EVERY_SECONDS):
        return None
    return family


def day_counts(now: float | None = None) -> tuple[int, int]:
    """(utility, marketing) retomadas of the day for their own 80/20: the ones sent plus the ones scheduled and waiting."""
    now = time.time() if now is None else now
    day = datetime.fromtimestamp(now, sdr.BUSINESS_TZ).strftime("%Y-%m-%d")
    utility = int(prospeccao.kv_get(f"tpl:{day}:RET_UTILITY") or 0)
    marketing = int(prospeccao.kv_get(f"tpl:{day}:RET_MARKETING") or 0)
    category = {t["name"]: t.get("category") for t in template_health.retomada_pool()}
    with connect() as c:
        for (name,) in c.execute("SELECT template FROM sdr_retomadas WHERE status='pendente'"):
            utility += category.get(name) == "UTILITY"
            marketing += category.get(name) == "MARKETING"
    return utility, marketing


def pick(familia: str, now: float | None = None) -> dict[str, Any] | None:
    """The template for the next retomada of the family, by the retomadas' own 80/20 (Talles 11/10)."""
    return template_health.pick_retomada(familia, *day_counts(now))


def candidates(now: float | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Who may get a retomada now, with the approved template the brain must fill."""
    now = time.time() if now is None else now
    with prospeccao.connect() as c:
        c.row_factory = sqlite3.Row
        rows = [dict(r) for r in c.execute("SELECT * FROM sdr_prospects WHERE jid LIKE '%@cloud' AND conversation IS NOT NULL ORDER BY enviado_em")]
    out = []
    for row in rows:
        family = eligible(row, now)
        template = pick(family, now) if family else None
        if not template:
            continue  # no family, or the retomadas' 80/20 has no template for it yet (no UTILITY approved)
        out.append({"conversation_id": int(row["conversation"]), "familia": family, "template": {"name": template["name"], "text": template["text"]},
                    "negocio": leads.lead(row["numero"]) or {}, "teste_enviado_em": row.get("enviado_em"), "respondeu_em": row.get("respondeu_em"),
                    "retomadas_anteriores": [{"familia": r["familia"], "status": r["status"], "params": json.loads(r["params"])}
                                             for r in history(int(row["conversation"]))]})
        if len(out) >= limit:
            break
    return out


def clean(value: Any) -> str:
    """Meta refuses line breaks and tabs inside a variable: one line, single spaces."""
    return " ".join(str(value or "").split())[:PARAM_MAX]


def schedule(conversation: int, familia: str, template: str, params: list[Any], send_at: float, send_until: float, motivo: str = "") -> int:
    if template not in {t["name"] for t in template_health.retomada_pool()}:
        raise ValueError("template desconhecido ou não aprovado")
    values = [clean(p) for p in params]
    if len(values) != 3 or not all(values):
        raise ValueError("os 3 parâmetros são obrigatórios")
    if sdr.leaked_terms(values):
        raise ValueError("termos internos nos parâmetros")
    with connect() as c:
        c.execute("UPDATE sdr_retomadas SET status='substituida' WHERE conversation=? AND status='pendente'", (conversation,))
        return int(c.execute("INSERT INTO sdr_retomadas(conversation,familia,template,params,send_at,send_until,motivo,criado) VALUES (?,?,?,?,?,?,?,?)",
                             (conversation, familia, template, json.dumps(values, ensure_ascii=False), send_at, send_until, motivo[:500], time.time())).lastrowid)


def due(now: float | None = None) -> dict[str, Any] | None:
    """The oldest retomada whose send time has come; the ones past their business window expire (the brain plans again)."""
    now = time.time() if now is None else now
    with connect() as c:
        c.execute("UPDATE sdr_retomadas SET status='expirada' WHERE status='pendente' AND send_until < ?", (now,))
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT * FROM sdr_retomadas WHERE status='pendente' AND send_at <= ? ORDER BY send_at LIMIT 1", (now,)).fetchone()
    return dict(row) if row else None


def render(row: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    template = next((t for t in template_health.retomada_pool() if t["name"] == row["template"]), None)
    if not template:
        return None
    values = json.loads(row["params"])
    text = template["text"]
    for index, value in enumerate(values, start=1):
        text = text.replace("{{%d}}" % index, value)
    return text, {"name": template["name"], "category": template.get("category") or "MARKETING", "language": template.get("language", "pt_BR"),
                  "processed_params": {str(i): v for i, v in enumerate(values, start=1)}}


def mark(retomada_id: int, status: str, erro: str = "") -> None:
    with connect() as c:
        c.execute("UPDATE sdr_retomadas SET status=?, erro=?, enviado_em=CASE WHEN ?='enviada' THEN ? ELSE enviado_em END WHERE id=?",
                  (status, erro[:300], status, time.time(), retomada_id))
