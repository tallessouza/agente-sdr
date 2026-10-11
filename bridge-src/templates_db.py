"""Template state in the central database (Talles, 11/10/2026: "nada dependa de JSON").

Until 11/10 the template farm kept its state in /data/templates-meta.json, templates-pool.json and
templates-retomada.json. Now everything lives in the bridge's SQLite:
  * tpl_templates: one row per template we track (opening or retomada), what we submitted and what Meta says now;
  * tpl_saude: every change of status, category or quality Meta reports (the health history);
  * tpl_placar, tpl_usados, tpl_submetidos: the generator's learning, the texts already used, submissions per day;
  * tpl_envios, tpl_envio_conversa: sends and failures per template and day, and which template opened each
    conversation (replies per template come from sdr_prospects).
The first connection imports the old JSON files once (nothing reads them afterwards).
"""
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import sdr

OLD_META = Path(os.getenv("CLOUD_TEMPLATES_META_FILE", "/data/templates-meta.json"))
OLD_POOL = Path(os.getenv("CLOUD_TEMPLATES_FILE", "/data/templates-pool.json"))
OLD_RETOMADA = Path(os.getenv("CLOUD_RETOMADA_TEMPLATES_FILE", "/data/templates-retomada.json"))
INFO_FIELDS = ("tipo", "familia", "scheme", "estado", "alvo", "contado", "contado_editado", "submetido", "criado", "editado_em")


def connect() -> sqlite3.Connection:
    c = sdr.connect()
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS tpl_templates (name TEXT PRIMARY KEY, tipo TEXT NOT NULL DEFAULT 'abertura', familia TEXT, "
              "scheme TEXT, params TEXT, estado TEXT, alvo TEXT, contado TEXT, contado_editado TEXT, submetido REAL, criado REAL, "
              "editado_em REAL, meta_id TEXT, language TEXT, texto TEXT, categoria TEXT, status TEXT, saude TEXT, motivo TEXT, "
              "no_pool INTEGER NOT NULL DEFAULT 0, atualizado REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS tpl_placar (scheme TEXT PRIMARY KEY, enviados INTEGER NOT NULL DEFAULT 0, utility INTEGER NOT NULL DEFAULT 0, "
              "marketing INTEGER NOT NULL DEFAULT 0, recusado INTEGER NOT NULL DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS tpl_usados (texto TEXT PRIMARY KEY)")
    c.execute("CREATE TABLE IF NOT EXISTS tpl_submetidos (dia TEXT NOT NULL, tipo TEXT NOT NULL, quantidade INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (dia, tipo))")
    c.execute("CREATE TABLE IF NOT EXISTS tpl_saude (id INTEGER PRIMARY KEY, ts REAL NOT NULL, name TEXT NOT NULL, tipo TEXT, categoria TEXT, "
              "status TEXT, saude TEXT, motivo TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS tpl_envios (name TEXT NOT NULL, dia TEXT NOT NULL, enviados INTEGER NOT NULL DEFAULT 0, "
              "falhas INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (name, dia))")
    c.execute("CREATE TABLE IF NOT EXISTS tpl_envio_conversa (conversation INTEGER NOT NULL, name TEXT NOT NULL, ts REAL NOT NULL, "
              "PRIMARY KEY (conversation, name, ts))")
    c.commit()
    return c


