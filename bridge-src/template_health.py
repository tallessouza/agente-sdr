"""Health of the first-contact templates of the official number (Talles, 10/10/2026).

Goal: keep at least 80% of the approved first-contact templates as UTILITY (marketing up to 20%), trying
forever. Every TEMPLATE_HEALTH_SECONDS:
  1. read the templates from Meta and learn which generation scheme got UTILITY (per-scheme counts);
  2. "isca" templates approved as UTILITY are edited to the real opening (Meta allows editing an approved one);
  3. rebuild the pool the queue draws from (usable = approved, and an isca only after the edit);
  4. delete approved MARKETING beyond 20% of the stock (newest kept);
  5. while UTILITY approved < TEMPLATE_UTILITY_TARGET and fewer than a batch are pending, submit TEMPLATE_BATCH
     new variants at once, drawn from the schemes in proportion to how often each one passed as UTILITY.
Schemes start from the only opening Meta kept as utility: "Oi, {{1}}! Consigo falar com alguém por aqui? Tenho uma dúvida."
Sends keep at least 80% utility: marketing is a fallback within MARKETING_MAX_SHARE of the day; else the queue pauses.
"""
import asyncio
import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("bridge.templates")

TOKEN = os.getenv("WA_CLOUD_TOKEN", "")
WABA = os.getenv("WA_CLOUD_WABA", "")
GRAPH = "https://graph.facebook.com/v23.0"
POOL_FILE = Path(os.getenv("CLOUD_TEMPLATES_FILE", "/data/templates-pool.json"))
META_FILE = Path(os.getenv("CLOUD_TEMPLATES_META_FILE", "/data/templates-meta.json"))
HEALTH_SECONDS = int(os.getenv("TEMPLATE_HEALTH_SECONDS", "900"))
UTILITY_TARGET = int(os.getenv("TEMPLATE_UTILITY_TARGET", "20"))
BATCH = int(os.getenv("TEMPLATE_BATCH", "30"))
MARKETING_MAX_SHARE = float(os.getenv("MARKETING_MAX_SHARE", "0.2"))

# Templates created before the generator: what fills their variables comes from the name.
LEGACY_PARAMS = [("abordagem_a", ["abertura_teste"]), ("abordagem_b", ["frase_teste"]), ("teste_atendimento_", ["saudacao_min"])]

OPEN = ["Oi", "Olá", "Opa", "Oie", "Oii"]
OPEN_B = ["Olá, tudo bem?", "Oi, tudo bem?", "Olá, tudo certo?", "Oi, tudo certo?", "Olá, como vai?", "Oi, como vai?",
          "Oi, tudo bem por aí?", "Olá, tudo joia?", "Oi, tudo tranquilo?", "Olá, como estão?"]
QUESTIONS = ["Consigo falar com alguém por aqui", "Consigo falar com alguém agora", "Tem alguém disponível por aqui",
             "Alguém consegue me atender por aqui", "Consigo ser atendido por aqui", "Posso falar com alguém por aqui",
             "Consigo tirar uma dúvida por aqui", "Tem alguém por aí", "Alguém pode me atender",
             "Consigo falar com o atendimento por aqui", "Alguém consegue me ajudar", "Tem alguém atendendo agora"]
CLOSINGS = ["Tenho uma dúvida.", "Tenho uma pergunta.", "É uma dúvida rápida.", "Queria uma informação.",
            "Preciso de uma informação.", "É rapidinho.", "Queria tirar uma dúvida.", "Tenho uma dúvida rápida.",
            "Queria fazer uma pergunta.", "Preciso tirar uma dúvida."]
CLOSE_B = ["Obrigado pela atenção!", "Fico no aguardo, obrigado!", "Aguardo o retorno de vocês.", "Desde já, obrigado!",
           "Agradeço a atenção de vocês.", "Valeu, fico aguardando!", "Fico aguardando, obrigado.", "Agradeço desde já.",
           "Obrigado, aguardo o retorno.", "Fico no aguardo."]
BAITS = ["Recebemos sua mensagem e retornamos em breve.", "Sua solicitação foi registrada.", "Seu atendimento foi iniciado.",
         "Confirmamos o recebimento do seu contato.", "Estamos verificando sua solicitação.", "Seu pedido de contato foi registrado."]
EXAMPLE = {"saudacao_min": "bom dia", "pergunta_teste": "Consigo falar com alguém por aqui",
           "abertura_teste": "bom dia! Vocês atendem por aqui? Queria tirar uma dúvida",
           "frase_teste": "Vocês atendem por aqui? Queria tirar uma dúvida"}


