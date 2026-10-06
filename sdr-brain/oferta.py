"""Offer facts and deterministic checks for the reviewer.

The facts come from `ofertas.json` (hermes-sdr/, mounted in the bridge like
capacidade.json), which the bridge sends inside `context.ofertas`. Nothing
here judges tone: it only finds what a model must never let through for the
installer offer (a price that does not exist, an unknown link, a request for
the server password, a revenue promise) and the competitor names that are
forbidden for both offers.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import urlparse

OFFERS = ("instalador", "raiox")
SPICED_FIELDS = {"S": "situacao", "P": "dor", "I": "impacto", "C": "evento_critico", "D": "decisao"}
# Structure of the competitor's pages may be used; his words, names and numbers never.
FORBIDDEN_NAMES = ("naia", "squad", "avalanche", "denderson")
INSTALLER_HOSTS = {"instalador.talles.dev"}

MONEY_RE = re.compile(r"R\$\s?(\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?(\s?mil\b)?", re.I)
URL_RE = re.compile(r"(?:https?://|www\.)[^\s)>\]]+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|dev|br|io|net|app)(?:\.br)?(?:/[^\s)>\]]*)?", re.I)
SECRET = r"(?:senha|token|ip|login|usuario|acesso)(?:\s+d[oa]\s+(?:servidor|vps|bot))?"
SECRET_REQUEST_RE = re.compile(
    r"(?<!nao )(?<!nunca )(?<!nao me )(?<!nunca me )\b(?:me\s+)?(?:passa|passe|manda|mande|envia|envie|informa|informe|digita|digite|cola|cole)"
    r"\s+(?:aqui\s+|pra mim\s+|por aqui\s+)?(?:a|o|sua|seu|essa|esse)\s+" + SECRET + r"\b"
    r"|\bqual\s+(?:e\s+)?(?:a|o)\s+(?:sua\s+|seu\s+)?" + SECRET + r"\b",
)
REVENUE_PROMISE_RE = re.compile(
    r"\b(?:vai|vao|voce vai|garant\w*)\s+(?:\w+\s+){0,2}(?:faturar|lucrar|vender mais|ganhar mais|aumentar\s+(?:o\s+|seu\s+|sua\s+|as\s+|os\s+)?(?:faturamento|vendas|lucro))"
    r"|\b(?:dobrar|triplicar|multiplicar)\s+(?:o\s+|seu\s+|sua\s+|as\s+|os\s+)?(?:faturamento|vendas|lucro)"
)
DISCOUNT_RE = re.compile(r"(?<!nao )(?<!nunca )\b(?:te dou|dou|faco|faz|consigo|tem|ganha)\s+(?:um\s+)?(?:desconto|cupom)\b|\d+\s?%\s?(?:de\s+)?(?:desconto|off)\b")
FAST_DEADLINE_RE = re.compile(r"\b(?:em|ate|dentro de)\s+24\s?(?:h|hs|horas)\b(?!\s+por\s+dia)")


def fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()


def current_offer(context: dict[str, Any]) -> str | None:
    """The offer of the conversation as the bridge resolved it (record or campaign)."""
    offer = (context or {}).get("oferta") or ((context or {}).get("lead") or {}).get("oferta")
    return offer if offer in OFFERS else None


def amounts(text: str) -> set[int]:
    """Every R$ value in the text, in reais ("R$ 1.300" -> 1300, "R$ 12 mil" -> 12000)."""
    found = set()
    for number, thousand in MONEY_RE.findall(text or ""):
        value = int(number.replace(".", ""))
        found.add(value * 1000 if thousand else value)
    return found


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


def offer_amounts(ofertas: dict[str, Any], offer: str) -> set[int]:
    return {value for text in _strings((ofertas or {}).get(offer)) for value in amounts(text)}


def facts(context: dict[str, Any]) -> list[str]:
    """Readable fact list for the reviewer, generated from ofertas.json."""
    offer = current_offer(context)
    data = ((context or {}).get("ofertas") or {}).get(offer or "")
    if not isinstance(data, dict):
        return []
    lines = []
    for key, value in data.items():
        if isinstance(value, (dict, list)):
            for text in _strings(value):
                lines.append(f"{key}: {text}")
        elif value not in (None, ""):
            lines.append(f"{key}: {value}")
    return lines


def check(parts: list[str], context: dict[str, Any], lead_texts: list[str]) -> list[str]:
    """Hard violations in a draft. Each item says what is wrong, in Portuguese."""
    text = "\n".join(parts or [])
    folded = fold(text)
    issues = [f"nome proibido: {name}" for name in FORBIDDEN_NAMES if re.search(rf"\b{name}\b", folded)]
    if current_offer(context) != "instalador":
        return issues
    ofertas = (context or {}).get("ofertas") or {}
    # Numbers the lead said himself may be echoed back (the task-by-task comparison).
    allowed = offer_amounts(ofertas, "instalador") | {v for t in lead_texts for v in amounts(t)}
    if offer_amounts(ofertas, "instalador"):
        for value in sorted(amounts(text) - allowed):
            issues.append(f"valor que não existe na oferta: R$ {value:,}".replace(",", "."))
    for url in URL_RE.findall(text):
        host = urlparse(url if "://" in url else "https://" + url).netloc.lower().removeprefix("www.")
        if host not in INSTALLER_HOSTS:
            issues.append(f"link fora da oferta: {url}")
    if SECRET_REQUEST_RE.search(folded):
        issues.append("pede senha, token ou dados do servidor na conversa (só pelo formulário cifrado)")
    if REVENUE_PROMISE_RE.search(folded):
        issues.append("promessa de faturamento ou vendas")
    if DISCOUNT_RE.search(folded):
        issues.append("desconto ou cupom (não existe)")
    if FAST_DEADLINE_RE.search(folded):
        issues.append("prazo errado: a instalação é em até 48 h depois do formulário completo")
    return issues


def spiced_state(records: dict[str, str], offer: str | None) -> dict[str, Any]:
    """Which SPICED letters are on record and which are still missing."""
    done = {letter: records[field] for letter, field in SPICED_FIELDS.items() if records.get(field)}
    missing = [letter for letter in SPICED_FIELDS if letter not in done]
    if offer == "instalador":
        for field in ("tem_vps", "tem_codex"):
            if not records.get(field):
                missing.append(f"D:{field}")
    return {"oferta": offer, "etapa": records.get("etapa_spiced"), "registrado": done, "faltando": missing,
            "proximo_passo": records.get("proximo_passo"), "proximo_passo_em": records.get("proximo_passo_em")}
