"""Banco central dos leads da prospecção (Talles, 11/10/2026: "nada dependa de JSON").

Every business of the prospect list, with what the enrichment found about it, lives in plain tables of the
bridge database, keyed by the normalized phone number (55 + DDD + number):

  leads                    one row per business (Google Maps data, priority, source, dates)
  lead_categorias          Maps categories, in order
  lead_servicos            services quoted on the site, in order
  lead_horarios            opening hours: weekday (0=segunda..6=domingo), open/close, closed, open 24 h
  lead_enriquecimento      what came from the site and Instagram, the hook and the dossier
  lead_decisores           the decision maker found (CNPJ, partners, who to call), one per business
  lead_socios              partners from the CNPJ
  lead_decisor_evidencias  where each fact about the decision maker came from
  lead_instagram           the business Instagram profile (by username)
  lead_instagram_posts     its recent media (one row per post URL)
  funil_classificacao      manual classification of conversations of the funnel
  funil_relatorio          the funnel report of a day (one row per conversation)
  lead_fontes              raw payload of every source, for audit only: no code reads it

Readers get dicts with the field names the code already uses (`lead(numero)` returns the same keys the old
`sdr_prospects.dados` JSON had). Nothing here needs `json.loads` to be used.
"""
import json
import re
import sqlite3
import time
from datetime import datetime
from typing import Any, Iterable

import sdr

# What the agent may know about a business (the keys of the old sdr_prospects.dados).
FIELDS = ("nome", "nicho", "categoria", "cidade", "uf", "bairro", "nota", "avaliacoes", "site", "instagram", "horario_resumo",
          "servicos", "site_leva_pro_whatsapp", "dossie", "gancho", "dias_abertos")
TEST_SOURCE = "teste_do_dono"
WEEKDAYS = {"segunda-feira": 0, "terça-feira": 1, "quarta-feira": 2, "quinta-feira": 3, "sexta-feira": 4, "sábado": 5, "domingo": 6}

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
  numero TEXT PRIMARY KEY, place_id TEXT, nome TEXT, nicho TEXT, categoria TEXT, cidade TEXT, cidade_maps TEXT, uf TEXT,
  bairro TEXT, endereco TEXT, cep TEXT, latitude REAL, longitude REAL, url_maps TEXT, site TEXT, instagram TEXT,
  instagram_usuario TEXT, facebook TEXT, nota REAL, avaliacoes INTEGER, provavel_whatsapp INTEGER, prioridade INTEGER,
  horario_google TEXT, horario_resumo TEXT, descricao_maps TEXT,
  fonte TEXT NOT NULL, coletado_em REAL, criado_em REAL NOT NULL, atualizado_em REAL NOT NULL);
CREATE INDEX IF NOT EXISTS leads_place_id ON leads(place_id);
CREATE INDEX IF NOT EXISTS leads_instagram_usuario ON leads(instagram_usuario);
CREATE INDEX IF NOT EXISTS leads_nicho_cidade ON leads(nicho, cidade);
CREATE INDEX IF NOT EXISTS leads_prioridade ON leads(prioridade);
CREATE INDEX IF NOT EXISTS leads_fonte ON leads(fonte);
CREATE TABLE IF NOT EXISTS lead_categorias (numero TEXT NOT NULL, ordem INTEGER NOT NULL, categoria TEXT NOT NULL, PRIMARY KEY (numero, ordem));
CREATE INDEX IF NOT EXISTS lead_categorias_categoria ON lead_categorias(categoria);
CREATE TABLE IF NOT EXISTS lead_servicos (numero TEXT NOT NULL, ordem INTEGER NOT NULL, servico TEXT NOT NULL, PRIMARY KEY (numero, ordem));
CREATE TABLE IF NOT EXISTS lead_horarios (
  numero TEXT NOT NULL, dia INTEGER NOT NULL, ordem INTEGER NOT NULL DEFAULT 0, abre TEXT, fecha TEXT,
  fechado INTEGER NOT NULL DEFAULT 0, aberto_24h INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (numero, dia, ordem));
