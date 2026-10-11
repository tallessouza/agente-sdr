"""Durable turn queue (Talles, 10/10/2026: "quando tiver deploy a gente não pode perder").

Until 10/10 the lead's messages waited for the agent only in memory, so a bridge restart dropped them (#74 got no
answer) and cut replies in the middle (#77). Now, in the bridge's SQLite:
  * turnos: every lead message (media saved under /data/turnos) until its turn is done;
  * turnos_lote: each batch being answered, with the final parts (after review and guards) and how many went out,
    so a restart resends only the missing parts instead of asking the agent again;
  * brain_eventos: the notices to the brain, retried until they get through (follow-ups depend on them).
"""
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

DB_PATH = Path(os.getenv("BRIDGE_DB", "/data/bridge.db"))
MEDIA_DIR = Path(os.getenv("BRIDGE_TURN_MEDIA_DIR", str(DB_PATH.parent / "turnos")))


def connect() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS turnos (id INTEGER PRIMARY KEY, external_id TEXT UNIQUE NOT NULL, jid TEXT NOT NULL, "
              "conversation INTEGER NOT NULL, source_id TEXT, content TEXT, media TEXT, evento TEXT, status TEXT NOT NULL DEFAULT 'pendente', "
              "lote TEXT, criado REAL NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS turnos_lote (lote TEXT PRIMARY KEY, jid TEXT NOT NULL, conversation INTEGER NOT NULL, source_id TEXT, "
              "last_message TEXT, reply_to TEXT, partes TEXT, diretivas TEXT, enviados INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, criado REAL NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS brain_eventos (id INTEGER PRIMARY KEY, path TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pendente', "
              "tentativas INTEGER NOT NULL DEFAULT 0, proxima REAL NOT NULL, criado REAL NOT NULL)")
    c.commit()
    return c


def save_turn(jid: str, conversation: int, source_id: str, content: str, media: list[tuple[bytes, str, str]] | None,
              external_id: str, evento: dict[str, Any] | None) -> bool:
    """Persist one lead message; False when it is already stored (a redelivery)."""
    stored = []
    key = hashlib.sha1(external_id.encode()).hexdigest()[:16]
    for index, (payload, mimetype, filename) in enumerate(media or []):
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        path = MEDIA_DIR / f"{key}-{index}-{Path(filename).name}"
        path.write_bytes(payload)
        stored.append({"path": str(path), "mimetype": mimetype, "filename": filename})
    with connect() as c:
        return bool(c.execute("INSERT OR IGNORE INTO turnos(external_id,jid,conversation,source_id,content,media,evento,criado) VALUES (?,?,?,?,?,?,?,?)",
                              (external_id, jid, conversation, source_id, content, json.dumps(stored), json.dumps(evento) if evento else None,
                               time.time())).rowcount)


def load_media(raw: str | None) -> list[tuple[bytes, str, str]]:
    out = []
    for item in json.loads(raw or "[]"):
        try:
            out.append((Path(item["path"]).read_bytes(), item["mimetype"], item["filename"]))
        except OSError:
            continue
    return out


def start_batch(lote: str, external_ids: list[str], jid: str, conversation: int, source_id: str, last_message: str, reply_to: str | None) -> None:
    with connect() as c:
        c.execute(f"UPDATE turnos SET status='processando', lote=? WHERE external_id IN ({','.join('?' * len(external_ids))})", (lote, *external_ids))
        c.execute("INSERT OR IGNORE INTO turnos_lote(lote,jid,conversation,source_id,last_message,reply_to,status,criado) VALUES (?,?,?,?,?,?,?,?)",
                  (lote, jid, conversation, source_id, last_message, reply_to, "aguardando", time.time()))


def finish(external_ids: list[str], lote: str | None = None, status: str = "feito") -> None:
    if not external_ids and not lote:
        return
    with connect() as c:
        if external_ids:
            c.execute(f"UPDATE turnos SET status=? WHERE external_id IN ({','.join('?' * len(external_ids))})", (status, *external_ids))
        if lote:
            c.execute("UPDATE turnos_lote SET status=? WHERE lote=?", (status, lote))


def requeue(external_ids: list[str], lote: str | None = None) -> None:
    """The lead wrote again before the answer went out: the messages wait for the next, combined turn."""
    with connect() as c:
        if external_ids:
            c.execute(f"UPDATE turnos SET status='pendente', lote=NULL WHERE external_id IN ({','.join('?' * len(external_ids))})", external_ids)
        if lote:
            c.execute("DELETE FROM turnos_lote WHERE lote=? AND enviados=0", (lote,))


def final_parts(lote: str) -> tuple[list[str], list[dict[str, Any]], int] | None:
    with connect() as c:
        row = c.execute("SELECT partes, diretivas, enviados FROM turnos_lote WHERE lote=?", (lote,)).fetchone()
    if not row or row[0] is None:
        return None
    return json.loads(row[0]), json.loads(row[1] or "[]"), int(row[2])


def save_final(lote: str, parts: list[str], directives: list[dict[str, Any]]) -> None:
    with connect() as c:
        c.execute("UPDATE turnos_lote SET partes=?, diretivas=?, status='enviando' WHERE lote=? AND partes IS NULL",
                  (json.dumps(parts, ensure_ascii=False), json.dumps(directives, ensure_ascii=False), lote))


def mark_sent(lote: str, count: int) -> None:
    with connect() as c:
        c.execute("UPDATE turnos_lote SET enviados=MAX(enviados, ?) WHERE lote=?", (count, lote))


def unfinished() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(batches with decided parts still to send, lead messages whose turn never got an answer), oldest first."""
    with connect() as c:
        c.row_factory = sqlite3.Row
        batches = [dict(r) for r in c.execute("SELECT * FROM turnos_lote WHERE status='enviando' AND partes IS NOT NULL ORDER BY criado")]
        lotes = {b["lote"] for b in batches}
        turns = [dict(r) for r in c.execute("SELECT * FROM turnos WHERE status IN ('pendente','processando') ORDER BY criado") if r["lote"] not in lotes]
    return batches, turns


def batch_external_ids(lote: str) -> list[str]:
    with connect() as c:
        return [r[0] for r in c.execute("SELECT external_id FROM turnos WHERE lote=?", (lote,))]


def queue_event(path: str, payload: dict[str, Any]) -> int:
    with connect() as c:
        return int(c.execute("INSERT INTO brain_eventos(path,payload,proxima,criado) VALUES (?,?,?,?)",
                             (path, json.dumps(payload, ensure_ascii=False), time.time(), time.time())).lastrowid)


def due_events(limit: int = 20) -> list[tuple[int, str, dict[str, Any], int]]:
    with connect() as c:
        rows = c.execute("SELECT id, path, payload, tentativas FROM brain_eventos WHERE status='pendente' AND proxima<=? ORDER BY id LIMIT ?",
                         (time.time(), limit)).fetchall()
    return [(int(r[0]), r[1], json.loads(r[2]), int(r[3])) for r in rows]


def event_done(event_id: int) -> None:
    with connect() as c:
        c.execute("UPDATE brain_eventos SET status='feito' WHERE id=?", (event_id,))


def event_failed(event_id: int, attempts: int) -> None:
    """Exponential retry; after a day it gives up (the follow-up of a day-old exchange no longer matters)."""
    with connect() as c:
        c.execute("UPDATE brain_eventos SET tentativas=?, proxima=?, status=CASE WHEN ?-criado > 86400 THEN 'desistiu' ELSE 'pendente' END WHERE id=?",
                  (attempts + 1, time.time() + min(900, 2 ** min(attempts + 3, 10)), time.time(), event_id))
