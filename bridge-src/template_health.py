"""Health of the first-contact templates of the official number (Talles, 10/10/2026).

Every TEMPLATE_HEALTH_SECONDS the bridge reads the templates from Meta and rebuilds the pool the prospect
queue draws from (approved UTILITY and MARKETING). When the UTILITY stock (approved + pending) falls under
TEMPLATE_UTILITY_TARGET it submits a fresh batch of short "Olá, {{1}}. ..." variants all at once, because
Meta tends to keep a batch as utility. Sends keep at least 80% utility: marketing is only a fallback while
it stays within MARKETING_MAX_SHARE of the day's sends; with no template allowed the queue pauses itself.
"""
import asyncio
import itertools
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
USED_FILE = Path(os.getenv("CLOUD_TEMPLATES_USED_FILE", "/data/templates-used.json"))
HEALTH_SECONDS = int(os.getenv("TEMPLATE_HEALTH_SECONDS", "1800"))
UTILITY_TARGET = int(os.getenv("TEMPLATE_UTILITY_TARGET", "20"))
BATCH = int(os.getenv("TEMPLATE_BATCH", "30"))
MARKETING_MAX_SHARE = float(os.getenv("MARKETING_MAX_SHARE", "0.2"))

# Name prefix -> what fills {{1}} (see cloud.test_fields).
PARAMS = [("abordagem_a", ["abertura_teste"]), ("abordagem_b", ["frase_teste"]), ("teste_atendimento_", ["saudacao_min"])]

# Pieces of new variants. A: "<abre>, {{1}}. <fecha>" ({{1}} = greeting + question). B: "<abre> {{1}}. <fecha>" ({{1}} = question).
OPEN_A = ["Olá", "Oi", "Opa", "Olá, tudo certo", "Oi, tudo certo"]
OPEN_B = ["Olá, tudo bem?", "Oi, tudo bem?", "Olá, tudo certo?", "Oi, tudo certo?", "Olá, como vai?", "Oi, como vai?",
          "Olá, tudo bem por aí?", "Oi, tudo bem por aí?", "Olá, tudo joia?", "Oi, tudo joia?", "Olá, tudo tranquilo?",
          "Oi, tudo tranquilo?", "Olá, como estão?", "Oi, como estão?", "Olá, espero que esteja tudo bem.", "Oi, espero que esteja tudo certo."]
CLOSE = ["Obrigado pela atenção!", "Fico no aguardo, obrigado!", "Aguardo o retorno de vocês.", "Desde já, obrigado!",
         "Agradeço a atenção de vocês.", "Quando puderem, me respondam por favor.", "Valeu, fico aguardando!", "Obrigado e até já!",
         "Fico aguardando, obrigado.", "Agradeço desde já.", "Aguardo, obrigado!", "Obrigado, aguardo o retorno.",
         "Muito obrigado!", "Fico no aguardo.", "Aguardo o retorno."]
EXAMPLE = {"abertura_teste": "bom dia! Vocês atendem por aqui? Queria tirar uma dúvida",
           "frase_teste": "Vocês atendem por aqui? Queria tirar uma dúvida", "saudacao_min": "bom dia"}


def params_for(name: str) -> list[str] | None:
    return next((p for prefix, p in PARAMS if name.startswith(prefix)), None)


async def graph(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.request(method, f"{GRAPH}/{path}", headers={"Authorization": f"Bearer {TOKEN}"}, json=body)
        data = r.json()
        if r.status_code >= 400:
            raise RuntimeError(f"{r.status_code} {json.dumps(data.get('error') or data)[:300]}")
        return data


async def list_templates() -> list[dict[str, Any]]:
    data = await graph("GET", f"{WABA}/message_templates?fields=name,status,category,language,components&limit=500")
    return data.get("data") or []


def build_pool(templates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pool = []
    for t in templates:
        params = params_for(t.get("name", ""))
        body = next((c for c in t.get("components") or [] if c.get("type") == "BODY"), {})
        if params is None or t.get("status") != "APPROVED" or t.get("category") not in {"UTILITY", "MARKETING"} or not body.get("text"):
            continue
        pool.append({"name": t["name"], "language": t.get("language", "pt_BR"), "category": t["category"], "text": body["text"], "params": params})
    return pool


def _load_used() -> set[str]:
    try:
        return set(json.loads(USED_FILE.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return set()


def new_variants(templates: list[dict[str, Any]], count: int, rng: random.Random | None = None) -> list[dict[str, Any]]:
    """Unseen texts and names, half of each shape."""
    rng = rng or random.Random()
    texts = _load_used() | {c.get("text", "") for t in templates for c in t.get("components") or [] if c.get("type") == "BODY"}
    names = {t.get("name", "") for t in templates}
    shapes = [("a", f"{o}, {{{{1}}}}. {c}", "abertura_teste") for o, c in itertools.product(OPEN_A, CLOSE)]
    shapes += [("b", f"{o} {{{{1}}}}. {c}", "frase_teste") for o, c in itertools.product(OPEN_B, CLOSE)]
    rng.shuffle(shapes)
    counters = {"a": 0, "b": 0}
    out = []
    for kind, text, param in shapes:
        if len(out) >= count:
            break
        if text in texts:
            continue
        while True:
            counters[kind] += 1
            name = f"abordagem_{kind}{counters[kind]:02d}"
            if name not in names:
                break
        names.add(name); texts.add(text)
        out.append({"name": name, "category": "UTILITY", "language": "pt_BR",
                    "components": [{"type": "BODY", "text": text, "example": {"body_text": [[EXAMPLE[param]]]}}]})
    return out


async def submit(batch: list[dict[str, Any]]) -> list[str]:
    results = await asyncio.gather(*(graph("POST", f"{WABA}/message_templates", t) for t in batch), return_exceptions=True)
    used = _load_used() | {t["components"][0]["text"] for t in batch}
    USED_FILE.write_text(json.dumps(sorted(used), ensure_ascii=False), encoding="utf-8")
    sent = [t["name"] for t, r in zip(batch, results) if not isinstance(r, Exception)]
    for t, r in zip(batch, results):
        if isinstance(r, Exception):
            logger.warning("Template %s not submitted: %s", t["name"], r)
    return sent


async def check_once(sync_chatwoot: Any = None) -> dict[str, Any]:
    templates = await list_templates()
    pool = build_pool(templates)
    POOL_FILE.write_text(json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")
    utility_stock = [t for t in templates if params_for(t.get("name", "")) and t.get("category") == "UTILITY"
                     and t.get("status") in {"APPROVED", "PENDING"}]
    submitted: list[str] = []
    if len(utility_stock) < UTILITY_TARGET:
        submitted = await submit(new_variants(templates, BATCH))
    if sync_chatwoot:
        await sync_chatwoot()
    report = {"quando": time.time(), "utility_aprovados": sum(t["category"] == "UTILITY" for t in pool),
              "marketing_aprovados": sum(t["category"] == "MARKETING" for t in pool),
              "utility_estoque": len(utility_stock), "enviados_para_aprovacao": submitted}
    logger.warning("Template health: %s", report)
    return report


def choose_category(pool: list[dict[str, Any]], utility_sent: int, marketing_sent: int) -> str | None:
    """UTILITY whenever there is one; MARKETING only while it stays within the share; else None (pause)."""
    if any(t.get("category") == "UTILITY" for t in pool):
        return "UTILITY"
    total = utility_sent + marketing_sent + 1
    if any(t.get("category") == "MARKETING" for t in pool) and (marketing_sent + 1) / total <= MARKETING_MAX_SHARE:
        return "MARKETING"
    return None