CREATE INDEX IF NOT EXISTS lead_horarios_dia ON lead_horarios(dia, fechado, numero);
CREATE TABLE IF NOT EXISTS lead_enriquecimento (
  numero TEXT PRIMARY KEY, site_titulo TEXT, site_descricao TEXT, site_erro TEXT, site_leva_pro_whatsapp INTEGER,
  site_whatsapp TEXT, gancho TEXT, gancho_tipo TEXT, dossie TEXT, enriquecido INTEGER, instagram_resumo TEXT,
  instagram_engajamento TEXT, instagram_comentarios TEXT, decisor_resumo TEXT, atualizado_em REAL NOT NULL);
CREATE TABLE IF NOT EXISTS lead_decisores (
  numero TEXT PRIMARY KEY, nome_negocio TEXT, prioridade_pesquisa INTEGER, nicho TEXT, cidade TEXT, cnpj TEXT,
  razao_social TEXT, porte TEXT, abertura TEXT, nome TEXT, como_chamar TEXT, papel TEXT, instagram_pessoal TEXT,
  contato_direto TEXT, fonte_contato TEXT, confianca TEXT, nota TEXT, coletado_em REAL, atualizado_em REAL NOT NULL);
CREATE INDEX IF NOT EXISTS lead_decisores_cnpj ON lead_decisores(cnpj);
CREATE TABLE IF NOT EXISTS lead_socios (numero TEXT NOT NULL, ordem INTEGER NOT NULL, nome TEXT, qualificacao TEXT, PRIMARY KEY (numero, ordem));
CREATE TABLE IF NOT EXISTS lead_decisor_evidencias (numero TEXT NOT NULL, ordem INTEGER NOT NULL, fonte TEXT, url TEXT, trecho TEXT, PRIMARY KEY (numero, ordem));
CREATE TABLE IF NOT EXISTS lead_instagram (
  usuario TEXT PRIMARY KEY, fonte TEXT, nome TEXT, seguidores INTEGER, posts_total INTEGER, bio TEXT, site TEXT,
  privado INTEGER, erro TEXT, coletado_em REAL, atualizado_em REAL NOT NULL);
