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
import re
import time
from pathlib import Path
from typing import Any

import httpx

import templates_db

logger = logging.getLogger("bridge.templates")

TOKEN = os.getenv("WA_CLOUD_TOKEN", "")
WABA = os.getenv("WA_CLOUD_WABA", "")
GRAPH = "https://graph.facebook.com/v23.0"
HEALTH_SECONDS = int(os.getenv("TEMPLATE_HEALTH_SECONDS", "900"))
UTILITY_TARGET = int(os.getenv("TEMPLATE_UTILITY_TARGET", "20"))
BATCH = int(os.getenv("TEMPLATE_BATCH", "30"))
MARKETING_MAX_SHARE = float(os.getenv("MARKETING_MAX_SHARE", "0.2"))
# Share of the approved stock kept as marketing, chosen by health (0 = every marketing template is deleted).
MARKETING_KEEP_SHARE = float(os.getenv("MARKETING_KEEP_SHARE", "0.2"))

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


def phrase_weights(templates: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Mean of Beta(utility+1, other+1) per opening, question and closing of the "vencedor" texts Meta decided:
    the phrases that passed as utility get drawn more ("siga os vencedores", Talles 10/10)."""
    counts: dict[str, dict[str, list[int]]] = {"abertura": {}, "pergunta": {}, "fecho": {}}
    for t in templates:
        if not str(t.get("name", "")).startswith("vencedor") or t.get("status") not in {"APPROVED", "REJECTED"}:
            continue
        m = re.match(r"^(\w+), \{\{1\}\}! (.+)\? (.+)$", body_of(t))
        if not m:
            continue
        good = t.get("status") == "APPROVED" and t.get("category") == "UTILITY"
        for kind, phrase in zip(("abertura", "pergunta", "fecho"), m.groups()):
            c = counts[kind].setdefault(phrase, [0, 0])
            c[0 if good else 1] += 1
    return {kind: {p: (u + 1) / (u + o + 2) for p, (u, o) in phrases.items()} for kind, phrases in counts.items()}


def weighted(rng: random.Random, options: list[str], weights: dict[str, float]) -> str:
    return rng.choices(options, weights=[weights.get(o, 0.5) for o in options])[0]


def scheme_text(scheme: str, rng: random.Random, weights: dict[str, dict[str, float]] | None = None) -> tuple[str, list[str]]:
    """(template body, variables in order). Never a variable at the very start or end (Meta refuses it)."""
    if scheme == "vencedor":    # small mutation of the ones that passed as utility, phrases weighted by their score
        w = weights or {}
        return (f"{weighted(rng, OPEN, w.get('abertura', {}))}, {{{{1}}}}! {weighted(rng, QUESTIONS, w.get('pergunta', {}))}? "
                f"{weighted(rng, CLOSINGS, w.get('fecho', {}))}", ["saudacao_min"])
    if scheme == "pergunta_var":  # more of the text inside variables
        return f"{rng.choice(OPEN)}, {{{{1}}}}! {{{{2}}}}? {rng.choice(CLOSINGS)}", ["saudacao_min", "pergunta_teste"]
    if scheme == "abertura_var":
        return f"{rng.choice(OPEN)}, {{{{1}}}}. {rng.choice(CLOSE_B)}", ["abertura_teste"]
    if scheme == "frase_var":
        return f"{rng.choice(OPEN_B)} {{{{1}}}}. {rng.choice(CLOSE_B)}", ["frase_teste"]
    raise ValueError(scheme)


# "isca" (approve a neutral text, edit it later) is the tactic Meta is most likely to punish: off unless asked for.
BAIT_ENABLED = os.getenv("TEMPLATE_BAIT_ENABLED", "0") == "1"
SCHEMES = ["vencedor", "pergunta_var", "abertura_var", "frase_var"] + (["isca"] if BAIT_ENABLED else [])
# Schemes the generator still submits. Until 10/10 the variable-heavy ones went 0 utility out of 109 decided, and
# Meta warns that "businesses consistently misclassifying marketing templates as utility may face warnings… rate
# limits and utility template restrictions": only the winner's variations now (Talles: "frear o gerador").
ACTIVE_SCHEMES = [s for s in os.getenv("TEMPLATE_SCHEMES", "vencedor").split(",") if s in SCHEMES]
# At most this many new first-contact templates per local day.
DAILY_MAX = int(os.getenv("TEMPLATE_DAILY_MAX", "10"))
PHONE_ID = os.getenv("WA_CLOUD_PHONE_ID", "")
# Number states that stop the queue before Meta restricts the account.
BAD_QUALITY = {"RED", "LOW"}
BAD_STATUS = {"FLAGGED", "RESTRICTED", "BANNED", "DISCONNECTED"}


def load_meta() -> dict[str, Any]:
    """The generator's state, from the central database (templates_db; the old JSON file is imported once)."""
    meta = templates_db.read_meta()
    meta.setdefault("templates", {}); meta.setdefault("usados", []); meta.setdefault("placar", {})
    return meta


def save_meta(meta: dict[str, Any]) -> None:
    templates_db.write_meta(meta)


HEALTH_WEIGHT = {"GREEN": 1.0, "UNKNOWN": 0.8, "": 0.8, "YELLOW": 0.3}


def pick_weighted(options: list[dict[str, Any]], rng: Any = None) -> dict[str, Any] | None:
    """A template drawn by health: YELLOW ones (Meta sees blocks or reports) go out much less than GREEN."""
    if not options:
        return None
    return (rng or random).choices(options, weights=[HEALTH_WEIGHT.get(str(t.get("saude") or "").upper(), 0.5) for t in options])[0]


def tipo_of(name: str, meta: dict[str, Any] | None = None) -> str | None:
    """'retomada', 'abertura' (first contact, generated or legacy) or None (not ours, e.g. hello_world)."""
    if is_retomada(name):
        return "retomada"
    if name.startswith("alerta_interno_"):
        return "interno"
    return "abertura" if params_for(name, meta) is not None else None


def familia_of(name: str) -> str | None:
    """retomada_<familia>_NN -> familia."""
    return name[len("retomada_"):].rsplit("_", 1)[0] if is_retomada(name) else None


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
    active = ACTIVE_SCHEMES or ["vencedor"]
    all_weights = dict(zip(SCHEMES, scheme_weights(meta)))
    phrases = phrase_weights(templates)
    while len(out) < count and attempts < count * 50:
        attempts += 1
        scheme = rng.choices(active, weights=[all_weights[s] for s in active])[0]
        if scheme == "isca":
            target, params = scheme_text("vencedor", rng, phrases)
            text = f"{rng.choice(OPEN)}, {{{{1}}}}! {rng.choice(BAITS)}"
        else:
            target, (text, params) = None, scheme_text(scheme, rng, phrases)
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
    data = await graph("GET", f"{WABA}/message_templates?fields=id,name,status,category,language,components,quality_score&limit=500")
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


HEALTH_RANK = {"GREEN": 0, "UNKNOWN": 1, "": 1, "YELLOW": 2, "RED": 3}


def health(t: dict[str, Any]) -> str:
    """Meta's quality score of the template (GREEN, YELLOW, RED or UNKNOWN while it has little traffic)."""
    return str(((t.get("quality_score") or {}).get("score")) or "UNKNOWN").upper()


def build_pool(templates: list[dict[str, Any]], meta: dict[str, Any]) -> list[dict[str, Any]]:
    pool = []
    for t in templates:
        params = params_for(t.get("name", ""), meta)
        text = body_of(t)
        if params is None or not_opening(t.get("name", "")) or t.get("status") != "APPROVED" or t.get("category") not in {"UTILITY", "MARKETING"} or not text or not usable(t, meta):
            continue
        if health(t) == "RED":
            continue  # recipients are blocking or reporting it: never sent again
        pool.append({"name": t["name"], "language": t.get("language", "pt_BR"), "category": t["category"], "text": text,
                     "params": params, "saude": health(t)})
    return pool


async def edit_baits(templates: list[dict[str, Any]], meta: dict[str, Any]) -> list[str]:
    if not BAIT_ENABLED:
        return []  # baits left from an earlier run stay unused (never sent: build_pool skips them)
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
    """Delete first-contact templates Meta put in MARKETING, approved or still pending (Talles: no need to keep them).

    MARKETING_KEEP_SHARE > 0 keeps that share of the approved stock as marketing (the newest), if ever wanted.
    """
    pool = build_pool(templates, meta)
    utility = sum(t["category"] == "UTILITY" for t in pool)
    marketing = [t for t in templates if t.get("status") in {"APPROVED", "PENDING"} and t.get("category") == "MARKETING"
                 and params_for(t.get("name", ""), meta) is not None and not not_opening(t.get("name", ""))]
    allowed = int(utility * MARKETING_KEEP_SHARE / (1 - MARKETING_KEEP_SHARE)) if MARKETING_KEEP_SHARE < 1 else len(marketing)
    # Healthiest approved first; pending (no health yet) and RED ones are always among the deleted.
    keepable = sorted([t for t in marketing if t.get("status") == "APPROVED" and health(t) != "RED"],
                      key=lambda t: (HEALTH_RANK.get(health(t), 1), -int(t.get("id") or 0)))
    keep = {t["name"] for t in keepable[:allowed]}
    deleted = []
    for t in [t for t in marketing if t["name"] not in keep]:
        info = meta["templates"].get(t["name"])
        if info and not info.get("contado"):  # a pending one Meta already labeled marketing still counts for the scheme
            info["contado"] = "marketing"
            placar = meta["placar"].setdefault(info["scheme"], {})
            placar["marketing"] = placar.get("marketing", 0) + 1
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


def number_alarm(number: dict[str, Any]) -> str | None:
    """Why the queue must stop now, from Meta's view of the number; None when it can go on."""
    quality = str(number.get("quality_rating") or "").upper()
    status = str(number.get("status") or "").upper()
    health = str(((number.get("health_status") or {}).get("can_send_message")) or "").upper()
    if quality in BAD_QUALITY:
        return f"qualidade do número {quality}"
    if status in BAD_STATUS:
        return f"número {status}"
    if health == "BLOCKED":
        return "Meta bloqueou o envio (health_status)"
    return None


async def guard_number() -> dict[str, Any]:
    """Pause the prospect queue when the number's quality or state turns bad (protects the account)."""
    if not PHONE_ID:
        return {}
    import prospeccao  # late import: keeps this module usable on its own
    number = await graph("GET", f"{PHONE_ID}?fields=quality_rating,messaging_limit_tier,status,health_status")
    alarm = number_alarm(number)
    if alarm and prospeccao.kv_get("prospeccao_pausada") != "1":
        prospeccao.kv_set("prospeccao_pausada", "1")
        prospeccao.kv_set("pausa_motivo", alarm)
        logger.warning("Prospect queue paused to protect the number: %s", alarm)
    elif str(number.get("quality_rating") or "").upper() in {"YELLOW", "MEDIUM"}:
        logger.warning("Number quality is %s: watch the blocks before raising the pace", number.get("quality_rating"))
    return {"qualidade": number.get("quality_rating"), "teto_meta": number.get("messaging_limit_tier"),
            "status": number.get("status"), "alarme": alarm}


async def check_once(sync_chatwoot: Any = None) -> dict[str, Any]:
    try:
        numero = await guard_number()
    except Exception as exc:
        logger.warning("Number health check failed: %s", exc)
        numero = {"erro": str(exc)[:200]}
    meta = load_meta()
    templates = await list_templates()
    learn(templates, meta)
    edited = await edit_baits(templates, meta)
    deleted = await trim_marketing(templates, meta)
    if deleted or edited:
        templates = await list_templates()
    save_meta(meta)  # the rows must exist before Meta's view of them is stored
    saude = templates_db.sync_from_meta(templates, lambda name: tipo_of(name, meta), health, body_of)
    for change in saude:
        logger.warning("Template health change: %s", json.dumps(change, ensure_ascii=False))
    pool = build_pool(templates, meta)
    templates_db.set_pool("abertura", [t["name"] for t in pool])
    # The farm keeps the target in HEALTHY utility templates: a YELLOW one still sends (less) but gets replaced.
    utility = sum(t["category"] == "UTILITY" and t.get("saude") != "YELLOW" for t in pool)
    pending = sum(1 for t in templates if t.get("status") == "PENDING" and params_for(t.get("name", ""), meta) is not None and not not_opening(t.get("name", "")))
    submitted: list[str] = []
    count = new_batch_size(utility, pending, meta)
    if count:
        submitted = await submit(new_variants(templates, meta, count), meta)
        today = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 3 * 3600))
        meta.setdefault("submetidos", {})[today] = meta.get("submetidos", {}).get(today, 0) + len(submitted)
    retomadas = await ensure_retomadas(templates, meta)
    await ensure_interno(templates, meta)
    save_meta(meta)
    if sync_chatwoot:
        await sync_chatwoot()
    report = {"quando": time.time(), "numero": numero, "utility_aprovados": utility, "marketing_aprovados": sum(t["category"] == "MARKETING" for t in pool),
              "pendentes": pending, "enviados_para_aprovacao": len(submitted), "retomadas_enviadas_para_aprovacao": retomadas,
              "retomadas_aprovadas": len(retomada_pool()), "iscas_editadas": edited, "marketing_apagados": deleted,
              "mudancas_de_saude": saude, "placar": meta["placar"]}
    logger.warning("Template health: %s", json.dumps(report, ensure_ascii=False))
    return report


