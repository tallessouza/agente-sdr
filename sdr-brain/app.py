"""SDR brain service: deterministic transport around an OpenAI-compatible judge."""
from __future__ import annotations

import asyncio
import json
import zlib
import logging
import os
import re
import sqlite3
import time
from contextlib import asynccontextmanager, closing
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

import crm
import enrichment
import horario
import oferta

LOGGER = logging.getLogger("sdr_brain")
BASE_DIR = Path(__file__).parent
DB_PATH = os.getenv("SDR_BRAIN_DB", "/data/sdr-brain.db")
LLM_URL = os.getenv("SDR_BRAIN_LLM_URL", "http://omniroute_omniroute:20129/v1").rstrip("/")
LLM_KEY = os.getenv("SDR_BRAIN_LLM_KEY", "")
MODEL = os.getenv("SDR_BRAIN_MODEL", "agy/gemini-3.7-flash-low")
BRIDGE_URL = os.getenv("BRIDGE_URL", "http://integration_bridge:8080").rstrip("/")
CHATWOOT_URL = os.getenv("CHATWOOT_URL", "http://chatwoot_rails:3000").rstrip("/")
CHATWOOT_ACCOUNT_ID = os.getenv("CHATWOOT_ACCOUNT_ID", "")
CHATWOOT_API_TOKEN = os.getenv("CHATWOOT_API_TOKEN", "")
BUSINESS_TZ = ZoneInfo(os.getenv("SDR_TIMEZONE", "America/Sao_Paulo"))
BUSINESS_START = int(os.getenv("SDR_BUSINESS_START_HOUR", "9"))
BUSINESS_END = int(os.getenv("SDR_BUSINESS_END_HOUR", "20"))
STAGES = [("5min", 300), ("30min", 1800), ("2h", 7200), ("d1", 86400)]
# Checkpoints que o recuperador da Kiwify cobre depois do link de compra (carrinho, Pix, até 30 min).
KIWIFY_COVERED_STAGES = {"5min", "30min", "2h"}
POST_PRICE_STAGE = ("d4", 345600)
# Prospecção (oferta atendimento): only whoever answered gets touches, and only these four,
# each breaking one objection of the Hormozi framework (fup.md); never at night (Talles, 09/10).
# The names keep the order of the objections in fup.md (tempo, fit, valor, adiamento); WHEN they go out comes
# from horario.touch_times: 4 touches inside the 24 h window, 6 h apart in the business's open hours, closer
# when closed hours eat the window (Talles, 10/10). The delays below are only the nominal spacing.
# The touch decisions carry the whole transcript: the model behind combo/sdr-brain took over 12 s on 11/10.
FUP_LLM_TIMEOUT = float(os.getenv("SDR_FUP_LLM_TIMEOUT", "45"))
ATENDIMENTO_STAGES = [("2h", 6 * 3600), ("d1", 12 * 3600), ("d3", 18 * 3600), ("d6", 24 * 3600),
                      # then the daily cadence on the following working days, by template (Talles 11/10)
                      ("c1", 48 * 3600), ("c2", 72 * 3600), ("c3", 96 * 3600)]
# Touches end 30 min before the official number's 24 h window closes ("sempre considerando a janela com 30 min
# antes de acabar", Talles 10/10); the bridge drops free text after the same 23 h 30.
ATENDIMENTO_WINDOW_SECONDS = int(os.getenv("SDR_ATENDIMENTO_WINDOW_SECONDS", str(23 * 3600 + 30 * 60)))
# Two touches never go out closer than this, whatever the stage (10/10: the Nóris got 4 in 4 minutes).
MIN_TOUCH_GAP_SECONDS = int(os.getenv("SDR_MIN_TOUCH_GAP_SECONDS", str(2 * 3600)))
# A robot (menu, automatic greeting) answered the test: "avaliar_dono" does not stop the touches, which speak to
# whoever reads the WhatsApp later, the owner ("fup pra quem conversou e parou, mesmo que bot", Talles 10/10).
ROBOT_OUTCOMES = {"avaliar_dono"}  # "desqualificado" is a person saying it does not fit (#143: closed 3 years ago)
# No touch of any kind right after the agent spoke (10/10: a same-day "next step" fired 41 s after the reveal).
MIN_SILENCE_SECONDS = int(os.getenv("SDR_MIN_SILENCE_SECONDS", "7200"))


def stages_for(offer: str | None, post_price: bool) -> list[tuple[str, int]]:
    if offer == "atendimento":
        return ATENDIMENTO_STAGES
    return STAGES + ([POST_PRICE_STAGE] if post_price else [])
# After the lead replies inside a sequence, a touch needs this much silence
# (from anyone) before it may fire; otherwise the conversation is still going.
QUIET_AFTER_REPLY_SECONDS = int(os.getenv("SDR_QUIET_AFTER_REPLY_SECONDS", "1800"))
# A next step dated without a time is due at this local hour of that day.
STEP_DUE_HOUR = int(os.getenv("SDR_STEP_DUE_HOUR", "10"))
# proximo_passo and proximo_passo_em arrive as separate records: wait a moment
# so the Chatwoot line shows both together instead of two half lines.
STEP_ACTIVITY_DELAY = float(os.getenv("SDR_STEP_ACTIVITY_DELAY", "3"))
STEP_FIELDS = ("oferta", "etapa_spiced", "proximo_passo", "proximo_passo_em")
NO = {"nao", "não", "no", "n"}

tracked: dict[int, dict[str, Any]] = {}
supervisor_running: set[int] = set()
cron_task: asyncio.Task | None = None
step_announcements: dict[int, asyncio.Task] = {}
last_step_line: dict[int, str] = {}


def prompt(name: str) -> str:
    """Read a bundled prompt on every request, allowing safe prompt updates.

    `{{PROIBIDOS}}` is filled from oferta.py, the only copy of the forbidden list.
    """
    return (BASE_DIR / "prompts" / name).read_text(encoding="utf-8").replace("{{PROIBIDOS}}", oferta.forbidden_list())


def connection() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, conversation_id INTEGER, kind TEXT, payload TEXT, ts REAL)")
    enrichment.ensure_tables(conn)
    conn.execute("CREATE TABLE IF NOT EXISTS sequences (conversation_id INTEGER PRIMARY KEY, anchor REAL NOT NULL, ended_at REAL, end_reason TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS tracked (conversation_id INTEGER PRIMARY KEY, jid TEXT, last_agent_ts REAL, source_id TEXT, updated REAL)")
    conn.execute("CREATE TABLE IF NOT EXISTS decisions (conversation_id INTEGER, stage TEXT, anchor REAL, decided INTEGER, ts REAL, motivo TEXT, disparar INTEGER, PRIMARY KEY(conversation_id, stage, anchor))")
    # The step each lead agreed to (status: pendente → cobrado by the deadline
    # touch, or encerrado on an outcome). Fed by /events/record.
    conn.execute("CREATE TABLE IF NOT EXISTS lead_steps (conversation_id INTEGER PRIMARY KEY, oferta TEXT, etapa_spiced TEXT, proximo_passo TEXT, proximo_passo_em TEXT, status TEXT, atualizado_em REAL)")
    columns ={row[1] for row in conn.execute("PRAGMA table_info(decisions)")}
    if "anchor" in columns and "motivo" not in columns:
        conn.execute("ALTER TABLE decisions ADD COLUMN motivo TEXT")
        conn.execute("ALTER TABLE decisions ADD COLUMN disparar INTEGER")
    if "anchor" not in columns:
        conn.execute("ALTER TABLE decisions RENAME TO decisions_legacy")
        conn.execute("CREATE TABLE decisions (conversation_id INTEGER, stage TEXT, anchor REAL, decided INTEGER, ts REAL, motivo TEXT, disparar INTEGER, PRIMARY KEY(conversation_id, stage, anchor))")
    conn.commit()
    return conn


def load_tracked() -> None:
    with closing(connection()) as conn:
        for cid, jid, last_agent_ts, source_id, updated in conn.execute("SELECT conversation_id,jid,last_agent_ts,source_id,updated FROM tracked"):
            tracked[int(cid)] = {"jid": jid, "last_agent_ts": last_agent_ts, "source_id": source_id, "updated": updated}


