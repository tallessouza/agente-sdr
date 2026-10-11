"""Retomadas: templates to leads whose 24 h window is closed (Talles, 10/10/2026).

"Temos fup de janela aberta e depois de retomada durante a semana, em todos os casos é quebrando objeções,
removendo incertezas." Three families: `sem_resposta` (never answered the test), `robo` (only a robot answered),
`conversa` (a person talked and went quiet). The bridge lists who may get one (candidates), the brain writes the
variables for each lead (the layer of Hormozi's onion) and schedules it inside the business's hours, and the
prospect worker sends it in the MARKETING slot of the 80/20 ("conta no 80/20", Talles 10/10): it only moves
together with the first contacts. At most one per conversation every RETOMADA_EVERY_DAYS, RETOMADA_MAX in total.
"""
import json
import os
import random
import sqlite3
import time
from typing import Any

import cloud
import prospeccao
import sdr
import template_health

RETOMADA_EVERY_DAYS = int(os.getenv("RETOMADA_EVERY_DAYS", "7"))
RETOMADA_MAX = int(os.getenv("RETOMADA_MAX", "2"))
# The never-answered get their first retomada only the next day.
RETOMADA_FIRST_AFTER = int(os.getenv("RETOMADA_FIRST_AFTER_SECONDS", str(18 * 3600)))
PARAM_MAX = 300


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
    if family == "sem_resposta" and now - float(row.get("enviado_em") or now) < RETOMADA_FIRST_AFTER:
        return None
    past = history(int(conversation))
    if any(r["status"] == "pendente" for r in past):
        return None
    sent = [r for r in past if r["status"] == "enviada"]
    if len(sent) >= RETOMADA_MAX or (sent and now - float(sent[-1]["enviado_em"] or 0) < RETOMADA_EVERY_DAYS * 86400):
        return None
    return family


def candidates(now: float | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Who may get a retomada now, with the approved template the brain must fill."""
    now = time.time() if now is None else now
    by_family: dict[str, list[dict[str, Any]]] = {}
    for t in template_health.retomada_pool():
        by_family.setdefault(t["familia"], []).append(t)
    with prospeccao.connect() as c:
        c.row_factory = sqlite3.Row
        rows = [dict(r) for r in c.execute("SELECT * FROM sdr_prospects WHERE jid LIKE '%@cloud' AND conversation IS NOT NULL ORDER BY enviado_em")]
    out = []
    for row in rows:
        family = eligible(row, now)
        if not family or not by_family.get(family):
            continue
        template = random.choice(by_family[family])
        out.append({"conversation_id": int(row["conversation"]), "familia": family, "template": {"name": template["name"], "text": template["text"]},
                    "negocio": json.loads(row.get("dados") or "{}"), "teste_enviado_em": row.get("enviado_em"), "respondeu_em": row.get("respondeu_em"),
                    "retomadas_anteriores": [{"familia": r["familia"], "status": r["status"], "params": json.loads(r["params"])}
                                             for r in history(int(row["conversation"]))]})
        if len(out) >= limit:
            break
    return out


def clean(value: Any) -> str:
    """Meta refuses line breaks and tabs inside a variable: one line, single spaces."""
    return " ".join(str(value or "").split())[:PARAM_MAX]


def schedule(conversation: int, familia: str, template: str, params: list[Any], send_at: float, send_until: float, motivo: str = "") -> int:
    if template not in template_health.RETOMADAS:
        raise ValueError("template desconhecido")
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