def new_batch_size(utility: int, pending: int, meta: dict[str, Any], now: float | None = None) -> int:
    """How many first-contact templates to submit now: only up to the utility target (counting the pending ones),
    at most DAILY_MAX per local day (Brasília, UTC-3)."""
    today = time.strftime("%Y-%m-%d", time.gmtime((time.time() if now is None else now) - 3 * 3600))
    left_today = DAILY_MAX - int(meta.get("submetidos", {}).get(today, 0))
    return max(0, min(BATCH, left_today, UTILITY_TARGET - utility - pending))


# --- retomada templates (Talles, 10/10) -------------------------------------------------------------------------
# A retomada is a template to someone whose 24 h window is closed: the one who never answered the test, the one who
# talked and went quiet, the robot nobody followed up. Meta: re-engagement "is marketing even if requested by
# users", so they are submitted as MARKETING (never as utility: misclassifying is what Meta punishes) and count in
# the 80/20 of the day. The variables carry what is specific to each lead (the layer of Hormozi's onion the brain
# picks); the fixed text keeps them away from the start and the end and never side by side, and always ends in
# an honest way out. {{1}} who we talk to, {{2}} the fact of the case, {{3}} the argument of the layer.
RETOMADAS = {
    "retomada_sem_resposta_01": ("sem_resposta", "Oi, {{1}}! Aqui é o agente do Talles, uma inteligência artificial. {{2}} mandei uma mensagem para vocês como teste de atendimento e ela continua sem resposta. {{3}} Topa ver em 20 minutos com o Talles como isso fica resolvido, ou prefere que eu não mande mais nada?",
                                 ["pessoal da Clínica Sorriso", "Ontem às 19h40", "Quem chama vocês depois do expediente costuma fechar com quem responde primeiro."]),
    "retomada_sem_resposta_02": ("sem_resposta", "Olá, {{1}}! Sou o agente do Talles, uma IA. Testei o WhatsApp de vocês {{2}} e a mensagem ficou sem resposta até agora. {{3}} Faz sentido o Talles te mostrar em 20 minutos como responder na hora, ou não é o momento?",
                                 ["pessoal da Clínica Sorriso", "ontem às 19h40", "É nesse intervalo que o cliente desiste e chama o próximo da lista."]),
    "retomada_conversa_01": ("conversa", "Oi, {{1}}! Aqui é o agente do Talles, retomando nossa conversa sobre o WhatsApp de vocês. Você comentou que {{2}}, e {{3}}. Topa ver isso em 20 minutos com o Talles, ou prefere que eu não chame mais?",
                             ["Mariana", "a recepção sai às 18h", "é justamente depois desse horário que o atendente segura o cliente para vocês"]),
    "retomada_conversa_02": ("conversa", "Olá, {{1}}! É o agente do Talles de novo. Da última vez você falou que {{2}}. {{3}} Vale 20 minutos com o Talles nesta semana, ou não é o momento?",
                             ["Mariana", "precisava ver isso com o seu sócio", "Se fizer sentido, ele pode entrar na mesma conversa."]),
    "retomada_robo_01": ("robo", "Oi, {{1}}! Aqui é o agente do Talles, uma IA. {{2}} o atendimento automático de vocês me respondeu na hora, mas depois ninguém continuou a conversa. {{3}} Topa ver em 20 minutos com o Talles como seguir de onde a boas-vindas para, ou prefere que eu não chame mais?",
                         ["pessoal da Clínica Sorriso", "Ontem às 19h40", "É nesse ponto que o cliente que perguntou o preço vai embora."]),
    "retomada_robo_02": ("robo", "Olá, {{1}}! Sou o agente do Talles. Quando escrevi para vocês {{2}}, a resposta automática chegou rápido e a conversa parou ali. {{3}} Faz sentido ver em 20 minutos como continuar esse atendimento, ou não é o momento?",
                         ["pessoal da Clínica Sorriso", "ontem às 19h40", "Um atendente que responde e continua agenda o cliente sem ninguém da equipe."]),
}