def auth(request: Request) -> None:
    token = os.getenv("SDR_BRAIN_TOKEN")
    if not token:
        raise HTTPException(503, "SDR_BRAIN_TOKEN unset")
    if request.headers.get("authorization") != f"Bearer {token}":
        raise HTTPException(401, "unauthorized")


def save_event(payload: dict[str, Any], kind: str) -> None:
    with closing(connection()) as conn:
        conn.execute("INSERT INTO events(conversation_id,kind,payload,ts) VALUES(?,?,?,?)", (payload.get("conversation_id"), kind, json.dumps(payload, ensure_ascii=False), payload.get("ts", time.time())))
        conn.commit()


def remember_exchange(payload: dict[str, Any]) -> None:
    cid = int(payload["conversation_id"])
    state = {"jid": payload.get("jid", ""), "last_agent_ts": float(payload.get("ts", time.time())), "source_id": payload.get("source_id", ""), "updated": time.time()}
    tracked[cid] = state
    with closing(connection()) as conn:
        conn.execute("INSERT INTO tracked(conversation_id,jid,last_agent_ts,source_id,updated) VALUES(?,?,?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET jid=excluded.jid,last_agent_ts=excluded.last_agent_ts,source_id=excluded.source_id,updated=excluded.updated", (cid, state["jid"], state["last_agent_ts"], state["source_id"], state["updated"]))
        conn.commit()


def forget_conversation(conversation_id: int) -> None:
    tracked.pop(conversation_id, None)
    with closing(connection()) as conn:
        conn.execute("DELETE FROM tracked WHERE conversation_id=?", (conversation_id,))
        conn.commit()
    LOGGER.info("Stopped tracking conversation %s (unknown to the bridge)", conversation_id)


def directives(text: str) -> list[str]:
    return re.findall(r"\[\[.*?\]\]", text or "", re.DOTALL)


def preserve_directives(original: str, rewritten: str) -> str:
    """Ensure every bridge directive survives an LLM rewrite verbatim."""
    result = rewritten.strip()
    for directive in directives(original):
        if directive not in result:
            result = f"{result} {directive}".strip()
    return result


