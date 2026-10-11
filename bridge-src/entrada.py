"""Entrada pelo "TESTE" do Instagram (Talles, 11/10/2026; 17-prospeccao/SDR-ENTRADA-TESTE-INSTAGRAM.md): one more
prospecting channel, where the lead writes first. The reel's CTA sends a wa.me link with a ready message from the
owner's personal phone; later the company's WhatsApp writes "Quero fazer um teste" to open the conversation.

This module recognizes both messages, labels the conversations (teste-instagram), links the owner's conversation to
the company's in the central database (table entradas, records origem / numero_empresa / conversa_dono, the company as
a lead with fonte instagram-teste), and when the company writes it tells Talles and pauses that conversation: the test
and the result are his. Everything else (the agent's answers, the follow-ups) is the same as any official conversation.
"""
import logging
import re
import sqlite3
import time
from typing import Any

import alertas
import handover
import leads
import sdr

logger = logging.getLogger("bridge.entrada")

LABEL = "teste-instagram"
CANAL = "instagram-teste"
PEDIDO = re.compile(r"quero o teste de tempo de resposta", re.I)
NUMERO_EMPRESA = re.compile(r"whatsapp da minha empresa (?:é|e)\s*:?\s*(\+?[\d(][\d\s().-]{7,})", re.I)
EMPRESA = re.compile(r"^\W*quero fazer um teste\W*$", re.I)


def connect() -> sqlite3.Connection:
    c = sdr.connect()
    c.execute("CREATE TABLE IF NOT EXISTS entradas (id INTEGER PRIMARY KEY, canal TEXT NOT NULL, conversa_dono INTEGER UNIQUE, numero_dono TEXT, "
              "numero_empresa TEXT, conversa_empresa INTEGER, status TEXT NOT NULL, criado REAL NOT NULL, atualizado REAL NOT NULL)")
    return c


def numero_de(jid: str) -> str | None:
    return leads.normalize_number(str(jid or "").split("@")[0])


def listar(limite: int = 200) -> list[dict[str, Any]]:
    with connect() as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute("SELECT * FROM entradas ORDER BY id DESC LIMIT ?", (limite,))]


async def ensure_label() -> None:
    """The label must exist in the Chatwoot account (a missing one is wiped when someone edits the conversation)."""
    try:
        current = (await sdr._chatwoot("GET", "/labels")).json().get("payload") or []
        if LABEL not in {str(l.get("title")) for l in current}:
            await sdr._chatwoot("POST", "/labels", json={"title": LABEL, "description": "Entrou pelo TESTE do Instagram",
                                                         "color": "#E1306C", "show_on_sidebar": True})
            logger.warning("Chatwoot label %s created", LABEL)
    except Exception:
        logger.exception("Could not make sure the %s label exists", LABEL)


async def _label(conversation: int) -> None:
    try:
        await sdr.add_label(conversation, LABEL)
    except Exception:
        logger.exception("Could not label conversation %s", conversation)


async def on_message(conversation: int, jid: str, content: str, now: float | None = None) -> str | None:
    """'pedido' for the owner's ready message, 'empresa' for the company's "Quero fazer um teste", else None."""
    now = time.time() if now is None else now
    numero = numero_de(jid)
    if PEDIDO.search(content or ""):
        found = NUMERO_EMPRESA.search(content)
        empresa = leads.normalize_number(found.group(1)) if found else None
        with connect() as c:
            c.execute("INSERT INTO entradas(canal,conversa_dono,numero_dono,numero_empresa,status,criado,atualizado) VALUES (?,?,?,?,?,?,?) "
                      "ON CONFLICT(conversa_dono) DO UPDATE SET numero_empresa=COALESCE(excluded.numero_empresa, entradas.numero_empresa), "
                      "atualizado=excluded.atualizado", (CANAL, conversation, numero, empresa, "pedido", now, now))
        await sdr.record(conversation, "origem", CANAL)
        if empresa:
            await sdr.record(conversation, "numero_empresa", empresa)
            leads.save(empresa, {}, fonte=CANAL)
        if numero:
            # The owner as a prospect who already answered, so the panel, the follow-ups, "para ligar" and the vigia see
            # him like any conversation. Straight SQL with status 'respondeu': never 'fila', or the queue would send a
            # cold opening to his personal phone.
            leads.save(numero, {"nome": f"Instagram · empresa …{(empresa or '')[-4:]}" if empresa else "Instagram (TESTE)"}, fonte=CANAL)
            with sdr.connect() as c:
                if c.execute("SELECT 1 FROM sqlite_master WHERE name='sdr_prospects'").fetchone():
                    c.execute("INSERT INTO sdr_prospects(numero,dados,status,enfileirado,jid,conversation,respondeu_em) VALUES (?,?,?,?,?,?,?) "
                              "ON CONFLICT(numero) DO UPDATE SET status='respondeu', jid=excluded.jid, conversation=excluded.conversation, "
                              "respondeu_em=COALESCE(sdr_prospects.respondeu_em, excluded.respondeu_em)",
                              (numero, '{"origem": "instagram-teste"}', "respondeu", now, jid, conversation, now))
        await _label(conversation)
        return "pedido"
    if EMPRESA.match(content or ""):
        with connect() as c:
            c.row_factory = sqlite3.Row
            row = c.execute("SELECT * FROM entradas WHERE numero_empresa=? ORDER BY id DESC LIMIT 1", (numero,)).fetchone()
            if row:
                c.execute("UPDATE entradas SET conversa_empresa=?, status='empresa_escreveu', atualizado=? WHERE id=?", (conversation, now, row["id"]))
        await sdr.record(conversation, "origem", CANAL)
        if row:
            await sdr.record(conversation, "conversa_dono", str(row["conversa_dono"]))
            await sdr.record(conversation, "contato_dono", str(row["numero_dono"] or ""))
        await _label(conversation)
        await handover.pause(conversation)  # the test and the result are Talles's (doc, step 5)
        dono = sdr.records_of(int(row["conversa_dono"])) if row else {}
        nome = dono.get("nome") or dono.get("decisor") or (f"…{row['numero_dono'][-4:]}" if row and row["numero_dono"] else "dono não identificado")
        texto = (f"🧪 Teste pedido pelo Instagram: {nome} (conversa #{row['conversa_dono']}) pediu o teste do WhatsApp da empresa …{(numero or '')[-4:]} "
                 f"(conversa #{conversation}). A conversa da empresa ficou pausada para você mandar o teste e o resultado." if row else
                 f"🧪 Um número escreveu \"Quero fazer um teste\" (conversa #{conversation}) sem pedido ligado pelo Instagram. Pausei a conversa.")
        try:
            await alertas.notify(f"teste_instagram:{conversation}", "teste_instagram", texto, conversation)
        except Exception:
            logger.exception("Teste pelo Instagram: alert failed conversation=%s", conversation)
        return "empresa"
    return None