def is_retomada(name: str) -> bool:
    return str(name or "").startswith("retomada_")


def not_opening(name: str) -> bool:
    """Retomada and internal alert templates never enter the first-contact pool, its trimming or its counts."""
    return is_retomada(name) or str(name or "").startswith("alerta_interno_")


# The retomada farm (Talles 11/10: "templates sendo farmados, tanto de abertura quanto de retomada"): variations of
# each family, always submitted as MARKETING, until RETOMADA_TARGET healthy (approved or pending) per family; at most
# RETOMADA_DAILY_MAX a day. The slots keep their meaning in every variation: {{1}} who, {{2}} the fact, {{3}} the argument.
RETOMADA_TARGET = int(os.getenv("RETOMADA_TEMPLATE_TARGET", "4"))
RETOMADA_DAILY_MAX = int(os.getenv("RETOMADA_TEMPLATE_DAILY_MAX", "6"))
RETOMADA_SKELETONS = {
    "sem_resposta": ["{abre}, {{{{1}}}}! {sou} {{{{2}}}} mandei uma mensagem para vocês como teste de atendimento e ela continua sem resposta. {{{{3}}}} {fecha}",
                     "{abre}, {{{{1}}}}! {sou} Testei o WhatsApp de vocês {{{{2}}}} e a mensagem ficou sem resposta até agora. {{{{3}}}} {fecha}",
                     "{abre}, {{{{1}}}}! {sou} Escrevi para vocês {{{{2}}}} como teste de tempo de resposta, e ninguém respondeu ainda. {{{{3}}}} {fecha}"],
    "conversa": ["{abre}, {{{{1}}}}! {volta} Você comentou que {{{{2}}}}, e {{{{3}}}}. {fecha}",
                 "{abre}, {{{{1}}}}! {volta} Da última vez você falou que {{{{2}}}}. {{{{3}}}} {fecha}"],
    "robo": ["{abre}, {{{{1}}}}! {sou} {{{{2}}}} o atendimento automático de vocês me respondeu na hora, mas depois ninguém continuou a conversa. {{{{3}}}} {fecha}",
             "{abre}, {{{{1}}}}! {sou} Quando escrevi para vocês {{{{2}}}}, a resposta automática chegou rápido e a conversa parou ali. {{{{3}}}} {fecha}"],
}
RETOMADA_OPEN = ["Oi", "Olá"]
RETOMADA_SOU = ["Aqui é o agente do Talles, uma inteligência artificial.", "Sou o agente do Talles, uma IA.", "Quem escreve é o agente do Talles, uma IA."]
RETOMADA_VOLTA = ["Aqui é o agente do Talles, retomando nossa conversa sobre o WhatsApp de vocês.", "É o agente do Talles de novo.",
                  "Aqui é o agente do Talles, voltando à nossa conversa sobre o atendimento de vocês."]