def parse_json_object(content: Any) -> dict[str, Any] | None:
    """Parse the model's JSON even when wrapped in ``` fences or extra prose."""
    text = str(content or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        result = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            result = json.loads(text[start:end + 1])
        except ValueError:
            return None
    return result if isinstance(result, dict) else None


async def ask_llm(instruction: str, attempts: int = 2, timeout: float = 12) -> dict[str, Any] | None:
    headers = {"Content-Type": "application/json"}
    if LLM_KEY:
        headers["Authorization"] = f"Bearer {LLM_KEY}"
    body = {"model": MODEL, "messages": [{"role": "user", "content": instruction}], "temperature": 0, "response_format": {"type": "json_object"}}
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(f"{LLM_URL}/chat/completions", headers=headers, json=body)
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                result = parse_json_object(content)
                if result is None:
                    raise ValueError(f"no JSON object in reply: {str(content)[:120]!r}")
                return result
        except Exception as exc:
            LOGGER.warning("LLM attempt %s failed: %s %s", attempt + 1, type(exc).__name__, exc)
    return None


async def chatwoot_messages(conversation_id: int) -> list[dict[str, Any]]:
    if not CHATWOOT_ACCOUNT_ID or not CHATWOOT_API_TOKEN:
        return []
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(f"{CHATWOOT_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}/messages", headers={"api_access_token": CHATWOOT_API_TOKEN})
            response.raise_for_status()
            body = response.json()
        messages = body.get("payload", body) if isinstance(body, dict) else body
        return compact_transcript(messages)
    except Exception as exc:
        LOGGER.warning("Chatwoot transcript failed for %s: %s", conversation_id, exc)
        return []


TRANSCRIPT_LIMIT = int(os.getenv("SDR_TRANSCRIPT_LIMIT", "40"))


def compact_transcript(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chatwoot messages → [{autor, texto, quando}], oldest first, public only.

    Chatwoot message_type: 0 incoming (lead), 1 outgoing (agent/Talles/touch),
    2 activity, 3 template.
    """
    authors = {0: "lead", "incoming": "lead", 1: "agente", "outgoing": "agente"}
    rows = []
    for item in messages or []:
        if item.get("private") or item.get("message_type") not in authors:
            continue
        text = (item.get("content") or "").strip()
        if authors[item["message_type"]] == "lead":
            text = oferta.redact_credentials(text)[0]  # the bridge already does it; older messages may not be
        if not text and item.get("attachments"):
            text = "[anexo]"
        if not text:
            continue
        created = item.get("created_at")
        when = datetime.fromtimestamp(created, BUSINESS_TZ).strftime("%Y-%m-%d %H:%M") if isinstance(created, (int, float)) else str(created or "")
        rows.append({"autor": authors[item["message_type"]], "texto": text[:1500], "quando": when})
    rows.sort(key=lambda row: row["quando"])
    return rows[-TRANSCRIPT_LIMIT:]


async def bridge_post(path: str, payload: dict[str, Any]) -> None:
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(f"{BRIDGE_URL}{path}", headers={"Authorization": f"Bearer {os.getenv('SDR_BRAIN_TOKEN', '')}"}, json=payload)
    except Exception as exc:
        LOGGER.warning("Bridge POST %s failed: %s", path, exc)


PROFILE_GUIDANCE = "registre perfil_raiox = sim e siga a venda da instalação; o Talles entra depois da compra registrada"


def profile_too_early(spiced: dict[str, Any], result: dict[str, Any], payload: dict[str, Any]) -> bool:
    """Installer lead with the Raio-X profile, before the purchase: record it, keep selling."""
    motivo = oferta.fold(str(result.get("motivo", "")))
    asked = re.search(r"raio[\s-]?x|copiar a minha opera|humano|\bfalar com (?:o talles|uma pessoa|alguem|voces)|atendente", oferta.fold(str(payload.get("lead_message", ""))))
    return (spiced.get("oferta") == "instalador" and oferta.fold(str(spiced.get("comprou") or "")).strip() != "sim"
            and "perfil" in motivo and not asked)


async def supervisor(payload: dict[str, Any]) -> None:
    cid = int(payload["conversation_id"])
    if cid in supervisor_running:
        return
    supervisor_running.add(cid)
    try:
        transcript = await chatwoot_messages(cid)
        records = conversation_records(cid)
        spiced = oferta.spiced_state(records, records.get("oferta") if records.get("oferta") in oferta.OFFERS else None)
        result = await ask_llm(prompt("supervisor.md") + "\nCONTEXTO:\n" + json.dumps({"evento": payload, "spiced": spiced, "transcript": transcript}, ensure_ascii=False))
        if not isinstance(result, dict):
            return
        if result.get("escalate") and profile_too_early(spiced, result, payload):
            result = {"guidance": PROFILE_GUIDANCE, "escalate": False}
        if result.get("guidance"):
            await bridge_post("/sdr/guidance", {"conversation_id": cid, "text": str(result["guidance"])[:500]})
            await crm.activity(cid, "🧭 Orientação para o próximo turno: " + str(result["guidance"])[:500])
        if result.get("escalate"):
            await bridge_post("/sdr/escalate", {"conversation_id": cid, "motivo": str(result.get("motivo", ""))[:300], "frase": str(result.get("frase", ""))[:1000]})
    finally:
        supervisor_running.discard(cid)


async def chatwoot_contact_name(conversation_id: int) -> str:
    """WhatsApp display name as synced to Chatwoot (used only to break ties)."""
    if not CHATWOOT_ACCOUNT_ID or not CHATWOOT_API_TOKEN:
        return ""
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(f"{CHATWOOT_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}", headers={"api_access_token": CHATWOOT_API_TOKEN})
            response.raise_for_status()
            return str(((response.json().get("meta") or {}).get("sender") or {}).get("name") or "")
    except Exception as exc:
        LOGGER.warning("Chatwoot contact name failed for %s: %s", conversation_id, exc)
        return ""


IDENTITY_LABELS = {"confirmado": "confirmado", "informado": "informado pelo lead", "provavel": "provável, não usado",
                   "ambiguo": "ambíguo, não usado", "direto": "sem origem no Instagram"}


async def report_enrichment(conversation_id: int, result: dict[str, Any]) -> None:
    """Show the operator what the Instagram lookup found."""
    identity, username = result["identity"], result.get("username")
    perfil, company = result.get("perfil"), result.get("company") or ""
    status = IDENTITY_LABELS.get(identity.get("status"), identity.get("status"))
    if not username:
        await crm.activity(conversation_id, f"🔎 Instagram: {status} ({identity.get('method')}, {identity.get('candidates', 0)} candidatos na janela).")
        return
    parts = [f"🔎 Instagram @{username}: {status} ({identity.get('method')})"]
    if perfil:
        parts.append(f"{perfil.get('seguidores') or 0} seguidores, {perfil.get('posts_total') or 0} posts")
    else:
        parts.append("perfil não disponível (privado ou não profissional)")
    if result.get("campanha"):
        parts.append("veio da campanha " + " / ".join(str(v) for v in (result["campanha"].get("campanha"), result["campanha"].get("palavra")) if v))
    if company:
        parts.append(f"empresa @{company}" + ("" if result.get("perfil_empresa") else " (perfil não disponível)"))
    await crm.activity(conversation_id, " · ".join(parts) + ". Detalhes no contato.")
    await crm.update_contact(conversation_id, crm.contact_attributes(username, identity, perfil, company, result.get("perfil_empresa"), result.get("campanha")),
                             instagram=username, bio=(perfil or {}).get("bio") or "")


async def enrich(payload: dict[str, Any]) -> None:
    conversation_id = int(payload["conversation_id"])

    async def post_profile(cid: int, ficha: dict[str, Any]) -> None:
        await bridge_post("/sdr/lead-profile", {"conversation_id": cid, "profile": ficha})

    try:
        await enrichment.enrich(payload, conn_factory=connection, display_name=await chatwoot_contact_name(conversation_id),
                                post_profile=post_profile, on_result=lambda result: report_enrichment(conversation_id, result))
    except Exception:
        LOGGER.exception("Enrichment failed for conversation %s", conversation_id)


def in_business_hours(ts: float) -> bool:
    return BUSINESS_START <= datetime.fromtimestamp(ts, BUSINESS_TZ).hour < BUSINESS_END


def due_stage(age: float, post_price: bool, offer: str | None = None) -> str | None:
    """Latest checkpoint already reached in this silence window, if any.

    Only the latest one is decided: after downtime or overnight, older
    checkpoints are skipped instead of bursting several touches at once.
    """
    stages = stages_for(offer, post_price)
    reached = [name for name, delay in stages if age >= delay]
    return reached[-1] if reached else None


def atendimento_touch_times(state: dict[str, Any], anchor: float, last_lead: float) -> list[float]:
    """The 4 attendant touches in the business's open hours (holidays closed); text inside the window, template after."""
    negocio = (((state.get("lead") or {}).get("origem") or {}).get("negocio") or {})
    window_end = (last_lead or anchor) + ATENDIMENTO_WINDOW_SECONDS
    holidays = set((((state.get("context") or {}).get("ofertas") or {}).get("atendimento") or {}).get("feriados") or [])
    hours = horario.parse_hours(negocio.get("horario_resumo"))
    seed = zlib.crc32(str(state.get("jid") or "").encode()) or None  # spreads the touches that fall at an opening
    times = horario.touch_times(anchor, window_end, hours, BUSINESS_TZ, holidays=holidays, seed=seed)
    # After the 4 touches, one a working day for the next days (always templates: the window is long closed).
    return times + (horario.cadence_times(times[-1], hours, BUSINESS_TZ, holidays, seed=seed) if len(times) == 4 else [])


def official(state: dict[str, Any]) -> bool:
    """Conversations of the official number (Cloud API); the old Evolution ones are legacy and get no touches."""
    return str(state.get("jid") or "").endswith("@cloud")


def atendimento_window_closed(anchor: float, last_lead: float, now: float) -> bool:
    return now >= (last_lead or anchor) + ATENDIMENTO_WINDOW_SECONDS


def atendimento_due_stage(state: dict[str, Any], anchor: float, last_lead: float, now: float,
                          is_decided: Any = lambda stage: False) -> str | None:
    """The first attendant touch already due and not decided yet: the 4 go out in order, never skipping to the last.

    After the 24 h window the touch still happens, as a retomada template (template_touch)."""
    for (name, _), when in zip(ATENDIMENTO_STAGES, atendimento_touch_times(state, anchor, last_lead)):
        if now >= when and not is_decided(name):
            return name
    return None


def sequence(conversation_id: int) -> tuple[float, float | None] | None:
    with closing(connection()) as conn:
        row = conn.execute("SELECT anchor, ended_at FROM sequences WHERE conversation_id=?", (conversation_id,)).fetchone()
    return (float(row[0]), row[1]) if row else None


def start_sequence(conversation_id: int, anchor: float) -> None:
    with closing(connection()) as conn:
        conn.execute("INSERT INTO sequences VALUES (?,?,NULL,NULL) ON CONFLICT(conversation_id) DO UPDATE SET anchor=excluded.anchor, ended_at=NULL, end_reason=NULL", (conversation_id, anchor))
        conn.commit()
    LOGGER.warning("FUP sequence started conversation=%s", conversation_id)


def end_sequence(conversation_id: int, now: float, reason: str) -> None:
    with closing(connection()) as conn:
        conn.execute("UPDATE sequences SET ended_at=?, end_reason=? WHERE conversation_id=? AND ended_at IS NULL", (now, reason, conversation_id))
        conn.commit()
    LOGGER.warning("FUP sequence ended conversation=%s reason=%s", conversation_id, reason)


def decided(conversation_id: int, stage: str, anchor: float) -> bool:
    with closing(connection()) as conn:
        return conn.execute("SELECT 1 FROM decisions WHERE conversation_id=? AND stage=? AND anchor=?", (conversation_id, stage, anchor)).fetchone() is not None


def record_decision(conversation_id: int, stage: str, anchor: float, now: float, disparar: bool, motivo: str) -> None:
    LOGGER.warning("FUP decision conversation=%s stage=%s disparar=%s motivo=%s", conversation_id, stage, disparar, motivo)
    with closing(connection()) as conn:
        conn.execute("INSERT OR REPLACE INTO decisions(conversation_id,stage,anchor,decided,ts,motivo,disparar) VALUES(?,?,?,?,?,?,?)",
                     (conversation_id, stage, anchor, 1, now, motivo[:500], int(disparar)))
        conn.commit()


def last_touch_ts(conversation_id: int) -> float:
    """When the last touch of any stage was decided to go out in this conversation (0 if never)."""
    with closing(connection()) as conn:
        row = conn.execute("SELECT MAX(ts) FROM decisions WHERE conversation_id=? AND disparar=1", (conversation_id,)).fetchone()
    return float(row[0] or 0)


def touch_too_soon(conversation_id: int, now: float) -> bool:
    return now - last_touch_ts(conversation_id) < MIN_TOUCH_GAP_SECONDS


def is_robot(records: dict[str, Any]) -> bool:
    return any(str(records.get(k) or "").strip().lower() == "sim" for k in ("atende_com_ia", "resposta_automatica"))


def outcome_stops_touches(records: dict[str, Any]) -> bool:
    desfecho = str(records.get("desfecho") or "").strip().lower()
    return bool(desfecho) and not (is_robot(records) and desfecho in ROBOT_OUTCOMES)


def previous_touches(conversation_id: int, anchor: float) -> list[dict[str, Any]]:
    with closing(connection()) as conn:
        rows = conn.execute("SELECT stage, disparar, motivo FROM decisions WHERE conversation_id=? AND anchor=? ORDER BY ts", (conversation_id, anchor)).fetchall()
    return [{"estagio": stage, "disparou": bool(fired), "motivo": motivo} for stage, fired, motivo in rows]


# --- next step per lead (lead_steps) ------------------------------------------

def lead_step(conversation_id: int) -> dict[str, Any] | None:
    with closing(connection()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM lead_steps WHERE conversation_id=?", (conversation_id,)).fetchone()
    return dict(row) if row else None


def record_step(conversation_id: int, campo: str, valor: str, ts: float) -> bool:
    """Keep lead_steps in line with the agent's records. True when the next step changed."""
    valor = str(valor or "").strip()
    current = lead_step(conversation_id) or {}
    changes: dict[str, Any] = {}
    if campo in STEP_FIELDS:
        changes[campo] = valor
        if campo in ("proximo_passo", "proximo_passo_em"):
            changes["status"] = "pendente"
    elif campo == "desfecho":
        changes["status"] = "encerrado"
    elif campo in ("tem_vps", "tem_codex") and oferta.fold(valor) in NO and not current.get("proximo_passo_em"):
        # A missing prerequisite is a next step, not an objection: if the agent did
        # not date it, check back the next day.
        tomorrow = (datetime.fromtimestamp(ts, BUSINESS_TZ) + timedelta(days=1)).date().isoformat()
        what = "a VPS" if campo == "tem_vps" else "o Codex (ou levar a Conta do Gemini)"
        changes.update(proximo_passo=current.get("proximo_passo") or f"conferir se já contratou {what}",
                       proximo_passo_em=tomorrow, status="pendente")
    if not changes:
        return False
    row = {"oferta": None, "etapa_spiced": None, "proximo_passo": None, "proximo_passo_em": None, "status": None,
           **{k: v for k, v in current.items() if k != "conversation_id"}, **changes, "atualizado_em": ts}
    with closing(connection()) as conn:
        conn.execute("INSERT INTO lead_steps(conversation_id,oferta,etapa_spiced,proximo_passo,proximo_passo_em,status,atualizado_em) VALUES(?,?,?,?,?,?,?) "
                     "ON CONFLICT(conversation_id) DO UPDATE SET oferta=excluded.oferta, etapa_spiced=excluded.etapa_spiced, proximo_passo=excluded.proximo_passo, "
                     "proximo_passo_em=excluded.proximo_passo_em, status=excluded.status, atualizado_em=excluded.atualizado_em",
                     (conversation_id, row["oferta"], row["etapa_spiced"], row["proximo_passo"], row["proximo_passo_em"], row["status"], row["atualizado_em"]))
        conn.commit()
    return any(current.get(k) != row[k] for k in ("proximo_passo", "proximo_passo_em"))


def step_due_ts(step: dict[str, Any] | None) -> float | None:
    """When the next step is due: the given time, or STEP_DUE_HOUR on a bare date."""
    raw = str((step or {}).get("proximo_passo_em") or "").strip()
    if not raw:
        return None
    try:
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", raw):
            when = datetime.strptime(raw, "%d/%m/%Y")
        else:
            when = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if len(raw) <= 10:
        when = when.replace(hour=STEP_DUE_HOUR, minute=0)
    if when.tzinfo is None:
        when = when.replace(tzinfo=BUSINESS_TZ)
    return when.timestamp()


def step_line(step: dict[str, Any] | None) -> str:
    """The operator's line in Chatwoot: 📌 Próximo passo: … até …"""
    text = str((step or {}).get("proximo_passo") or "").strip()
    due = step_due_ts(step)
    raw = str((step or {}).get("proximo_passo_em") or "").strip()
    if not text and not raw:
        return ""
    when = datetime.fromtimestamp(due, BUSINESS_TZ).strftime("%d/%m/%Y" if len(raw) <= 10 else "%d/%m/%Y %H:%M") if due else (raw or "sem data")
    return f"📌 Próximo passo: {text or '(sem descrição)'} até {when}"


async def announce_step(conversation_id: int, delay: float) -> None:
    try:
        await asyncio.sleep(delay)
        line = step_line(lead_step(conversation_id))
        if line and line != last_step_line.get(conversation_id):
            last_step_line[conversation_id] = line
            await crm.activity(conversation_id, line)
    finally:
        step_announcements.pop(conversation_id, None)


def schedule_step_announcement(conversation_id: int) -> None:
    pending = step_announcements.pop(conversation_id, None)
    if pending:
        pending.cancel()
    step_announcements[conversation_id] = asyncio.create_task(announce_step(conversation_id, STEP_ACTIVITY_DELAY))


def conversation_records(conversation_id: int) -> dict[str, str]:
    """Everything the agent recorded in this conversation, last value wins."""
    with closing(connection()) as conn:
        rows = conn.execute("SELECT payload FROM events WHERE conversation_id=? AND kind='record' ORDER BY id", (conversation_id,)).fetchall()
    records: dict[str, str] = {}
    for (raw,) in rows:
        try:
            item = json.loads(raw)
        except ValueError:
            continue
        if item.get("campo"):
            records[str(item["campo"])] = str(item.get("valor", ""))
    return records


async def track_record(payload: dict[str, Any]) -> None:
    """Records → lead_steps, SPICED attributes on the conversation, next-step line."""
    try:
        cid, campo, valor = int(payload["conversation_id"]), str(payload.get("campo") or ""), str(payload.get("valor") or "")
        changed = record_step(cid, campo, valor, float(payload.get("ts") or time.time()))
        attributes = {crm.SPICED_ATTRIBUTES_BY_FIELD[campo]: valor} if campo in crm.SPICED_ATTRIBUTES_BY_FIELD else {}
        if changed:
            step = lead_step(cid) or {}
            attributes.update(spiced_proximo_passo=step.get("proximo_passo") or "", spiced_proximo_passo_em=step.get("proximo_passo_em") or "")
        if attributes:
            await crm.set_conversation_attributes(cid, attributes)
        if changed:
            schedule_step_announcement(cid)
    except Exception:
        LOGGER.exception("Record tracking failed for %s", payload.get("conversation_id"))


async def deadline_touch(conversation_id: int, state: dict[str, Any], step: dict[str, Any], due: float, now: float, last_lead: float) -> None:
    """The date the lead agreed to has come: one touch about that step."""
    records = state.get("lead", {}).get("registros", {})
    transcript = await chatwoot_messages(conversation_id)
    context = {
        "stage": "prazo", "gatilho": "chegou a data do próximo passo combinado",
        "oferta": oferta.current_offer(state.get("context") or {}) or records.get("oferta") or step.get("oferta"),
        "proximo_passo": {"texto": step.get("proximo_passo"), "ate": step.get("proximo_passo_em")},
        "evento_critico": records.get("evento_critico"),
        "pre_requisitos": {"tem_vps": records.get("tem_vps"), "tem_codex": records.get("tem_codex")},
        "sequencia": {"lead_respondeu_durante": False, "toques_anteriores": previous_touches(conversation_id, due)},
        "transcript": transcript, "lead": state.get("lead", {}), "state": state,
    }
    result = await ask_llm(prompt("fup.md") + "\nCONTEXTO:\n" + json.dumps(context, ensure_ascii=False), timeout=FUP_LLM_TIMEOUT)
    if result is None:
        LOGGER.warning("Deadline touch postponed conversation=%s: LLM unavailable", conversation_id)
        return
    disparar = bool(result.get("disparar") and result.get("texto"))
    motivo, text = str(result.get("motivo", "")), str(result.get("texto") or "")[:500]
    if disparar:
        text, motivo, disparar = await review_touch(conversation_id, text, motivo, state, transcript)
    record_decision(conversation_id, "prazo", due, now, disparar, motivo)
    with closing(connection()) as conn:
        conn.execute("UPDATE lead_steps SET status='cobrado' WHERE conversation_id=?", (conversation_id,))
        conn.commit()
    if disparar:
        await bridge_post("/sdr/followups", {"conversation_id": conversation_id, "send_at": now, "text": text, "motivo": motivo, "after_ts": last_lead, "stage": "prazo"})
        await crm.activity(conversation_id, f"⏱️ Toque do próximo passo agendado: {motivo}")
    else:
        await crm.activity(conversation_id, f"⏱️ Toque do próximo passo não enviado: {motivo}")


async def followup_once(now: float | None = None) -> None:
    """One pass of the follow-up cadence.

    A sequence starts when the lead goes silent after an agent message. If the
    lead replies and the agent answers back, the clock restarts at the agent's
    last message (07/10). A checkpoint is skipped (not postponed) while the
    conversation is going on, and the sequence ends at its last checkpoint,
    on an outcome, or when the conversation is paused.
    """
    current = now or time.time()
    if not in_business_hours(current):
        return
    for conversation_id, local_state in list(tracked.items()):
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{BRIDGE_URL}/sdr/conversations/{conversation_id}", headers={"Authorization": f"Bearer {os.getenv('SDR_BRAIN_TOKEN', '')}"})
                if response.status_code == 404:
                    # The bridge no longer maps this conversation (e.g. an owner
                    # test run ended): stop tracking it instead of polling forever.
                    forget_conversation(conversation_id)
                    continue
                response.raise_for_status()
                state = response.json()
        except Exception as exc:
            LOGGER.warning("Bridge conversation lookup failed: %s", exc)
            continue
        records = state.get("lead", {}).get("registros", {})
        seq = sequence(conversation_id)
        active = seq is not None and seq[1] is None
        if records.get("objecao") and str(records.get("opt_out") or "").strip().lower() != "sim" and not state.get("paused") \
                and not touch_too_soon(conversation_id, current) \
                and official(state) and (oferta.current_offer(state.get("context") or {}) or records.get("oferta")) == "atendimento":
            # "Não faz sentido pra nós" is an objection, not a stop (Talles, 10/10): one touch the next day to
            # find out why, then the sequence is over unless the lead answers.
            await objection_touch(conversation_id, state, records, current, local_state)
            continue
        if state.get("paused") or outcome_stops_touches(records):
            if active:
                end_sequence(conversation_id, current, "pausada" if state.get("paused") else "desfecho")
            continue
        if official(state) and touch_too_soon(conversation_id, current):
            continue  # official number: 2 h at least between any two touches (the Instalador keeps its 5 min cadence)
        last_agent = float(state.get("last_agent_ts") or local_state.get("last_agent_ts") or 0)
        last_lead = float(state.get("last_lead_ts") or 0)
        # Besides silence, the date of the agreed next step triggers a touch
        # (e.g. "contrato a VPS amanhã": the next day, ask if it is done).
        step = lead_step(conversation_id)
        due = step_due_ts(step) if step and step.get("status") == "pendente" else None
        if due is not None and current >= due and not decided(conversation_id, "prazo", due) \
                and current - last_agent >= MIN_SILENCE_SECONDS \
                and not (last_lead >= last_agent and last_lead > float(step.get("atualizado_em") or 0)):
            await deadline_touch(conversation_id, state, step, due, current, last_lead)
            continue
        if not active:
            # A new sequence needs a new silence: the agent spoke last, after
            # whatever ended the previous sequence.
            previous_end = float(seq[1]) if seq else 0.0
            if not last_agent or last_lead >= last_agent or last_agent <= previous_end:
                continue
            start_sequence(conversation_id, last_agent)
            seq = (last_agent, None)
        elif last_lead > seq[0] and last_agent > last_lead:
            # O lead respondeu durante a sequência e o agente respondeu de volta: o relógio recomeça
            # na última mensagem do agente (decisão do Talles, 07/10), para 5min/30min/2h valerem de novo.
            start_sequence(conversation_id, last_agent)
            LOGGER.warning("FUP sequence restarted conversation=%s (lead replied, agent answered)", conversation_id)
            seq = (last_agent, None)
        anchor = seq[0]
        offer_now = oferta.current_offer(state.get("context") or {}) or records.get("oferta")
        stages = stages_for(offer_now, bool(records.get("preco_dado")))
        if offer_now == "atendimento":
            if not official(state):
                end_sequence(conversation_id, current, "legado")
                continue
            stage = atendimento_due_stage(state, anchor, last_lead, current, lambda s: decided(conversation_id, s, anchor))
        else:
            stage = due_stage(current - anchor, bool(records.get("preco_dado")), offer_now)
        if stage is None:
            continue
        if stage in KIWIFY_COVERED_STAGES and str(records.get("checkout_iniciado") or "").strip().lower() == "sim":
            # O recuperador da Kiwify só cobre quem pôs o telefone no checkout (correção do Talles, 09/10):
            # quem só recebeu o link na conversa não está coberto e segue recebendo os toques.
            continue
        final = stage == stages[-1][0]
        if decided(conversation_id, stage, anchor):
            if final:
                end_sequence(conversation_id, current, "completa")
            continue
        if last_lead >= last_agent:
            continue  # the lead spoke last: the agent owes the reply, wait
        replied_during = last_lead > anchor
        quiet = current - max(last_agent, last_lead)
        if replied_during and quiet < QUIET_AFTER_REPLY_SECONDS:
            record_decision(conversation_id, stage, anchor, current, False, "conversa em andamento")
            if final:
                end_sequence(conversation_id, current, "completa")
            continue
        if offer_now == "atendimento" and atendimento_window_closed(anchor, last_lead, current):
            # After the 23 h 30 window the touch goes as a retomada template (Talles 11/10).
            due_at = dict(zip([s for s, _ in ATENDIMENTO_STAGES], atendimento_touch_times(state, anchor, last_lead))).get(stage, current)
            if current - due_at > TEMPLATE_TOUCH_STALE_SECONDS:
                record_decision(conversation_id, stage, anchor, current, False, "venceu sem template aprovado a tempo")
            else:
                outcome = await template_touch(conversation_id, records, stage, last_lead, current)
                if outcome is None:
                    continue  # no approved template yet: the same stage waits for the next pass
                record_decision(conversation_id, stage, anchor, current, outcome == "agendada", f"template ({stage}): {outcome}")
            if final:
                end_sequence(conversation_id, current, "completa")
            continue
        transcript = await chatwoot_messages(conversation_id)
        context = {
            "stage": stage,
            "oferta": oferta.current_offer(state.get("context") or {}) or records.get("oferta"),
            "proximo_passo": {"texto": records.get("proximo_passo"), "ate": records.get("proximo_passo_em")},
            "evento_critico": records.get("evento_critico"),
            "sequencia": {"lead_respondeu_durante": replied_during, "toques_anteriores": previous_touches(conversation_id, anchor)},
            "robo": is_robot(records),
            "transcript": transcript, "lead": state.get("lead", {}), "state": state,
        }
        result = await ask_llm(prompt("fup.md") + "\nCONTEXTO:\n" + json.dumps(context, ensure_ascii=False), timeout=FUP_LLM_TIMEOUT)
        if result is None:
            # 11/10: a timeout used to become "decided, not sent" and the touch was lost; now the stage waits for the next pass.
            LOGGER.warning("FUP decision postponed conversation=%s stage=%s: LLM unavailable", conversation_id, stage)
            continue
        disparar = bool(result.get("disparar") and result.get("texto"))
        motivo = str(result.get("motivo", ""))
        text = str(result.get("texto") or "")[:500]
        if disparar:
            text, motivo, disparar = await review_touch(conversation_id, text, motivo, state, transcript)
        record_decision(conversation_id, stage, anchor, current, disparar, motivo)
        if disparar:
            await bridge_post("/sdr/followups", {"conversation_id": conversation_id, "send_at": current, "text": text, "motivo": motivo, "after_ts": last_lead, "stage": stage})
            await crm.activity(conversation_id, f"⏱️ Toque {stage} agendado: {motivo}")
        else:
            await crm.activity(conversation_id, f"⏱️ Toque {stage} não enviado: {motivo}")
        if final:
            end_sequence(conversation_id, current, "completa")


def objection_touch_time(state: dict[str, Any], last_agent: float, last_lead: float) -> float:
    """The next day, one hour after the business opens, inside the 24 h window and at least 2 h after the agent."""
    negocio = (((state.get("lead") or {}).get("origem") or {}).get("negocio") or {})
    hours = horario.parse_hours(negocio.get("horario_resumo")) or horario.FALLBACK
    window_end = (last_lead or last_agent) + ATENDIMENTO_WINDOW_SECONDS
    earliest = last_agent + MIN_SILENCE_SECONDS
    next_day = datetime.fromtimestamp(last_lead or last_agent, BUSINESS_TZ).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    opens = horario.open_intervals(next_day.timestamp(), window_end, hours, BUSINESS_TZ) or \
        horario.open_intervals(next_day.timestamp(), window_end, horario.FALLBACK, BUSINESS_TZ)
    target = min(opens[0][0] + 3600, opens[0][1]) if opens else window_end - 3600
    return min(max(target, earliest), max(window_end - 600, earliest))


async def objection_touch(conversation_id: int, state: dict[str, Any], records: dict[str, Any], now: float, local_state: dict[str, Any]) -> None:
    last_agent = float(state.get("last_agent_ts") or local_state.get("last_agent_ts") or 0)
    last_lead = float(state.get("last_lead_ts") or 0)
    if not last_agent or last_lead > last_agent:
        return  # the lead wrote after the objection: the conversation goes on, not this touch
    anchor = last_agent
    if decided(conversation_id, "objecao", anchor) or now < objection_touch_time(state, last_agent, last_lead):
        return
    transcript = await chatwoot_messages(conversation_id)
    context = {
        "stage": "objecao", "gatilho": "o lead disse que não faz sentido; descobrir o motivo real",
        "objecao": records.get("objecao"), "oferta": records.get("oferta"),
        "sequencia": {"lead_respondeu_durante": False, "toques_anteriores": previous_touches(conversation_id, anchor)},
        "transcript": transcript, "lead": state.get("lead", {}), "state": state,
    }
    result = await ask_llm(prompt("fup.md") + "\nCONTEXTO:\n" + json.dumps(context, ensure_ascii=False), timeout=FUP_LLM_TIMEOUT)
    if result is None:
        LOGGER.warning("Objection touch postponed conversation=%s: LLM unavailable", conversation_id)
        return
    disparar = bool(result.get("disparar") and result.get("texto"))
    motivo, text = str(result.get("motivo", "")), str(result.get("texto") or "")[:500]
    if disparar:
        text, motivo, disparar = await review_touch(conversation_id, text, motivo, state, transcript)
    record_decision(conversation_id, "objecao", anchor, now, disparar, motivo)
    if disparar:
        await bridge_post("/sdr/followups", {"conversation_id": conversation_id, "send_at": now, "text": text, "motivo": motivo, "after_ts": last_lead, "stage": "objecao"})
        await crm.activity(conversation_id, f"⏱️ Toque de objeção agendado: {motivo}")
    else:
        await crm.activity(conversation_id, f"⏱️ Toque de objeção não enviado: {motivo}")


async def review_touch(conversation_id: int, text: str, motivo: str, state: dict[str, Any], transcript: list[dict[str, Any]]) -> tuple[str, str, bool]:
    """Touches pass the same reviewer as conversation replies."""
    last_lead = next((row["texto"] for row in reversed(transcript) if row.get("autor") == "lead"), "")
    verdict = await run_review({"conversation_id": conversation_id, "tipo": "toque", "lead_message": last_lead,
                                "draft_parts": [text], "directives": [], "context": state.get("context") or {"lead": state.get("lead", {})},
                                "transcript": transcript})
    if verdict["decision"] == "bloquear":
        return text, f"revisor bloqueou: {verdict.get('motivo', '')}", False
    if verdict["decision"] == "reescrever":
        return "\n\n".join(verdict["parts"])[:500], f"{motivo} (revisor reescreveu: {verdict.get('motivo', '')})", True
    return text, motivo, True


# --- retomadas: templates after the 24 h window (Talles, 10/10) ---------------------------------------------------
RETOMADA_PER_PASS = int(os.getenv("SDR_RETOMADA_PER_PASS", "10"))
WEEKDAY_ON = ["na segunda", "na terça", "na quarta", "na quinta", "na sexta", "no sábado", "no domingo"]


def when_label(ts: float, now: float) -> str:
    """'hoje às 19h40', 'ontem às 9h', 'no sábado às 19h40' (local time)."""
    local, today = datetime.fromtimestamp(ts, BUSINESS_TZ), datetime.fromtimestamp(now, BUSINESS_TZ)
    hour = f"{local.hour}h{local.minute:02d}" if local.minute else f"{local.hour}h"
    days = (today.date() - local.date()).days
    day = "hoje" if days == 0 else "ontem" if days == 1 else WEEKDAY_ON[local.weekday()]
    return f"{day} às {hour}"


def fit_case(value: str, template_text: str, slot: int) -> str:
    """Capitalize a value that opens a sentence in the template ('{{2}} mandei…' after a period)."""
    before = template_text.split("{{%d}}" % slot, 1)[0].rstrip()
    return value[:1].upper() + value[1:] if not before or before[-1] in ".!?" else value


def short_name(nome: str) -> str:
    name = re.split(r"\s[-–|]\s|\|", str(nome or ""))[0].strip()
    words = name.split()
    return " ".join(words[:5]) if words else "vocês"


def retomada_window(negocio: dict[str, Any], now: float, holidays: Any = ()) -> tuple[float, float] | None:
    """The next stretch of the business's open hours (9h–20h at most) in the next 3 days: (send_at, send_until)."""
    hours = horario.parse_hours(negocio.get("horario_resumo")) or horario.FALLBACK
    for spans in (horario.open_intervals(now, now + 7 * 86400, horario._clip(hours), BUSINESS_TZ, holidays),
                  horario.open_intervals(now, now + 7 * 86400, horario.FALLBACK, BUSINESS_TZ, holidays)):
        for a, b in spans:
            start = max(a, now) if a <= now else a + 1800  # half an hour after it opens, or right away if open
            if b - start >= 1800:
                return start, b - 900
    return None


def render_retomada(text: str, values: list[str]) -> str:
    for index, value in enumerate(values, start=1):
        text = text.replace("{{%d}}" % index, value)
    return text


STAGE_LAYER = {"2h": "tempo", "d1": "fit", "d3": "dinheiro", "d6": "adiamento",
               # the daily cadence goes to the next layers of the onion: other people, then the honest last call
               "c1": "autoridade", "c2": "fit", "c3": "adiamento"}
# A template touch whose time passed more than this ago (no approved template until then) is dropped, not sent late.
TEMPLATE_TOUCH_STALE_SECONDS = int(os.getenv("SDR_TEMPLATE_TOUCH_STALE_SECONDS", str(24 * 3600)))


async def template_touch(conversation_id: int, records: dict[str, Any], stage: str, last_lead: float, now: float) -> str | None:
    """One of the 4 touches after the window: the retomada template of the conversation's family, filled by the
    layer of the stage. None when no template of that family is approved yet."""
    familia = "robo" if is_robot(records) else "conversa"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{BRIDGE_URL}/sdr/retomada/template", params={"familia": familia},
                                        headers={"Authorization": f"Bearer {os.getenv('SDR_BRAIN_TOKEN', '')}"})
    except Exception as exc:
        LOGGER.warning("Retomada template lookup failed: %s", exc)
        return None
    if response.status_code != 200:
        return None
    async with httpx.AsyncClient(timeout=10) as client:
        lead = (await client.get(f"{BRIDGE_URL}/sdr/conversations/{conversation_id}",
                                 headers={"Authorization": f"Bearer {os.getenv('SDR_BRAIN_TOKEN', '')}"})).json().get("lead") or {}
    candidate = {"conversation_id": conversation_id, "familia": familia, "template": response.json(),
                 "negocio": ((lead.get("origem") or {}).get("negocio") or {}), "teste_enviado_em": last_lead}
    return await plan_retomada(candidate, now, estagio=stage)


async def plan_retomada(candidate: dict[str, Any], now: float, estagio: str | None = None) -> str:
    cid = int(candidate["conversation_id"])
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(f"{BRIDGE_URL}/sdr/conversations/{cid}", headers={"Authorization": f"Bearer {os.getenv('SDR_BRAIN_TOKEN', '')}"})
    if response.status_code != 200:
        return "sem estado"
    state = response.json()
    if state.get("paused"):
        return "pausada"
    negocio = candidate.get("negocio") or {}
    holidays = set((((state.get("context") or {}).get("ofertas") or {}).get("atendimento") or {}).get("feriados") or [])
    window = retomada_window(negocio, now, holidays)
    if not window:
        return "sem horário de funcionamento nos próximos 7 dias"
    template = candidate["template"]
    tested = float(candidate.get("teste_enviado_em") or now)
    records = (state.get("lead") or {}).get("registros") or {}
    context = {
        "familia": candidate["familia"], "template": template, "negocio": negocio,
        "p1_sugerido": f"pessoal da {short_name(negocio.get('nome'))}",
        "p2_sugerido": fit_case(when_label(tested, window[0]), template["text"], 2) if candidate["familia"] != "conversa" else None,
        "registros": records, "transcript": await chatwoot_messages(cid),
        "toques_anteriores": [{"estagio": s, "motivo": m} for s, m in previous_touch_motives(cid)],
        "estagio": estagio, "camada_sugerida": STAGE_LAYER.get(estagio or ""),
        "retomadas_anteriores": candidate.get("retomadas_anteriores") or [],
    }
    result = await ask_llm(prompt("retomada.md") + "\nCONTEXTO:\n" + json.dumps(context, ensure_ascii=False)) or {}
    if not result.get("disparar"):
        return "não disparar: " + str(result.get("motivo") or "sem resposta do modelo")[:200]
    values = [" ".join(str(result.get(k) or "").split()) for k in ("p1", "p2", "p3")]
    if candidate["familia"] != "conversa" and context["p2_sugerido"]:
        values[1] = context["p2_sugerido"]
    values[0] = fit_case(values[0], template["text"], 1)
    text = render_retomada(template["text"], values)
    if not all(values) or "{{" in text:
        return "lacuna vazia"
    verdict = await run_review({"conversation_id": cid, "tipo": "retomada", "lead_message": "", "draft_parts": [text], "directives": [],
                                "context": state.get("context") or {"lead": state.get("lead", {})}, "transcript": context["transcript"]})
    if verdict.get("decision") != "aprovar":
        return f"revisor: {verdict.get('decision')} {verdict.get('motivo', '')}"[:200]
    motivo = f"{result.get('camada', '')}: {result.get('motivo', '')}"[:400]
    await bridge_post("/sdr/retomadas", {"conversation_id": cid, "familia": candidate["familia"], "template": template["name"], "params": values,
                                         "send_at": window[0], "send_until": window[1], "motivo": motivo})
    await crm.activity(cid, f"🔁 Retomada agendada ({candidate['familia']}, camada {result.get('camada', '?')}) para "
                            f"{datetime.fromtimestamp(window[0], BUSINESS_TZ):%d/%m %H:%M}")
    return "agendada"


def previous_touch_motives(conversation_id: int) -> list[tuple[str, str]]:
    with closing(connection()) as conn:
        return [(r[0], r[1]) for r in conn.execute("SELECT stage, motivo FROM decisions WHERE conversation_id=? AND disparar=1 ORDER BY ts", (conversation_id,))]


async def retomada_once(now: float | None = None) -> None:
    current = now or time.time()
    if not in_business_hours(current):
        return
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{BRIDGE_URL}/sdr/retomada/candidatos", headers={"Authorization": f"Bearer {os.getenv('SDR_BRAIN_TOKEN', '')}"})
            response.raise_for_status()
            candidates = response.json().get("candidatos") or []
    except Exception as exc:
        LOGGER.warning("Retomada candidates failed: %s", exc)
        return
    for candidate in candidates[:RETOMADA_PER_PASS]:
        try:
            outcome = await plan_retomada(candidate, current)
        except Exception:
            LOGGER.exception("Retomada planning failed conversation=%s", candidate.get("conversation_id"))
            continue
        LOGGER.warning("Retomada conversation=%s familia=%s -> %s", candidate.get("conversation_id"), candidate.get("familia"), outcome)
        save_event({"conversation_id": candidate.get("conversation_id"), "familia": candidate.get("familia"), "resultado": outcome}, "retomada")


async def retomada_loop() -> None:
    while True:
        try:
            await retomada_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Retomada iteration failed")
        await asyncio.sleep(600)


async def followup_loop() -> None:
    while True:
        try:
            await followup_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Follow-up iteration failed")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global cron_task
    load_tracked()
    cron_task = asyncio.create_task(followup_loop())
    retomada_task = asyncio.create_task(retomada_loop())
    try:
        yield
    finally:
        for task in (cron_task, retomada_task):
            if task:
                task.cancel()
        await asyncio.gather(*(t for t in (cron_task, retomada_task) if t), return_exceptions=True)


app = FastAPI(title="sdr-brain", lifespan=lifespan)


async def plan_snapshot(now: float | None = None) -> dict[str, Any]:
    """The expected follow-up plan of every official conversation the brain tracks (read only), for the bridge's
    vigia (Talles 11/10: "não me faça passar vergonha"): the 4 touch times with their channel (text inside the
    23 h 30 window, template after), what was decided for each stage, and whether touches may go at all."""
    current = now or time.time()
    out: dict[str, Any] = {}
    with closing(connection()) as conn:
        tracked_ids = [r[0] for r in conn.execute("SELECT conversation_id FROM tracked")]
        ended = {r[0]: r[1] for r in conn.execute("SELECT conversation_id, end_reason FROM sequences WHERE ended_at IS NOT NULL")}
        decisions: dict[int, list[dict[str, Any]]] = {}
        for cid, stage, anchor, ts, motivo, fired in conn.execute("SELECT conversation_id, stage, anchor, ts, motivo, disparar FROM decisions ORDER BY ts"):
            decisions.setdefault(cid, []).append({"estagio": stage, "anchor": anchor, "quando": ts, "disparou": bool(fired), "motivo": (motivo or "")[:200]})
    async with httpx.AsyncClient(timeout=10) as client:
        for cid in tracked_ids:
            try:
                r = await client.get(f"{BRIDGE_URL}/sdr/conversations/{cid}", headers={"Authorization": f"Bearer {os.getenv('SDR_BRAIN_TOKEN', '')}"})
                if r.status_code != 200:
                    continue
                st = r.json()
            except Exception:
                continue
            if not official(st):
                continue
            rec = (st.get("lead") or {}).get("registros") or {}
            last_lead, last_agent = float(st.get("last_lead_ts") or 0), float(st.get("last_agent_ts") or 0)
            seq = sequence(cid)
            anchor = seq[0] if seq and seq[1] is None else last_agent
            window_end = (last_lead or anchor) + ATENDIMENTO_WINDOW_SECONDS + horario.END_MARGIN
            plan = []
            if last_lead and last_agent:
                for (stage, _), when in zip(ATENDIMENTO_STAGES, atendimento_touch_times(st, anchor, last_lead)):
                    plan.append({"estagio": stage, "quando": when, "canal": horario.touch_channel(when, window_end),
                                 "decidido": decided(cid, stage, anchor)})
            out[str(cid)] = {"plano": plan, "decisoes": decisions.get(cid, []), "anchor": anchor, "encerrada": ended.get(cid),
                             "pausada": bool(st.get("paused")), "para_toques": outcome_stops_touches(rec),
                             "objecao": bool(rec.get("objecao")), "robo": is_robot(rec), "lead_falou_por_ultimo": last_lead > last_agent,
                             "limite_toque": (last_lead + ATENDIMENTO_WINDOW_SECONDS) if last_lead else None,
                             "horario_resumo": (((st.get("lead") or {}).get("origem") or {}).get("negocio") or {}).get("horario_resumo")}
    return {"gerado_em": current, "conversas": out}


@app.get("/plano")
async def plano(request: Request) -> dict[str, Any]:
    auth(request)
    return await plan_snapshot()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/review")
async def review(request: Request) -> dict[str, Any]:
    auth(request)
    try:
        payload = await request.json()
    except Exception:
        return {"decision": "aprovar", "motivo": "review_unavailable"}
    # A caller may send the transcript (simulations); otherwise read Chatwoot.
    simulated = isinstance(payload.get("transcript"), list)
    decision = await run_review(payload)
    conversation_id = payload.get("conversation_id")
    if not simulated and isinstance(conversation_id, int) and decision["decision"] != "aprovar" and decision.get("motivo") != "review_unavailable":
        label = "✏️ Resposta reescrita pelo revisor" if decision["decision"] == "reescrever" else "⛔ Resposta bloqueada pelo revisor"
        await crm.activity(conversation_id, f"{label}: {decision.get('motivo', '')}")
    return decision


async def run_review(payload: dict[str, Any]) -> dict[str, Any]:
    draft = payload.get("draft_parts", [])
    conversation_id = payload.get("conversation_id")
    transcript = payload.pop("transcript", None)
    if not isinstance(transcript, list):
        transcript = await chatwoot_messages(int(conversation_id)) if isinstance(conversation_id, int) else []
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    recorded = next((str(d.get("valor", "")).strip().lower() for d in payload.get("directives") or []
                     if isinstance(d, dict) and d.get("type") == "registro" and d.get("campo") == "oferta"), None)
    if not oferta.current_offer(context) and recorded in oferta.OFFERS:
        context = {**context, "oferta": recorded}  # the draft itself discovered the offer
    draft_parts = [str(part) for part in draft] if isinstance(draft, list) else []
    lead_texts = [str(payload.get("lead_message") or "")] + [str(row.get("texto", "")) for row in transcript if isinstance(row, dict) and row.get("autor") == "lead"]
    sent_texts = [str(row.get("texto", "")) for row in transcript if isinstance(row, dict) and row.get("autor") == "agente"]
    issues = oferta.check(draft_parts, context, lead_texts, sent_texts)
    cta = [PRICE_WITHOUT_LINK] if oferta.price_without_link(draft_parts, context) else []
    dados = {**payload, "transcript": transcript, "oferta": oferta.current_offer(context) or "desconhecida",
             "fatos_oferta": oferta.facts(context), "verificacao_automatica": issues + cta}
    # One slower attempt fits the bridge's wait; a retry would land after it gave up.
    result = await ask_llm(prompt("revisor.md") + "\nDADOS:\n" + json.dumps(dados, ensure_ascii=False),
                           attempts=1, timeout=float(os.getenv("SDR_REVIEW_LLM_TIMEOUT", "18")))
    decision = judged_review(result, draft)
    decision = enforce_offer_rules(decision, issues, context, lead_texts, sent_texts)
    decision = enforce_price_cta(decision, draft_parts, context, toque=payload.get("tipo") == "toque")
    return reconcile_link_record(decision, payload.get("directives"))


DIRECTIVE_RE = re.compile(r"\[\[\s*([A-Za-zÇÃÕÁÉÍÓÚçãõáéíóú_]+)\s*(?::\s*(.*?))?\s*\]\]", re.S)


def _parse_directives(text: str) -> list[dict[str, Any]]:
    """The bridge's directive format (bridge-src/sdr.py parse_reply), for the ones a rewrite carries."""
    found = []
    for name, arg in DIRECTIVE_RE.findall(text or ""):
        name, arg = name.upper(), (arg or "").strip()
        if name == "REGISTRO" and "=" in arg:
            campo, _, valor = arg.partition("=")
            found.append({"type": "registro", "campo": campo.strip().lower(), "valor": valor.strip()})
        elif name == "ESCALAR":
            motivo, _, frase = arg.partition("|")
            found.append({"type": "escalar", "motivo": motivo.strip(), "frase": frase.strip()})
        elif name == "FOTO" and arg:
            found.append({"type": "foto", "nome": arg})
    return found


def _render_directive(d: dict[str, Any]) -> str:
    if d.get("type") == "registro":
        return f"[[REGISTRO: {d.get('campo')} = {d.get('valor')}]]"
    if d.get("type") == "escalar":
        return f"[[ESCALAR: {d.get('motivo', '')} | {d.get('frase', '')}]]"
    if d.get("type") == "foto":
        return f"[[FOTO: {d.get('nome')}]]"
    return ""


def reconcile_link_record(decision: dict[str, Any], directives: Any) -> dict[str, Any]:
    """link_enviado follows what the lead really receives.

    The bridge keeps the draft's directives when a rewrite carries none, so a
    rewrite that drops the link would still record link_enviado = sim (and the
    link the code adds would not be recorded). When that happens, the corrected
    set of directives goes in the last part, which the bridge then uses.
    """
    if decision.get("decision") != "reescrever" or not decision.get("parts"):
        return decision
    parts = [str(p) for p in decision["parts"]]
    carried = [d for p in parts for d in _parse_directives(p)]
    base = carried or [d for d in (directives or []) if isinstance(d, dict)]
    text = oferta.fold(" ".join(re.sub(r"\[\[.*?\]\]", "", p, flags=re.S) for p in parts))
    has_link = "instalador.talles.dev/antes" in text
    is_link = lambda d: d.get("type") == "registro" and d.get("campo") == "link_enviado"
    is_price = lambda d: d.get("type") == "registro" and d.get("campo") == "preco_dado"
    fixed = list(base)
    if has_link and not any(is_link(d) for d in base):
        fixed.append({"type": "registro", "campo": "link_enviado", "valor": "sim"})
    if not has_link and any(is_link(d) for d in base):
        fixed = [d for d in fixed if not is_link(d) and not (is_price(d) and "r$" not in text)]
    if fixed == base:
        return decision
    clean = [re.sub(r"\s*\[\[.*?\]\]", "", p, flags=re.S).strip() for p in parts]
    clean[-1] = (clean[-1] + " " + " ".join(filter(None, map(_render_directive, fixed)))).strip()
    return {**decision, "parts": clean}


PRICE_WITHOUT_LINK = "preço da instalação sem o link https://instalador.talles.dev/antes e a pergunta do próximo passo (C8)"


def enforce_price_cta(decision: dict[str, Any], draft_parts: list[str], context: dict[str, Any], toque: bool = False) -> dict[str, Any]:
    """TSX-78: the installation price never goes out without the /antes link and a next step.

    Whatever the reviewer decided (or if it was down), a price turn without the
    link gets the link and "Consegue fazer hoje?" added deterministically.
    """
    if decision["decision"] == "bloquear":
        return decision
    parts = decision["parts"] if decision["decision"] == "reescrever" else draft_parts
    if not oferta.price_without_link(parts, context):
        return decision
    motivo = "; ".join(m for m in (decision.get("motivo") if decision["decision"] == "reescrever" else "", "C8: preço sai com o link e o próximo passo") if m)
    return {"decision": "reescrever", "parts": oferta.with_price_cta(parts, toque=toque), "motivo": motivo}


def judged_review(result: Any, draft: Any) -> dict[str, Any]:
    if not isinstance(result, dict) or result.get("decision") not in {"aprovar", "reescrever", "bloquear"}:
        return {"decision": "aprovar", "motivo": "review_unavailable"}
    if result["decision"] == "reescrever":
        parts = result.get("parts")
        if not isinstance(parts, list) or len(parts) > 3 or not all(isinstance(part, str) for part in parts):
            return {"decision": "aprovar", "motivo": "review_unavailable"}
        original = "\n".join(draft) if isinstance(draft, list) else ""
        return {"decision": "reescrever", "parts": [preserve_directives(original, part) for part in parts], "motivo": str(result.get("motivo", ""))}
    return {"decision": result["decision"], **({"motivo": str(result.get("motivo", ""))} if result["decision"] == "bloquear" else {})}


def enforce_offer_rules(decision: dict[str, Any], issues: list[str], context: dict[str, Any], lead_texts: list[str],
                        sent_texts: list[str] | tuple = ()) -> dict[str, Any]:
    """Hard offer violations never go out, whatever the model decided or if it was down."""
    if decision["decision"] == "bloquear" or not issues:
        return decision
    if decision["decision"] == "reescrever":
        issues = oferta.check([re.sub(r"\[\[.*?\]\]", "", part) for part in decision["parts"]], context, lead_texts, sent_texts)
        if not issues:
            return decision
    return {"decision": "bloquear", "motivo": "verificação automática: " + "; ".join(issues)}


@app.post("/events/exchange", status_code=202)
async def exchange(request: Request, background_tasks: BackgroundTasks) -> dict[str, bool]:
    auth(request)
    payload = await request.json()
    save_event(payload, "exchange"); remember_exchange(payload); background_tasks.add_task(supervisor, payload)
    return {"accepted": True}


@app.post("/events/lead", status_code=202)
async def lead(request: Request, background_tasks: BackgroundTasks) -> dict[str, bool]:
    auth(request); payload = await request.json(); save_event(payload, "lead"); background_tasks.add_task(enrich, payload); return {"accepted": True}


@app.post("/events/record", status_code=202)
async def record(request: Request, background_tasks: BackgroundTasks) -> dict[str, bool]:
    auth(request)
    payload = await request.json()
    save_event(payload, "record")
    campo, valor, cid = payload.get("campo"), payload.get("valor", ""), payload["conversation_id"]
    background_tasks.add_task(track_record, payload)
    if campo == "instagram":  # the lead's own @, typed when the agent asked
        background_tasks.add_task(enrich, {"conversation_id": cid, "typed_instagram": valor, "ts": payload.get("ts")})
    elif campo == "arroba":  # the company @, used for the company profile
        background_tasks.add_task(enrich, {"conversation_id": cid, "company_instagram": valor, "ts": payload.get("ts")})
    return {"accepted": True}