def _migrate_once(c: sqlite3.Connection) -> None:
    """The old JSON state, imported the first time the tables are empty."""
    if c.execute("SELECT 1 FROM tpl_templates LIMIT 1").fetchone() or not OLD_META.exists():
        return
    try:
        meta = json.loads(OLD_META.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    write_meta(meta, c)
    for path, tipo in ((OLD_POOL, "abertura"), (OLD_RETOMADA, "retomada")):
        try:
            pool = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        except (OSError, json.JSONDecodeError):
            pool = []
        for t in pool:
            c.execute("INSERT INTO tpl_templates(name,tipo,familia,params,texto,categoria,language,saude,status,no_pool,atualizado) "
                      "VALUES (?,?,?,?,?,?,?,?,'APPROVED',1,?) ON CONFLICT(name) DO UPDATE SET texto=excluded.texto, categoria=excluded.categoria, "
                      "language=excluded.language, saude=excluded.saude, status='APPROVED', no_pool=1, tipo=excluded.tipo, "
                      "familia=COALESCE(tpl_templates.familia, excluded.familia), params=COALESCE(tpl_templates.params, excluded.params)",
                      (t["name"], tipo, t.get("familia"), ",".join(t.get("params") or []) or None, t.get("text"), t.get("category"),
                       t.get("language", "pt_BR"), t.get("saude"), time.time()))
    c.commit()


def ready() -> sqlite3.Connection:
    c = connect()
    _migrate_once(c)
    return c


def read_meta() -> dict[str, Any]:
    """The generator's state in the shape template_health always used."""
    with ready() as c:
        templates = {}
        for r in c.execute("SELECT * FROM tpl_templates WHERE scheme IS NOT NULL OR tipo='retomada'"):
            info = {k: r[k] for k in INFO_FIELDS if r[k] is not None}
            info["params"] = r["params"].split(",") if r["params"] else []
            templates[r["name"]] = info
        placar = {r["scheme"]: {k: r[k] for k in ("enviados", "utility", "marketing", "recusado") if r[k]} for r in c.execute("SELECT * FROM tpl_placar")}
        usados = [r["texto"] for r in c.execute("SELECT texto FROM tpl_usados")]
        submetidos = {r["dia"]: r["quantidade"] for r in c.execute("SELECT dia, quantidade FROM tpl_submetidos WHERE tipo='abertura'")}
        submetidos_retomada = {r["dia"]: r["quantidade"] for r in c.execute("SELECT dia, quantidade FROM tpl_submetidos WHERE tipo='retomada'")}
    return {"templates": templates, "placar": placar, "usados": usados, "submetidos": submetidos, "submetidos_retomada": submetidos_retomada}


def write_meta(meta: dict[str, Any], c: sqlite3.Connection | None = None) -> None:
    own = c is None
    c = c or connect()
    try:
        for name, info in (meta.get("templates") or {}).items():
            values = {k: info.get(k) for k in INFO_FIELDS}
            values["tipo"] = values["tipo"] or ("retomada" if name.startswith("retomada_") else "abertura")
            params = ",".join(info.get("params") or []) or None
            c.execute(f"INSERT INTO tpl_templates(name,params,{','.join(INFO_FIELDS)},atualizado) VALUES (?,?,{','.join('?' * len(INFO_FIELDS))},?) "
                      f"ON CONFLICT(name) DO UPDATE SET params=excluded.params, {', '.join(f'{k}=excluded.{k}' for k in INFO_FIELDS)}, atualizado=excluded.atualizado",
                      (name, params, *values.values(), time.time()))
        for scheme, p in (meta.get("placar") or {}).items():
            c.execute("INSERT INTO tpl_placar(scheme,enviados,utility,marketing,recusado) VALUES (?,?,?,?,?) ON CONFLICT(scheme) DO UPDATE SET "
                      "enviados=excluded.enviados, utility=excluded.utility, marketing=excluded.marketing, recusado=excluded.recusado",
                      (scheme, p.get("enviados", 0), p.get("utility", 0), p.get("marketing", 0), p.get("recusado", 0)))
        c.executemany("INSERT OR IGNORE INTO tpl_usados(texto) VALUES (?)", [(t,) for t in meta.get("usados") or [] if t])
        for key, tipo in (("submetidos", "abertura"), ("submetidos_retomada", "retomada")):
            for dia, n in (meta.get(key) or {}).items():
                c.execute("INSERT INTO tpl_submetidos(dia,tipo,quantidade) VALUES (?,?,?) ON CONFLICT(dia,tipo) DO UPDATE SET quantidade=excluded.quantidade",
                          (dia, tipo, n))
        c.commit()
    finally:
        if own:
            c.close()


def sync_from_meta(templates: list[dict[str, Any]], tipo_of: Any, health_of: Any, body_of: Any, now: float | None = None) -> list[dict[str, Any]]:
    """Store what Meta says about every template we track; record each change of status, category or quality."""
    now = time.time() if now is None else now
    changes = []
    with ready() as c:
        known = {r["name"]: r for r in c.execute("SELECT name, status, categoria, saude, tipo FROM tpl_templates")}
        for t in templates:
            name = t.get("name", "")
            tipo = tipo_of(name)
            if not tipo:
                continue
            state = (t.get("status"), t.get("category"), health_of(t), t.get("rejected_reason") or None)
            before = known.get(name)
            if not before or (before["status"], before["categoria"], before["saude"]) != state[:3]:
                c.execute("INSERT INTO tpl_saude(ts,name,tipo,categoria,status,saude,motivo) VALUES (?,?,?,?,?,?,?)",
                          (now, name, tipo, state[1], state[0], state[2], state[3]))
                changes.append({"name": name, "antes": dict(before) if before else None, "agora": {"status": state[0], "categoria": state[1], "saude": state[2]}})
            c.execute("INSERT INTO tpl_templates(name,tipo,meta_id,language,texto,categoria,status,saude,motivo,atualizado) VALUES (?,?,?,?,?,?,?,?,?,?) "
                      "ON CONFLICT(name) DO UPDATE SET meta_id=excluded.meta_id, language=excluded.language, texto=excluded.texto, "
                      "categoria=excluded.categoria, status=excluded.status, saude=excluded.saude, motivo=excluded.motivo, atualizado=excluded.atualizado",
                      (name, (before["tipo"] if before else tipo), str(t.get("id") or ""), t.get("language", "pt_BR"), body_of(t), state[1], state[0], state[2],
                       state[3], now))
        # Gone from Meta (deleted): out of every pool.
        present = {t.get("name") for t in templates}
        for name in known:
            if name not in present:
                c.execute("UPDATE tpl_templates SET no_pool=0, status='APAGADO', atualizado=? WHERE name=? AND status IS NOT 'APAGADO'", (now, name))
        c.commit()
    return changes


def set_pool(tipo: str, names: list[str]) -> None:
    with ready() as c:
        c.execute("UPDATE tpl_templates SET no_pool=0 WHERE tipo=?", (tipo,))
        c.executemany("UPDATE tpl_templates SET no_pool=1 WHERE name=?", [(n,) for n in names])
        c.commit()


def pool(tipo: str) -> list[dict[str, Any]]:
    """Templates usable now: approved by Meta and healthy (see template_health.build_pool and ensure_retomadas)."""
    try:
        with ready() as c:
            rows = c.execute("SELECT * FROM tpl_templates WHERE tipo=? AND no_pool=1 ORDER BY name", (tipo,)).fetchall()
    except sqlite3.Error:
        return []
    return [{"name": r["name"], "language": r["language"] or "pt_BR", "category": r["categoria"], "text": r["texto"],
             "params": r["params"].split(",") if r["params"] else [], "familia": r["familia"], "saude": r["saude"] or "UNKNOWN"} for r in rows]


def record_send(name: str, conversation: int | None, day: str, now: float | None = None) -> None:
    with connect() as c:
        c.execute("INSERT INTO tpl_envios(name,dia,enviados) VALUES (?,?,1) ON CONFLICT(name,dia) DO UPDATE SET enviados=enviados+1", (name, day))
        if conversation:
            c.execute("INSERT OR IGNORE INTO tpl_envio_conversa(conversation,name,ts) VALUES (?,?,?)", (conversation, name, time.time() if now is None else now))


def record_failure(name: str, day: str) -> None:
    with connect() as c:
        c.execute("INSERT INTO tpl_envios(name,dia,falhas) VALUES (?,?,1) ON CONFLICT(name,dia) DO UPDATE SET falhas=falhas+1", (name, day))


def health_report() -> list[dict[str, Any]]:
    """Every tracked template that Meta still has: its state, sends, failures and replies (person or robot)."""
    with ready() as c:
        rows = [dict(r) for r in c.execute("SELECT name, tipo, familia, scheme, categoria, status, saude, motivo, no_pool, texto FROM tpl_templates "
                                           "WHERE status IS NOT NULL AND status != 'APAGADO' ORDER BY tipo, name")]
        sends = {r["name"]: (r["e"], r["f"]) for r in c.execute("SELECT name, SUM(enviados) e, SUM(falhas) f FROM tpl_envios GROUP BY name")}
        has_prospects = c.execute("SELECT 1 FROM sqlite_master WHERE name='sdr_prospects'").fetchone()
        replies = {}
        if has_prospects:
            for r in c.execute("SELECT e.name, COUNT(p.respondeu_em) resp, SUM(p.status='automatica') robo FROM tpl_envio_conversa e "
                               "LEFT JOIN sdr_prospects p ON p.conversation=e.conversation AND p.respondeu_em >= e.ts - 5 GROUP BY e.name"):
                replies[r["name"]] = (r["resp"] or 0, r["robo"] or 0)
        changed = {r["name"]: r["ts"] for r in c.execute("SELECT name, MAX(ts) ts FROM tpl_saude GROUP BY name")}
    for r in rows:
        e, f = sends.get(r["name"], (0, 0))
        resp, robo = replies.get(r["name"], (0, 0))
        r.update({"enviados": e or 0, "falhas": f or 0, "respostas": resp, "respostas_robo": robo, "ultima_mudanca": changed.get(r["name"])})
    return rows