RETOMADA_FECHA = ["Topa ver em 20 minutos com o Talles como isso fica resolvido, ou prefere que eu não mande mais nada?",
                  "Faz sentido o Talles te mostrar em 20 minutos como responder na hora, ou não é o momento?",
                  "Vale 20 minutos com o Talles para ver isso funcionando, ou prefere que eu pare por aqui?",
                  "Topa ver isso em 20 minutos com o Talles, ou prefere que eu não chame mais?"]
# Utility variations (Talles 11/10: "uma farm de 80/20 pra abertura e outra de 80/20 pra retomada"): the fixed text is a
# plain note about the test or the conversation, without a sales close, and the argument stays in {{3}}. Meta decides
# the category on approval: one that comes back MARKETING counts as marketing. Names end in _uNN.
RETOMADA_UTILITY_TARGET = int(os.getenv("RETOMADA_UTILITY_TARGET", "4"))
RETOMADA_UTILITY_GIVE_UP = int(os.getenv("RETOMADA_UTILITY_GIVE_UP", "3"))  # utility asks Meta turned MARKETING before giving up
RETOMADA_UTILITY_SKELETONS = {
    "sem_resposta": ["{abre}, {{{{1}}}}. {sou} {{{{2}}}} fiz um teste de atendimento no WhatsApp de vocês. {{{{3}}}} {fecha}",
                     "{abre}, {{{{1}}}}. {sou} {{{{2}}}} mandei uma mensagem de teste para o atendimento de vocês. {{{{3}}}} {fecha}"],
    "conversa": ["{abre}, {{{{1}}}}. {volta} Sobre o que você comentou, que {{{{2}}}}: {{{{3}}}}. {fecha}",
                 "{abre}, {{{{1}}}}. {volta} Você tinha comentado que {{{{2}}}}. {{{{3}}}} {fecha}"],
    "robo": ["{abre}, {{{{1}}}}. {sou} {{{{2}}}} a resposta automática de vocês chegou e a conversa parou ali. {{{{3}}}} {fecha}",
             "{abre}, {{{{1}}}}. {sou} {{{{2}}}} escrevi para vocês e só a mensagem automática respondeu. {{{{3}}}} {fecha}"],
}
RETOMADA_UTILITY_FECHA = ["Se quiser continuar, é só responder por aqui.", "Pode me responder por aqui quando puder.",
                          "Fico por aqui se quiser continuar a conversa."]