CREATE TABLE IF NOT EXISTS lead_instagram_posts (
  url TEXT PRIMARY KEY, usuario TEXT NOT NULL, ordem INTEGER NOT NULL, publicado_em TEXT, data TEXT, tipo TEXT,
  curtidas INTEGER, comentarios INTEGER, legenda TEXT, recente INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS lead_instagram_posts_usuario ON lead_instagram_posts(usuario, ordem);
CREATE TABLE IF NOT EXISTS funil_classificacao (
  conversation INTEGER PRIMARY KEY, numero TEXT, etapa_max INTEGER, etapa_nome TEXT, tipo TEXT, parou_em TEXT,
  objecao TEXT, camada TEXT, perda TEXT, prova TEXT, fonte TEXT, atualizado_em REAL NOT NULL);
CREATE INDEX IF NOT EXISTS funil_classificacao_numero ON funil_classificacao(numero);
CREATE TABLE IF NOT EXISTS funil_relatorio (
  relatorio TEXT NOT NULL, conversation INTEGER NOT NULL, numero TEXT, numero_fim TEXT, nome TEXT, nicho TEXT, cidade TEXT,
  canal TEXT, status TEXT, tipo_resposta TEXT, msgs_lead INTEGER, msgs_agente INTEGER, parou_em TEXT, etapa_spiced TEXT,
  quem_respondeu TEXT, desfecho TEXT, proximo_passo TEXT, followup TEXT, sinais_dossie TEXT, usados TEXT,
  PRIMARY KEY (relatorio, conversation));
CREATE TABLE IF NOT EXISTS lead_fontes (
  fonte TEXT NOT NULL, chave TEXT NOT NULL, numero TEXT, payload TEXT NOT NULL, coletado_em REAL, importado_em REAL NOT NULL,
  PRIMARY KEY (fonte, chave));
CREATE INDEX IF NOT EXISTS lead_fontes_numero ON lead_fontes(numero);
"""
# Prospect state that used to ride inside sdr_prospects.dados (the 10/10 "legado" marking).
PROSPECT_COLUMNS = (("status_antes_legado", "TEXT"), ("legado_em", "TEXT"))

LEAD_COLUMNS = ("place_id", "nome", "nicho", "categoria", "cidade", "cidade_maps", "uf", "bairro", "endereco", "cep", "latitude",
                "longitude", "url_maps", "site", "instagram", "instagram_usuario", "facebook", "nota", "avaliacoes",
                "provavel_whatsapp", "prioridade", "horario_google", "horario_resumo", "descricao_maps")
ENRICH_COLUMNS = ("site_titulo", "site_descricao", "site_erro", "site_leva_pro_whatsapp", "site_whatsapp", "gancho", "gancho_tipo",
                  "dossie", "enriquecido", "instagram_resumo", "instagram_engajamento", "instagram_comentarios", "decisor_resumo")
# Item key -> column, where they differ.
ALIASES = {"placeId": "place_id", "horario": "horario_google", "lat": "latitude", "lng": "longitude", "decisor": "decisor_resumo"}
INTEGER_COLUMNS = {"avaliacoes", "prioridade", "provavel_whatsapp", "site_leva_pro_whatsapp", "enriquecido"}
REAL_COLUMNS = {"nota", "latitude", "longitude"}


# --- schema ---------------------------------------------------------------------

def ensure_schema(c: sqlite3.Connection) -> None:
    """Create the lead tables and the extra sdr_prospects columns when missing (one cheap query when present)."""
    has_tables, has_prospects, has_columns = c.execute(
        "SELECT (SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='lead_fontes'),"
        " (SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='sdr_prospects'),"
        " (SELECT COUNT(*) FROM pragma_table_info('sdr_prospects') WHERE name='legado_em')").fetchone()
    if not has_tables:
        c.executescript(SCHEMA)
    if has_prospects and not has_columns:
        present = {r[1] for r in c.execute("PRAGMA table_info(sdr_prospects)")}
        for name, kind in PROSPECT_COLUMNS:
            if name not in present:
                c.execute(f"ALTER TABLE sdr_prospects ADD COLUMN {name} {kind}")
        c.commit()


def connect() -> sqlite3.Connection:
    c = sdr.connect()
    ensure_schema(c)
    return c


class _Conn:
    """Use the caller's connection (and transaction) or open, commit and close our own."""

    def __init__(self, c: sqlite3.Connection | None):
        self.given, self.c = c, c

    def __enter__(self) -> sqlite3.Connection:
        if self.c is None:
            self.c = connect()
        return self.c

    def __exit__(self, kind, *_):
        if self.given is None:
            if kind is None:
                self.c.commit()
            self.c.close()
        return False


# --- normalization --------------------------------------------------------------

def normalize_number(raw: Any) -> str | None:
    """Brazilian number as 55 + DDD + number; anything else is rejected."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if re.match(r"0[3589]00", digits):
        return None  # 0800/0300/0500/0900: no WhatsApp
    digits = digits.lstrip("0")
    if len(digits) in (10, 11):
        digits = "55" + digits
    return digits if digits.startswith("55") and len(digits) in (12, 13) else None


def instagram_user(handle: Any) -> str | None:
    """'@Foo', 'instagram.com/foo/' or 'foo' -> 'foo'."""
    text = str(handle or "").strip()
    text = re.sub(r"^(https?://)?(www\.)?instagram\.com/", "", text, flags=re.I).strip("/@ ").split("/")[0].split("?")[0]
    return text.lower() or None


def _cep(address: Any) -> str | None:
    found = re.search(r"\b(\d{5}-\d{3})\b", str(address or ""))
    return found.group(1) if found else None


def _iso_date(value: Any) -> str | None:
    """'25/11/2019' -> '2019-11-25'; ISO stays; anything else stays as written."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return text


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    """Plain text; a short list becomes 'a | b | c'; a dict (never expected) is dropped."""
    if value is None or value == "" or isinstance(value, dict):
        return None
    if isinstance(value, list):
        return " | ".join(str(v) for v in value if v not in (None, "")) or None
    return str(value)


def _typed(column: str, value: Any) -> Any:
    return _int(value) if column in INTEGER_COLUMNS else _float(value) if column in REAL_COLUMNS else _text(value)


def parse_hours(google: str) -> list[tuple[int, int, str | None, str | None, int, int]]:
    """Google's 'segunda-feira: 08:00 to 12:00, 13:30 to 18:00; domingo: Fechado; ...' as
    (dia, ordem, abre, fecha, fechado, aberto_24h) rows."""
    rows = []
    for part in (google or "").split(";"):
        day, _, spec = part.strip().partition(":")
        if day.strip().lower() not in WEEKDAYS:
            continue
        dia, spec = WEEKDAYS[day.strip().lower()], spec.strip()
        if not spec or spec.lower().startswith("fechado"):
            rows.append((dia, 0, None, None, 1, 0))
        elif "24 horas" in spec.lower() or "24 hours" in spec.lower():
            rows.append((dia, 0, "00:00", "24:00", 0, 1))
        else:
            spans = re.findall(r"(\d{1,2}:\d{2})\s*(?:to|às|a|–|-)\s*(\d{1,2}:\d{2})", spec)
            if not spans:
                rows.append((dia, 0, None, None, 0, 0))  # open, hours not understood
            for ordem, (start, end) in enumerate(spans):
                rows.append((dia, ordem, start.zfill(5), end.zfill(5), 0, 0))
    return rows


def _hours_from_days(days: Iterable[int]) -> list[tuple[int, int, str | None, str | None, int, int]]:
    """Only the open weekdays are known: open with unknown hours on those, closed on the others."""
    open_days = {int(d) for d in days}
    return [(d, 0, None, None, 0 if d in open_days else 1, 0) for d in range(7)]


# --- writes ---------------------------------------------------------------------

def _replace_children(c: sqlite3.Connection, table: str, numero: str, columns: tuple[str, ...], rows: list[tuple]) -> bool:
    """Replace the child rows of a lead when they differ; True when something changed."""
    order = ", ".join(columns)
    current = [tuple(r) for r in c.execute(f"SELECT {order} FROM {table} WHERE numero=?", (numero,))]
    if sorted(current, key=repr) == sorted((tuple(r) for r in rows), key=repr):
        return False
    c.execute(f"DELETE FROM {table} WHERE numero=?", (numero,))
    c.executemany(f"INSERT INTO {table} (numero, {order}) VALUES (?{', ?' * len(columns)})", [(numero, *r) for r in rows])
    return True


def _upsert(c: sqlite3.Connection, table: str, key: str, key_value: Any, values: dict[str, Any], insert_extra: dict[str, Any],
            now: float) -> bool:
    """Insert, or update only the given columns when one of them changed; True when something was written."""
    columns = list(values) + ["atualizado_em"]
    params = list(values.values()) + [now]
    insert_columns = [key] + columns + list(insert_extra)
    insert_params = [key_value] + params + list(insert_extra.values())
    sets = ", ".join(f"{col}=excluded.{col}" for col in columns)
    changed = " OR ".join(f"{table}.{col} IS NOT excluded.{col}" for col in values) or "0"
    cur = c.execute(f"INSERT INTO {table} ({', '.join(insert_columns)}) VALUES ({', '.join('?' * len(insert_columns))}) "
                    f"ON CONFLICT({key}) DO UPDATE SET {sets} WHERE {changed}", insert_params)
    return cur.rowcount > 0


def save(numero: str, item: dict[str, Any], fonte: str = "api", c: sqlite3.Connection | None = None,
         coletado_em: float | None = None, now: float | None = None) -> bool:
    """Create or update one business from a dict with the usual keys (the Maps/enrichment item or the queue item).

    Merge: only the keys present in `item` are written (None or "" clears that column); the others stay.
    `fonte` is kept from the first save. Returns True when anything changed.
    """
    now = time.time() if now is None else now
    item = {ALIASES.get(k, k): v for k, v in (item or {}).items()}
    if "instagram" in item:
        item["instagram_usuario"] = instagram_user(item.get("instagram"))
    if "endereco" in item and "cep" not in item:
        item["cep"] = _cep(item.get("endereco"))
    if isinstance(item.get("decisor_resumo"), dict):
        item.pop("decisor_resumo")  # a decisores.json entry: goes through save_decisor
    lead_values = {col: _typed(col, item[col]) for col in LEAD_COLUMNS if col in item}
    enrich_values = {col: _typed(col, item[col]) for col in ENRICH_COLUMNS if col in item}
    with _Conn(c) as conn:
        changed = _upsert(conn, "leads", "numero", numero, lead_values,
                          {"fonte": fonte, "coletado_em": coletado_em, "criado_em": now}, now)
        if enrich_values:
            changed |= _upsert(conn, "lead_enriquecimento", "numero", numero, enrich_values, {}, now)
        for key, table, column in (("categorias", "lead_categorias", "categoria"), ("servicos", "lead_servicos", "servico")):
            if key in item:
                values = [str(v).strip() for v in (item[key] if isinstance(item[key], list) else []) if str(v or "").strip()]
                changed |= _replace_children(conn, table, numero, ("ordem", column), list(enumerate(values)))
        hours = None
        if isinstance(item.get("horario_google"), str) and item["horario_google"].strip():
            hours = parse_hours(item["horario_google"])
        elif "dias_abertos" in item:
            days = item["dias_abertos"]
            if not isinstance(days, list):
                hours = []
            elif sorted({int(d) for d in days}) != _open_days(conn, numero):
                hours = _hours_from_days(days)
        elif "horario_google" in item:
            hours = []
        if hours is not None:
            changed |= _replace_children(conn, "lead_horarios", numero, ("dia", "ordem", "abre", "fecha", "fechado", "aberto_24h"), hours)
        if changed:
            conn.execute("UPDATE leads SET atualizado_em=? WHERE numero=?", (now, numero))
    return changed


def save_decisor(numero: str, entry: dict[str, Any], c: sqlite3.Connection | None = None, coletado_em: float | None = None,
                 now: float | None = None) -> bool:
    """One entry of decisores.json (keyed by phone): the business, its CNPJ and partners, the decision maker, the evidence."""
    now = time.time() if now is None else now
    entry = entry or {}
    person = entry.get("decisor") if isinstance(entry.get("decisor"), dict) else {}
    values = {
        "nome_negocio": _text(entry.get("nome_negocio")), "prioridade_pesquisa": _int(entry.get("prioridade")),
        "nicho": _text(entry.get("nicho")), "cidade": _text(entry.get("cidade")), "cnpj": _text(entry.get("cnpj")),
        "razao_social": _text(entry.get("razao_social")), "porte": _text(entry.get("porte")), "abertura": _iso_date(entry.get("abertura")),
        "confianca": _text(entry.get("confianca")), "nota": _text(entry.get("nota")), "coletado_em": coletado_em,
        **{k: _text(person.get(k)) for k in ("nome", "como_chamar", "papel", "instagram_pessoal", "contato_direto", "fonte_contato")},
    }
    with _Conn(c) as conn:
        changed = _upsert(conn, "lead_decisores", "numero", numero, values, {}, now)
        partners = [(i, s.get("nome"), s.get("qualificacao")) for i, s in enumerate(entry.get("socios") or []) if isinstance(s, dict)]
        changed |= _replace_children(conn, "lead_socios", numero, ("ordem", "nome", "qualificacao"), partners)
        evidence = [(i, e.get("fonte"), e.get("url"), e.get("trecho")) for i, e in enumerate(entry.get("evidencias") or []) if isinstance(e, dict)]
        changed |= _replace_children(conn, "lead_decisor_evidencias", numero, ("ordem", "fonte", "url", "trecho"), evidence)
    return changed


def save_instagram(perfil: dict[str, Any], c: sqlite3.Connection | None = None, coletado_em: float | None = None,
                   now: float | None = None) -> bool:
    """One profile of instagram-perfis.json; its media become lead_instagram_posts (recente=1 for posts_recentes)."""
    now = time.time() if now is None else now
    user = instagram_user(perfil.get("username"))
    if not user:
        return False
    values = {"fonte": _text(perfil.get("fonte")), "nome": _text(perfil.get("nome")), "seguidores": _int(perfil.get("seguidores")),
              "posts_total": _int(perfil.get("posts_total")), "bio": _text(perfil.get("bio")), "site": _text(perfil.get("site")),
              "privado": _int(perfil.get("privado")), "erro": _text(perfil.get("erro")), "coletado_em": coletado_em}
    recent = {(p.get("data"), p.get("legenda")) for p in perfil.get("posts_recentes") or [] if isinstance(p, dict)}
    with _Conn(c) as conn:
        changed = _upsert(conn, "lead_instagram", "usuario", user, values, {}, now)
        media = [m for m in perfil.get("midias") or [] if isinstance(m, dict) and m.get("url")]
        for ordem, m in enumerate(media):
            row = (user, ordem, _text(m.get("ts")), _text(m.get("data")), _text(m.get("tipo")), _int(m.get("curtidas")),
                   _int(m.get("comentarios")), _text(m.get("legenda")), int((m.get("data"), m.get("legenda")) in recent))
            cur = conn.execute(
                "INSERT INTO lead_instagram_posts (url, usuario, ordem, publicado_em, data, tipo, curtidas, comentarios, legenda, recente) "
                "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET usuario=excluded.usuario, ordem=excluded.ordem, "
                "publicado_em=excluded.publicado_em, data=excluded.data, tipo=excluded.tipo, curtidas=excluded.curtidas, "
                "comentarios=excluded.comentarios, legenda=excluded.legenda, recente=excluded.recente "
                "WHERE (lead_instagram_posts.usuario, lead_instagram_posts.ordem, lead_instagram_posts.publicado_em, lead_instagram_posts.data, "
                "lead_instagram_posts.tipo, lead_instagram_posts.curtidas, lead_instagram_posts.comentarios, lead_instagram_posts.legenda, "
                "lead_instagram_posts.recente) IS NOT (excluded.usuario, excluded.ordem, excluded.publicado_em, excluded.data, excluded.tipo, "
                "excluded.curtidas, excluded.comentarios, excluded.legenda, excluded.recente)", (m["url"], *row))
            changed |= cur.rowcount > 0
        urls = [m["url"] for m in media]
        gone = conn.execute(f"DELETE FROM lead_instagram_posts WHERE usuario=? AND url NOT IN ({','.join('?' * len(urls)) or 'NULL'})",
                            (user, *urls)).rowcount
        changed |= gone > 0
    return changed


def save_classificacao(item: dict[str, Any], fonte: str = "manual", c: sqlite3.Connection | None = None, now: float | None = None) -> bool:
    """One manual classification of a funnel conversation (the shape of funil-classificado.json)."""
    now = time.time() if now is None else now
    conversation = _int(item.get("conversation"))
    if conversation is None:
        return False
    with _Conn(c) as conn:
        values = {"numero": _number_of(conn, conversation), "etapa_max": _int(item.get("etapa_max")),
                  **{k: _text(item.get(k)) for k in ("etapa_nome", "tipo", "parou_em", "objecao", "camada", "perda", "prova")},
                  "fonte": fonte}
        return _upsert(conn, "funil_classificacao", "conversation", conversation, values, {}, now)


def save_relatorio(relatorio: str, item: dict[str, Any], c: sqlite3.Connection | None = None) -> bool:
    """One line of a funnel report (funil-AAAA-MM-DD.jsonl)."""
    conversation = _int(item.get("conversa"))
    if conversation is None:
        return False
    with _Conn(c) as conn:
        row = {"numero": _number_of(conn, conversation), "numero_fim": _text(item.get("numero_fim")),
               **{k: _text(item.get(k)) for k in ("nome", "nicho", "cidade", "canal", "status", "tipo_resposta", "parou_em",
                                                  "etapa_spiced", "quem_respondeu", "desfecho", "proximo_passo", "followup")},
               "msgs_lead": _int(item.get("msgs_lead")), "msgs_agente": _int(item.get("msgs_agente")),
               "sinais_dossie": _text(item.get("sinais_dossie")), "usados": _text(item.get("usados"))}
        current = conn.execute(f"SELECT {', '.join(row)} FROM funil_relatorio WHERE relatorio=? AND conversation=?",
                               (relatorio, conversation)).fetchone()
        if current is not None and tuple(current) == tuple(row.values()):
            return False
        conn.execute(f"INSERT OR REPLACE INTO funil_relatorio (relatorio, conversation, {', '.join(row)}) "
                     f"VALUES (?, ?{', ?' * len(row)})", (relatorio, conversation, *row.values()))
        return True


def save_fonte(fonte: str, chave: str, payload: Any, numero: str | None = None, coletado_em: float | None = None,
               c: sqlite3.Connection | None = None, now: float | None = None) -> bool:
    """Raw payload of one source item, for audit. Nothing reads it back."""
    now = time.time() if now is None else now
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    with _Conn(c) as conn:
        cur = conn.execute(
            "INSERT INTO lead_fontes (fonte, chave, numero, payload, coletado_em, importado_em) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(fonte, chave) DO UPDATE SET numero=excluded.numero, payload=excluded.payload, coletado_em=excluded.coletado_em, "
            "importado_em=excluded.importado_em WHERE lead_fontes.payload IS NOT excluded.payload OR lead_fontes.numero IS NOT excluded.numero",
            (fonte, str(chave), numero, text, coletado_em, now))
        return cur.rowcount > 0


def delete(numero: str, fonte: str | None = None, c: sqlite3.Connection | None = None) -> bool:
    """Remove a lead and its child rows (only when it came from `fonte`, if given). Used for the owner's test persona."""
    with _Conn(c) as conn:
        query, params = "SELECT 1 FROM leads WHERE numero=?", [numero]
        if fonte:
            query, params = query + " AND fonte=?", [numero, fonte]
        if not conn.execute(query, params).fetchone():
            return False
        for table in ("leads", "lead_enriquecimento", "lead_categorias", "lead_servicos", "lead_horarios", "lead_decisores",
                      "lead_socios", "lead_decisor_evidencias"):
            conn.execute(f"DELETE FROM {table} WHERE numero=?", (numero,))
        return True


# --- reads ----------------------------------------------------------------------

def _has_table(c: sqlite3.Connection, name: str) -> bool:
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _number_of(c: sqlite3.Connection, conversation: int) -> str | None:
    """The prospect number behind a Chatwoot conversation, when it is one."""
    if not _has_table(c, "sdr_prospects"):
        return None
    found = c.execute("SELECT numero FROM sdr_prospects WHERE conversation=? ORDER BY enviado_em DESC LIMIT 1", (conversation,)).fetchone()
    return found[0] if found else None


def _open_days(c: sqlite3.Connection, numero: str) -> list[int] | None:
    rows = c.execute("SELECT dia, MAX(fechado=0) FROM lead_horarios WHERE numero=? GROUP BY dia ORDER BY dia", (numero,)).fetchall()
    return [dia for dia, aberto in rows if aberto] if rows else None


def _number(value: Any) -> Any:
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _row(c: sqlite3.Connection, sql: str, params: tuple) -> dict[str, Any] | None:
    cur = c.execute(sql, params)
    row = cur.fetchone()
    return dict(zip([d[0] for d in cur.description], row)) if row else None


def lead(numero: str, c: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    """What the agent knows about a business, with the keys of the old sdr_prospects.dados (empty ones left out).
    None when the number is not a lead."""
    with _Conn(c) as conn:
        row = _row(conn, "SELECT l.nome, l.nicho, l.categoria, l.cidade, l.uf, l.bairro, l.nota, l.avaliacoes, l.site, l.instagram, "
                         "l.horario_resumo, e.site_leva_pro_whatsapp, e.dossie, e.gancho, l.fonte "
                         "FROM leads l LEFT JOIN lead_enriquecimento e ON e.numero=l.numero WHERE l.numero=?", (numero,))
        if row is None:
            return None
        services = [r[0] for r in conn.execute("SELECT servico FROM lead_servicos WHERE numero=? ORDER BY ordem", (numero,))]
        days = _open_days(conn, numero)
    fonte = row.pop("fonte")
    data: dict[str, Any] = {}
    for key in FIELDS:
        if key == "servicos":
            value = services or None
        elif key == "dias_abertos":
            value = days
        elif key == "site_leva_pro_whatsapp":
            value = None if row[key] is None else bool(row[key])
        else:
            value = _number(row.get(key))
        if value not in (None, ""):
            data[key] = value
    if fonte == TEST_SOURCE:
        data["teste_do_dono"] = True
    return data


def horarios(numero: str, c: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    with _Conn(c) as conn:
        cur = conn.execute("SELECT dia, ordem, abre, fecha, fechado, aberto_24h FROM lead_horarios WHERE numero=? ORDER BY dia, ordem", (numero,))
        names = [d[0] for d in cur.description]
        return [{**dict(zip(names, r)), "fechado": bool(r[4]), "aberto_24h": bool(r[5])} for r in cur.fetchall()]


def decisor(numero: str, c: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    """The decision maker of a business, in the shape of a decisores.json entry."""
    with _Conn(c) as conn:
        row = _row(conn, "SELECT * FROM lead_decisores WHERE numero=?", (numero,))
        if row is None:
            return None
        partners = [{"nome": r[0], "qualificacao": r[1]} for r in conn.execute("SELECT nome, qualificacao FROM lead_socios WHERE numero=? ORDER BY ordem", (numero,))]
        evidence = [{"fonte": r[0], "url": r[1], "trecho": r[2]}
                    for r in conn.execute("SELECT fonte, url, trecho FROM lead_decisor_evidencias WHERE numero=? ORDER BY ordem", (numero,))]
    person = {k: row[k] for k in ("nome", "papel", "como_chamar", "instagram_pessoal", "contato_direto", "fonte_contato")}
    out = {"nome_negocio": row["nome_negocio"], "prioridade": row["prioridade_pesquisa"], "nicho": row["nicho"], "cidade": row["cidade"],
           "cnpj": row["cnpj"], "razao_social": row["razao_social"], "socios": partners, "porte": row["porte"], "abertura": row["abertura"],
           "decisor": person if person.get("nome") else None, "evidencias": evidence, "confianca": row["confianca"]}
    if row["nota"]:
        out["nota"] = row["nota"]
    return out


def instagram(usuario: str, c: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    """A profile in the shape of instagram-perfis.json (posts_recentes and midias from lead_instagram_posts)."""
    user = instagram_user(usuario)
    with _Conn(c) as conn:
        row = _row(conn, "SELECT * FROM lead_instagram WHERE usuario=?", (user,))
        if row is None:
            return None
        cur = conn.execute("SELECT url, publicado_em, curtidas, comentarios, tipo, legenda, data, recente FROM lead_instagram_posts "
                           "WHERE usuario=? ORDER BY ordem", (user,))
        media = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
    return {"username": row["usuario"], "fonte": row["fonte"], "nome": row["nome"], "seguidores": row["seguidores"],
            "posts_total": row["posts_total"], "bio": row["bio"], "site": row["site"],
            "privado": None if row["privado"] is None else bool(row["privado"]), "erro": row["erro"],
            "posts_recentes": [{"data": m["data"], "legenda": m["legenda"]} for m in media if m["recente"]],
            "midias": [{"url": m["url"], "ts": m["publicado_em"], "curtidas": m["curtidas"], "comentarios": m["comentarios"],
                        "tipo": m["tipo"], "legenda": m["legenda"], "data": m["data"]} for m in media]}


def ficha(numero: str, c: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    """Everything known about a business: the lead row, lists, hours, enrichment, decision maker and Instagram."""
    with _Conn(c) as conn:
        row = _row(conn, "SELECT * FROM leads WHERE numero=?", (numero,))
        if row is None:
            return None
        enrich = _row(conn, "SELECT * FROM lead_enriquecimento WHERE numero=?", (numero,)) or {}
        enrich.pop("numero", None)
        enrich.pop("atualizado_em", None)
        out = {**row, **enrich,
               "categorias": [r[0] for r in conn.execute("SELECT categoria FROM lead_categorias WHERE numero=? ORDER BY ordem", (numero,))],
               "servicos": [r[0] for r in conn.execute("SELECT servico FROM lead_servicos WHERE numero=? ORDER BY ordem", (numero,))],
               "horarios": horarios(numero, conn), "dias_abertos": _open_days(conn, numero), "decisor": decisor(numero, conn),
               "instagram_perfil": instagram(row["instagram_usuario"], conn) if row.get("instagram_usuario") else None}
    for key in ("nota",):
        out[key] = _number(out.get(key))
    for key in ("provavel_whatsapp", "site_leva_pro_whatsapp", "enriquecido"):
        if out.get(key) is not None:
            out[key] = bool(out[key])
    return out


def classificacoes(c: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    """The manual funnel classification, in the shape of funil-classificado.json."""
    with _Conn(c) as conn:
        cur = conn.execute("SELECT conversation, etapa_max, etapa_nome, tipo, parou_em, objecao, camada, perda, prova "
                           "FROM funil_classificacao ORDER BY conversation")
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]


def contagens(c: sqlite3.Connection | None = None) -> dict[str, int]:
    tables = ("leads", "lead_categorias", "lead_servicos", "lead_horarios", "lead_enriquecimento", "lead_decisores", "lead_socios",
              "lead_decisor_evidencias", "lead_instagram", "lead_instagram_posts", "funil_classificacao", "funil_relatorio", "lead_fontes")
    with _Conn(c) as conn:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
