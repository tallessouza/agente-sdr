"""The result of every call Talles makes to a lead (panel next steps of 09/10: "registrar o resultado de cada ligação
(atendeu, objeção, próximo passo) e mostrar no painel"), in the central database.

One row per call: when, whether the lead answered, the result (agendou, retornar, sem_interesse, nao_atendeu,
fechou, outro), the objection in the lead's words, the next step and a note. The panel records them and shows them
in the conversation and in the funnel (a call that happened is a step past "call agendada").
"""
import sqlite3
import time
from typing import Any

import sdr

RESULTADOS = {"agendou", "retornar", "sem_interesse", "nao_atendeu", "fechou", "outro"}


def connect() -> sqlite3.Connection:
    c = sdr.connect()
    c.execute("CREATE TABLE IF NOT EXISTS ligacoes (id INTEGER PRIMARY KEY, conversation INTEGER, numero TEXT, quando REAL NOT NULL, "
              "atendeu INTEGER NOT NULL, resultado TEXT NOT NULL, objecao TEXT, proximo_passo TEXT, proximo_passo_em TEXT, nota TEXT, "
              "criado REAL NOT NULL)")
    c.execute("CREATE INDEX IF NOT EXISTS ligacoes_conversa ON ligacoes(conversation)")
    return c


def registrar(item: dict[str, Any], now: float | None = None) -> int:
    resultado = str(item.get("resultado") or "").strip()
    if resultado not in RESULTADOS:
        raise ValueError(f"resultado deve ser um de: {', '.join(sorted(RESULTADOS))}")
    conversation = int(item["conversation"]) if item.get("conversation") not in (None, "") else None
    numero = str(item.get("numero") or "") or None
    if conversation is None and not numero:
        raise ValueError("informe a conversa ou o número")
    now = time.time() if now is None else now

    def clean(key: str) -> str | None:
        return " ".join(str(item.get(key) or "").split())[:500] or None

    with connect() as c:
        if conversation is not None and not numero and c.execute("SELECT 1 FROM sqlite_master WHERE name='sdr_prospects'").fetchone():
            found = c.execute("SELECT numero FROM sdr_prospects WHERE conversation=?", (conversation,)).fetchone()
            numero = found[0] if found else None
        return int(c.execute("INSERT INTO ligacoes(conversation,numero,quando,atendeu,resultado,objecao,proximo_passo,proximo_passo_em,nota,criado) "
                             "VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (conversation, numero, float(item.get("quando") or now), 1 if item.get("atendeu") in (True, 1, "1", "sim", "true") else 0,
                              resultado, clean("objecao"), clean("proximo_passo"), clean("proximo_passo_em"), clean("nota"), now)).lastrowid)


def listar(conversation: int | None = None, limit: int = 500) -> list[dict[str, Any]]:
    with connect() as c:
        c.row_factory = sqlite3.Row
        if conversation is None:
            rows = c.execute("SELECT * FROM ligacoes ORDER BY quando DESC LIMIT ?", (limit,))
        else:
            rows = c.execute("SELECT * FROM ligacoes WHERE conversation=? ORDER BY quando DESC", (conversation,))
        return [dict(r) for r in rows]