def is_utility_variant(name: str) -> bool:
    return bool(re.search(r"_u\d+$", str(name or "")))


def retomada_example(familia: str, text: str) -> list[str]:
    """Example values Meta requires, shaped like the slot (sentence start or continuation)."""
    starts = lambda slot: text.split("{{%d}}" % slot, 1)[0].rstrip()[-1:] in {".", "!", "?", ""}
    when = "Ontem às 19h40" if starts(2) else "ontem às 19h40"
    fact = when if familia != "conversa" else "a recepção sai às 18h"
    arg = ("Quem chama depois do expediente costuma fechar com quem responde primeiro." if starts(3)
           else "é justamente depois desse horário que o atendente segura o cliente para vocês")
    return ["pessoal da Clínica Sorriso", fact, arg]


def new_retomada_variants(familia: str, count: int, templates: list[dict[str, Any]], meta: dict[str, Any], rng: random.Random | None = None,
                          utility: bool = False) -> list[dict[str, Any]]:
    rng = rng or random.Random()
    skeletons, closes, tag = (RETOMADA_UTILITY_SKELETONS, RETOMADA_UTILITY_FECHA, "u") if utility else (RETOMADA_SKELETONS, RETOMADA_FECHA, "")
    texts = set(meta["usados"]) | {body_of(t) for t in templates}
    names = {t.get("name", "") for t in templates} | set(meta["templates"])
    out, attempts = [], 0
    while len(out) < count and attempts < count * 50:
        attempts += 1
        text = rng.choice(skeletons[familia]).format(abre=rng.choice(RETOMADA_OPEN), sou=rng.choice(RETOMADA_SOU),
                                                     volta=rng.choice(RETOMADA_VOLTA), fecha=rng.choice(closes))
        if text in texts:
            continue
        number = 1
        while f"retomada_{familia}_{tag}{number:02d}" in names:
            number += 1
        name = f"retomada_{familia}_{tag}{number:02d}"
        names.add(name); texts.add(text)
        out.append({"name": name, "familia": familia, "text": text, "example": retomada_example(familia, text)})
    return out