def scheme_text(scheme: str, rng: random.Random) -> tuple[str, list[str]]:
    """(template body, variables in order). Never a variable at the very start or end (Meta refuses it)."""
    if scheme == "vencedor":    # small mutation of the one that passed as utility
        return f"{rng.choice(OPEN)}, {{{{1}}}}! {rng.choice(QUESTIONS)}? {rng.choice(CLOSINGS)}", ["saudacao_min"]
    if scheme == "pergunta_var":  # more of the text inside variables
        return f"{rng.choice(OPEN)}, {{{{1}}}}! {{{{2}}}}? {rng.choice(CLOSINGS)}", ["saudacao_min", "pergunta_teste"]
    if scheme == "abertura_var":
        return f"{rng.choice(OPEN)}, {{{{1}}}}. {rng.choice(CLOSE_B)}", ["abertura_teste"]
    if scheme == "frase_var":
        return f"{rng.choice(OPEN_B)} {{{{1}}}}. {rng.choice(CLOSE_B)}", ["frase_teste"]
    raise ValueError(scheme)


SCHEMES = ["vencedor", "pergunta_var", "abertura_var", "frase_var", "isca"]


def load_meta() -> dict[str, Any]:
    try:
        meta = json.loads(META_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        meta = {}
    meta.setdefault("templates", {}); meta.setdefault("usados", []); meta.setdefault("placar", {})
    return meta


def save_meta(meta: dict[str, Any]) -> None:
    META_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


def params_for(name: str, meta: dict[str, Any] | None = None) -> list[str] | None:
    info = (meta or {}).get("templates", {}).get(name)
    if info:
        return info.get("params")
    return next((p for prefix, p in LEGACY_PARAMS if name.startswith(prefix)), None)


def body_of(template: dict[str, Any]) -> str:
    return next((c.get("text", "") for c in template.get("components") or [] if c.get("type") == "BODY"), "")


def scheme_weights(meta: dict[str, Any]) -> list[float]:
    """Mean of Beta(utility+1, other+1): schemes that pass as utility get drawn more, none ever reaches zero."""
    weights = []
    for scheme in SCHEMES:
        p = meta["placar"].get(scheme, {})
        decided = p.get("utility", 0) + p.get("marketing", 0) + p.get("recusado", 0)
        weights.append((p.get("utility", 0) + 1) / (decided + 2))
    return weights


def new_variants(templates: list[dict[str, Any]], meta: dict[str, Any], count: int, rng: random.Random | None = None) -> list[dict[str, Any]]:
    rng = rng or random.Random()
    texts = set(meta["usados"]) | {body_of(t) for t in templates}
    names = {t.get("name", "") for t in templates} | set(meta["templates"])
    out: list[dict[str, Any]] = []
    attempts = 0
    while len(out) < count and attempts < count * 50:
        attempts += 1
        scheme = rng.choices(SCHEMES, weights=scheme_weights(meta))[0]
        if scheme == "isca":
            target, params = scheme_text("vencedor", rng)
            text = f"{rng.choice(OPEN)}, {{{{1}}}}! {rng.choice(BAITS)}"
        else:
            target, (text, params) = None, scheme_text(scheme, rng)
        if text in texts or (target and target in texts):
            continue
        number = 1
        while f"{scheme}_{number:03d}" in names:
            number += 1
        name = f"{scheme}_{number:03d}"
        names.add(name); texts.add(text)
        if target:
            texts.add(target)
        example = {"body_text": [[EXAMPLE[p] for p in params]]}
        out.append({"template": {"name": name, "category": "UTILITY", "language": "pt_BR",
                                 "components": [{"type": "BODY", "text": text, "example": example}]},
                    "info": {"scheme": scheme, "params": params, "alvo": target, "estado": "isca" if target else "pronto",
                             "criado": time.time()}})
    return out


async def graph(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.request(method, f"{GRAPH}/{path}", headers={"Authorization": f"Bearer {TOKEN}"}, json=body)
        data = r.json()
        if r.status_code >= 400:
            raise RuntimeError(f"{r.status_code} {json.dumps(data.get('error') or data)[:300]}")
        return data


async def list_templates() -> list[dict[str, Any]]:
    data = await graph("GET", f"{WABA}/message_templates?fields=id,name,status,category,language,components&limit=500")
    return data.get("data") or []


def learn(templates: list[dict[str, Any]], meta: dict[str, Any]) -> None:
    """Count, once per template (and once more after an isca edit), the category Meta settled on."""
    for t in templates:
        info = meta["templates"].get(t.get("name", ""))
        if not info or t.get("status") not in {"APPROVED", "REJECTED"}:
            continue
        outcome = "recusado" if t["status"] == "REJECTED" else ("utility" if t.get("category") == "UTILITY" else "marketing")
        key = "contado_editado" if info.get("estado") == "editado" else "contado"
        if info.get(key):
            continue
        if info.get("estado") == "isca" and outcome == "utility":
            continue  # bait approved: the score comes after the edit
        info[key] = outcome
        placar = meta["placar"].setdefault(info["scheme"], {})
        placar[outcome] = placar.get(outcome, 0) + 1


def usable(t: dict[str, Any], meta: dict[str, Any]) -> bool:
    info = meta["templates"].get(t.get("name", ""))
    return not (info and info.get("estado") == "isca")


def build_pool(templates: list[dict[str, Any]], meta: dict[str, Any]) -> list[dict[str, Any]]:
    pool = []
    for t in templates:
        params = params_for(t.get("name", ""), meta)
        text = body_of(t)
        if params is None or t.get("status") != "APPROVED" or t.get("category") not in {"UTILITY", "MARKETING"} or not text or not usable(t, meta):
            continue
        pool.append({"name": t["name"], "language": t.get("language", "pt_BR"), "category": t["category"], "text": text, "params": params})
    return pool


async def edit_baits(templates: list[dict[str, Any]], meta: dict[str, Any]) -> list[str]:
    edited = []
    for t in templates:
        info = meta["templates"].get(t.get("name", ""))
        if not info or info.get("estado") != "isca" or t.get("status") != "APPROVED":
            continue
        if t.get("category") != "UTILITY":
            info["estado"] = "falhou"
            continue
        example = {"body_text": [[EXAMPLE[p] for p in info["params"]]]}
        try:
            await graph("POST", t["id"], {"components": [{"type": "BODY", "text": info["alvo"], "example": example}]})
            info["estado"] = "editado"; info["editado_em"] = time.time()
            edited.append(t["name"])
        except Exception as exc:
            logger.warning("Bait %s not edited: %s", t["name"], exc)
    return edited


async def trim_marketing(templates: list[dict[str, Any]], meta: dict[str, Any]) -> list[str]:
    """Keep approved marketing within 20% of the approved first-contact stock (the newest stay)."""
    pool = build_pool(templates, meta)
    utility = sum(t["category"] == "UTILITY" for t in pool)
    marketing = [t for t in templates if t.get("status") == "APPROVED" and t.get("category") == "MARKETING" and params_for(t.get("name", ""), meta) is not None]
    allowed = int(utility * MARKETING_MAX_SHARE / (1 - MARKETING_MAX_SHARE))
    marketing.sort(key=lambda t: int(t.get("id") or 0), reverse=True)
    deleted = []
    for t in marketing[allowed:]:
        try:
            await graph("DELETE", f"{WABA}/message_templates?name={t['name']}&hsm_id={t['id']}")
            deleted.append(t["name"])
        except Exception as exc:
            logger.warning("Marketing template %s not deleted: %s", t["name"], exc)
    return deleted


async def submit(batch: list[dict[str, Any]], meta: dict[str, Any]) -> list[str]:
    results = await asyncio.gather(*(graph("POST", f"{WABA}/message_templates", b["template"]) for b in batch), return_exceptions=True)
    sent = []
    for b, r in zip(batch, results):
        meta["usados"].append(b["template"]["components"][0]["text"])
        if b["info"].get("alvo"):
            meta["usados"].append(b["info"]["alvo"])
        if isinstance(r, Exception):
            logger.warning("Template %s not submitted: %s", b["template"]["name"], r)
            continue
        meta["templates"][b["template"]["name"]] = b["info"]
        placar = meta["placar"].setdefault(b["info"]["scheme"], {})
        placar["enviados"] = placar.get("enviados", 0) + 1
        sent.append(b["template"]["name"])
    return sent


async def check_once(sync_chatwoot: Any = None) -> dict[str, Any]:
    meta = load_meta()
    templates = await list_templates()
    learn(templates, meta)
    edited = await edit_baits(templates, meta)
    deleted = await trim_marketing(templates, meta)
    if deleted or edited:
        templates = await list_templates()
    pool = build_pool(templates, meta)
    POOL_FILE.write_text(json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")
    utility = sum(t["category"] == "UTILITY" for t in pool)
    pending = sum(1 for t in templates if t.get("status") == "PENDING" and params_for(t.get("name", ""), meta) is not None)
    submitted: list[str] = []
    if utility < UTILITY_TARGET and pending < BATCH:
        submitted = await submit(new_variants(templates, meta, BATCH), meta)
    save_meta(meta)
    if sync_chatwoot:
        await sync_chatwoot()
    report = {"quando": time.time(), "utility_aprovados": utility, "marketing_aprovados": sum(t["category"] == "MARKETING" for t in pool),
              "pendentes": pending, "enviados_para_aprovacao": len(submitted), "iscas_editadas": edited, "marketing_apagados": deleted,
              "placar": meta["placar"]}
    logger.warning("Template health: %s", json.dumps(report, ensure_ascii=False))
    return report


def choose_category(pool: list[dict[str, Any]], utility_sent: int, marketing_sent: int) -> str | None:
    """UTILITY whenever there is one; MARKETING only while it stays within the share; else None (pause)."""
    if any(t.get("category") == "UTILITY" for t in pool):
        return "UTILITY"
    total = utility_sent + marketing_sent + 1
    if any(t.get("category") == "MARKETING" for t in pool) and (marketing_sent + 1) / total <= MARKETING_MAX_SHARE:
        return "MARKETING"
    return None


if __name__ == "__main__":  # manual run: python template_health.py
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(asyncio.run(check_once()), ensure_ascii=False, indent=1))
