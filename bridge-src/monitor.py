"""Conversation monitor (Talles, 10/10/2026: "ficar olhando as conversas e impedir que o agente faça merda").

Two layers:
  * pre_send(): runs on every agent reply right before it goes out. In a prospect conversation (offer
    "atendimento") it holds anything about the other offers or any price, and the generic "let me check with
    Talles" fallback. A held reply is not sent: the conversation pauses and the draft goes to a private note.
  * patrol(): every MONITOR_SECONDS, looks at the recent official-number conversations for what slipped through
    (repeated text, a burst without reply, a reply after an opt-out, model error text, talking on to a robot).
Every alert pauses the conversation, leaves a private note with the reason, tags it `monitor-alerta` and is kept
in the monitor_alertas table (once per conversation, rule and message) for the dashboard.
"""
import json
import logging
import os
import re
import sqlite3
import time
import unicodedata
from typing import Any

import httpx

logger = logging.getLogger("bridge.monitor")

DB_PATH = os.getenv("BRIDGE_DB", "/data/bridge.db")
CHATWOOT_URL = os.getenv("CHATWOOT_URL", "http://chatwoot_rails:3000").rstrip("/")
CHATWOOT_ACCOUNT_ID = os.getenv("CHATWOOT_ACCOUNT_ID", "")
CHATWOOT_APP_TOKEN = os.getenv("CHATWOOT_APP_TOKEN", "")
MONITOR_SECONDS = int(os.getenv("MONITOR_SECONDS", "300"))
MONITOR_WINDOW = int(os.getenv("MONITOR_WINDOW_SECONDS", str(3 * 3600)))
BURST_LIMIT = int(os.getenv("MONITOR_BURST_LIMIT", "4"))
LABEL = os.getenv("MONITOR_LABEL", "monitor-alerta")


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", text).strip()


# What never goes out in a prospect conversation (the attendant offer has no price in chat, and the other
# offers are a different conversation).
OFFTOPIC = [
    (r"r\$\s*\d", "preço na conversa"),
    (r"\b\d+\s*(mil|reais)\b", "preço na conversa"),
    (r"\btelegram\b", "oferta do Instalador (Telegram)"),
    (r"\bcodex\b|\bchatgpt\b|\bconta do gemini\b", "oferta do Instalador (assinatura de IA)"),
    (r"\btime de ia\b|\btime instalado\b", "oferta do Instalador (time de IA)"),
    (r"\bservidor\b|\bvps\b", "oferta do Instalador (servidor)"),
    (r"\braio[ -]?x\b", "oferta do Raio-X"),
    (r"pronto em 48", "garantia do Instalador"),
]
# Model or gateway errors returned as if they were a reply (10/10: "All credentials ... cooling down").
# Internal product names stay with sdr.leaked_terms, which knows the allowed uses ("a Conta do Gemini").
ERROR_TEXT = [r"cooling down", r"rate[ _-]?limit", r"\b429\b", r"\bcredentials?\b", r"model_cooldown", r"internal server error",
              r"traceback", r"\bomniroute\b"]
OPT_OUT = [r"nao (tenho|temos) interesse", r"\bpare\b", r"\bparar de\b", r"nao quero", r"\bremov", r"\bsair da lista\b",
           r"nao me (mande|manda|envie)", r"\bdescadastr", r"\bspam\b", r"\bbloque", r"nao (mande|manda) mais"]


def offer_violations(parts: list[str], offer: str | None) -> list[str]:
    if offer != "atendimento":
        return []
    found = []
    for part in parts:
        folded = fold(part)
        for pattern, reason in OFFTOPIC:
            if re.search(pattern, folded) and reason not in found:
                found.append(reason)
    return found


def error_violations(parts: list[str]) -> list[str]:
    return [f"texto interno ou de erro: {p}" for p in ERROR_TEXT if any(re.search(p, fold(x)) for x in parts)]


def pre_send(parts: list[str], offer: str | None, fallback: str) -> list[str]:
    """Reasons to hold this reply; empty list = send it."""
    reasons = offer_violations(parts, offer) + error_violations(parts)
    if offer == "atendimento" and any(fold(p) == fold(fallback) for p in parts):
        reasons.append("frase de espera (\"confirmar com o Talles\") numa prospecção")
    return reasons


def connect() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS monitor_alertas (id INTEGER PRIMARY KEY, conversation INTEGER NOT NULL, regra TEXT NOT NULL, "
              "detalhe TEXT, chave TEXT UNIQUE NOT NULL, criado REAL NOT NULL, resolvido REAL)")
    c.commit()
    return c


def remember(conversation: int, regra: str, detalhe: str, chave: str) -> bool:
    """True the first time this alert is seen (one per conversation, rule and message)."""
    with connect() as c:
        return bool(c.execute("INSERT OR IGNORE INTO monitor_alertas(conversation,regra,detalhe,chave,criado) VALUES (?,?,?,?,?)",
                              (conversation, regra, detalhe[:1000], chave, time.time())).rowcount)


def recent_alerts(limit: int = 50) -> list[dict[str, Any]]:
    with connect() as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute("SELECT * FROM monitor_alertas ORDER BY criado DESC LIMIT ?", (limit,))]