async def submit_retomada(name: str, familia: str, text: str, example: list[str], meta: dict[str, Any], category: str = "MARKETING") -> bool:
    body = {"name": name, "category": category, "language": "pt_BR",
            "components": [{"type": "BODY", "text": text, "example": {"body_text": [example]}}]}
    meta["usados"].append(text)
    try:
        await graph("POST", f"{WABA}/message_templates", body)
    except Exception as exc:
        logger.warning("Retomada template %s not submitted: %s", name, exc)
        return False
    meta["templates"][name] = {"scheme": "retomada", "tipo": "retomada", "familia": familia, "params": ["p1", "p2", "p3"],
                               "estado": "pronto", "submetido": time.time(), "pedido": category}
    return True


async def ensure_retomadas(templates: list[dict[str, Any]], meta: dict[str, Any], now: float | None = None) -> list[str]:
    """Seeds once, then the farm up to RETOMADA_TARGET healthy per family; the approved, non-RED ones form the pool."""
    known = {t.get("name") for t in templates}
    submitted = []
    for name, (familia, text, example) in RETOMADAS.items():
        if name not in known and not meta["templates"].get(name, {}).get("submetido"):
            if await submit_retomada(name, familia, text, example, meta):
                submitted.append(name)
    today = time.strftime("%Y-%m-%d", time.gmtime((time.time() if now is None else now) - 3 * 3600))
    left = RETOMADA_DAILY_MAX - int(meta.setdefault("submetidos_retomada", {}).get(today, 0)) - len(submitted)
    for familia in RETOMADA_SKELETONS:
        # Utility first: the 80/20 of the retomadas only moves with utility ones approved as UTILITY.
        healthy_u = [t for t in templates if familia_of(t.get("name", "")) == familia and is_utility_variant(t.get("name", ""))
                     and (t.get("status") == "PENDING" or (t.get("status") == "APPROVED" and t.get("category") == "UTILITY" and health(t) not in {"RED", "YELLOW"}))]
        need = min(max(0, RETOMADA_UTILITY_TARGET - len(healthy_u)), left)
        recategorized = sum(1 for t in templates if familia_of(t.get("name", "")) == familia and is_utility_variant(t.get("name", ""))
                            and t.get("status") == "APPROVED" and t.get("category") == "MARKETING")
        if recategorized >= RETOMADA_UTILITY_GIVE_UP:
            # 11/10: Meta approved all 4 "sem_resposta" utility asks as MARKETING (nobody asked for that message). Asking
            # again only piles up recategorizations, which Meta treats as repeat offence: stop asking for this family.
            need = 0
        for v in new_retomada_variants(familia, need, templates, meta, utility=True):
            if await submit_retomada(v["name"], familia, v["text"], v["example"], meta, "UTILITY"):
                submitted.append(v["name"])
                left -= 1
        healthy = [t for t in templates if familia_of(t.get("name", "")) == familia and not is_utility_variant(t.get("name", ""))
                   and (t.get("status") == "PENDING" or (t.get("status") == "APPROVED" and health(t) not in {"RED", "YELLOW"}))]
        need = min(max(0, RETOMADA_TARGET - len(healthy)), left)
        for v in new_retomada_variants(familia, need, templates, meta):
            if await submit_retomada(v["name"], familia, v["text"], v["example"], meta):
                submitted.append(v["name"])
                left -= 1
    meta["submetidos_retomada"][today] = int(meta["submetidos_retomada"].get(today, 0)) + len(submitted)
    usable = [t["name"] for t in templates if is_retomada(t.get("name", "")) and t.get("status") == "APPROVED" and health(t) != "RED"]
    templates_db.set_pool("retomada", usable)
    return submitted


async def ensure_interno(templates: list[dict[str, Any]], meta: dict[str, Any]) -> list[str]:
    """The owner alert template (alertas.py): submitted once as UTILITY; approved and not RED, it is the 'interno' pool."""
    import alertas
    name, text, example = alertas.ALERT_TEMPLATE
    known = {t.get("name") for t in templates}
    submitted = []
    if name not in known and not meta["templates"].get(name, {}).get("submetido"):
        body = {"name": name, "category": "UTILITY", "language": "pt_BR", "components": [{"type": "BODY", "text": text, "example": {"body_text": [example]}}]}
        try:
            await graph("POST", f"{WABA}/message_templates", body)
            meta["templates"][name] = {"scheme": "interno", "tipo": "interno", "params": ["texto"], "estado": "pronto", "submetido": time.time()}
            submitted.append(name)
        except Exception as exc:
            logger.warning("Alert template %s not submitted: %s", name, exc)
    templates_db.set_pool("interno", [t["name"] for t in templates if tipo_of(t.get("name", ""), meta) == "interno"
                                      and t.get("status") == "APPROVED" and health(t) != "RED"])
    return submitted


def retomada_pool() -> list[dict[str, Any]]:
    """Approved, non-RED retomada templates, with their family (from the central database)."""
    return [{**t, "familia": t.get("familia") or familia_of(t["name"])} for t in templates_db.pool("retomada")]