TURN_GAP = int(os.getenv("MONITOR_TURN_GAP_SECONDS", "90"))
BURST_WINDOW = int(os.getenv("MONITOR_BURST_WINDOW_SECONDS", "1800"))


def agent_turns(messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Agent messages grouped into turns: one reply split in short parts (seconds apart) is one turn."""
    turns: list[list[dict[str, Any]]] = []
    last = None
    for m in messages:
        if m.get("message_type") == 0:
            last = None
            continue
        if not (m.get("message_type") == 1 and (m.get("content_attributes") or {}).get("bridge_agent")):
            continue
        if last is not None and m["created_at"] - last["created_at"] <= TURN_GAP:
            turns[-1].append(m)
        else:
            turns.append([m])
        last = m
    return turns


def patrol_findings(messages: list[dict[str, Any]], robot: bool = False) -> list[tuple[str, str, str]]:
    """(rule, detail, message id) for one conversation; messages oldest first, public only."""
    findings: list[tuple[str, str, str]] = []
    ours = [m for m in messages if m.get("message_type") == 1]
    seen: dict[str, Any] = {}
    for m in ours:
        key = fold(m.get("content"))
        if len(key) > 20 and key in seen:
            findings.append(("mensagem repetida", m.get("content", "")[:200], str(m["id"])))
        seen.setdefault(key, m)
    # Turns without a reply from the lead in between, inside a short window: the agent talking to itself.
    run: list[list[dict[str, Any]]] = []
    previous_end = None
    for turn in agent_turns(messages):
        lead_between = previous_end is not None and any(
            m.get("message_type") == 0 and previous_end["created_at"] < m["created_at"] < turn[0]["created_at"] for m in messages)
        run = [turn] if lead_between or not run else run + [turn]
        previous_end = turn[-1]
        recent = [t for t in run if turn[-1]["created_at"] - t[0]["created_at"] <= BURST_WINDOW]
        if len(recent) == BURST_LIMIT:
            findings.append(("muitas mensagens seguidas sem resposta", f"{len(recent)} turnos do agente em até {BURST_WINDOW // 60} min sem o lead responder", str(turn[-1]["id"])))
    opted_out_at = None
    for m in messages:
        if m.get("message_type") == 0 and any(re.search(p, fold(m.get("content"))) for p in OPT_OUT):
            opted_out_at = m["created_at"]
        elif opted_out_at and m.get("message_type") == 1 and m["created_at"] > opted_out_at and (m.get("content_attributes") or {}).get("bridge_agent"):
            findings.append(("resposta depois de pedido para parar", m.get("content", "")[:200], str(m["id"])))
            break
    for m in ours:
        if (m.get("content_attributes") or {}).get("bridge_agent"):
            for reason in error_violations([m.get("content", "")]):
                findings.append(("texto interno vazou", reason, str(m["id"])))
    if robot:
        # Touches (bridge_followup) are spaced 2 h apart and speak to the owner: they are not talking to the robot.
        turns = [t for t in agent_turns(messages) if not all((m.get("content_attributes") or {}).get("bridge_followup") for m in t)]
        if len(turns) > 2:  # the test and one colleague message (in short parts), then silence
            findings.append(("seguiu conversando com robô", f"{len(turns)} turnos nossos numa conversa com robô", str(turns[-1][-1]["id"])))
    return findings


async def messages_of(conversation: int) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{CHATWOOT_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation}/messages",
                             headers={"api_access_token": CHATWOOT_APP_TOKEN})
        r.raise_for_status()
    rows = [m for m in r.json().get("payload") or [] if m.get("message_type") in (0, 1) and not m.get("private")]
    for m in rows:
        attributes = m.get("content_attributes")
        if isinstance(attributes, str):
            try:
                m["content_attributes"] = json.loads(attributes)
            except json.JSONDecodeError:
                m["content_attributes"] = {}
    return sorted(rows, key=lambda m: m["created_at"])


async def alert(conversation: int, regra: str, detalhe: str, chave: str, pause: Any, note: Any, label: Any) -> bool:
    if not remember(conversation, regra, detalhe, chave):
        return False
    logger.warning("Monitor alert conversation=%s rule=%s", conversation, regra)
    try:
        await pause(conversation)
        await note(conversation, f"🚨 Monitor: {regra}. A conversa foi pausada; retome tirando o rótulo hermes-pausado.\n\n{detalhe}")
        await label(conversation, LABEL)
    except Exception:
        logger.exception("Monitor could not act on conversation=%s", conversation)
    return True


async def patrol(conversations: list[tuple[int, bool]], pause: Any, note: Any, label: Any) -> int:
    """conversations: (conversation id, talking to a robot?) with recent activity. Returns new alerts."""
    raised = 0
    for conversation, robot in conversations:
        try:
            messages = await messages_of(conversation)
        except Exception:
            logger.warning("Monitor could not read conversation=%s", conversation, exc_info=True)
            continue
        for regra, detalhe, message_id in patrol_findings(messages, robot):
            raised += await alert(conversation, regra, detalhe, f"{conversation}:{regra}:{message_id}", pause, note, label)
    return raised