def pick_retomada(familia: str, utility_sent: int, marketing_sent: int, rng: Any = None) -> dict[str, Any] | None:
    """A retomada template of the family by the retomadas' own 80/20 (Talles 11/10), apart from the openings': UTILITY
    while marketing would pass MARKETING_MAX_SHARE of the day's retomadas, MARKETING otherwise; none without a UTILITY one."""
    pool = retomada_pool()
    options = [t for t in pool if t.get("familia") == familia]
    if not any(t.get("category") == "UTILITY" for t in options) and any(t.get("category") == "UTILITY" for t in pool):
        # The 80/20 is of all the retomadas, not of each family: Meta approves "sem_resposta" only as MARKETING (nobody
        # asked for it), so that family goes in the marketing share the other families' utility ones open (11/10).
        ok = (marketing_sent + 1) / (utility_sent + marketing_sent + 1) <= MARKETING_MAX_SHARE
        return pick_weighted([t for t in options if t.get("category") == "MARKETING"], rng) if ok else None
    category = choose_category(options, utility_sent, marketing_sent)
    return pick_weighted([t for t in options if t.get("category") == category], rng) if category else None


def marketing_slot(pool: list[dict[str, Any]], utility_sent: int, marketing_sent: int) -> bool:
    """Whether one more MARKETING send keeps the day within MARKETING_MAX_SHARE, with utility in stock."""
    if not any(t.get("category") == "UTILITY" for t in pool):
        return False
    return (marketing_sent + 1) / (utility_sent + marketing_sent + 1) <= MARKETING_MAX_SHARE


def choose_category(pool: list[dict[str, Any]], utility_sent: int, marketing_sent: int) -> str | None:
    """No UTILITY in the pool: no send at all (None pauses the queue). With UTILITY, the day's sends follow
    80/20: a MARKETING one goes out whenever it keeps marketing within MARKETING_MAX_SHARE (every 5th send)."""
    if not any(t.get("category") == "UTILITY" for t in pool):
        return None
    total = utility_sent + marketing_sent + 1
    if any(t.get("category") == "MARKETING" for t in pool) and (marketing_sent + 1) / total <= MARKETING_MAX_SHARE:
        return "MARKETING"
    return "UTILITY"


if __name__ == "__main__":  # manual run: python template_health.py
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(asyncio.run(check_once()), ensure_ascii=False, indent=1))
