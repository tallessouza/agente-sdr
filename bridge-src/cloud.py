"""Official WhatsApp (Cloud API) through a native Chatwoot WhatsApp inbox.

Chatwoot owns the Meta side: the public webhook, media download, the 24 h window and template delivery.
The bridge listens to that inbox's Chatwoot events and answers by posting outgoing messages to it, so the
agent runs exactly the same turn pipeline as on Evolution. Contacts of this channel use the key
"<number>@cloud" (Brazilian mobiles always with the 9) so they never collide with Evolution JIDs.
"""
import json
import os
import re
import time
from typing import Any

import httpx

CHATWOOT_URL = os.getenv("CHATWOOT_URL", "http://chatwoot_rails:3000").rstrip("/")
CHATWOOT_ACCOUNT_ID = os.getenv("CHATWOOT_ACCOUNT_ID", "")
CHATWOOT_APP_TOKEN = os.getenv("CHATWOOT_APP_TOKEN", "")
CLOUD_INBOX_ID = int(os.getenv("CLOUD_INBOX_ID", "0") or 0)
# First contact of the prospect queue: an approved template (free text is refused outside the 24 h window).
TEMPLATE_NAME = os.getenv("CLOUD_PROSPECT_TEMPLATE", "falar_responsavel")
TEMPLATE_LANGUAGE = os.getenv("CLOUD_PROSPECT_TEMPLATE_LANGUAGE", "pt_BR")
TEMPLATE_CATEGORY = os.getenv("CLOUD_PROSPECT_TEMPLATE_CATEGORY", "UTILITY")
TEMPLATE_TEXT = os.getenv("CLOUD_PROSPECT_TEMPLATE_TEXT",
                          "Olá, tudo bem? Gostaria de falar com o responsável pelo atendimento de vocês. Consigo por aqui?")
# Free text only while the lead's last message is younger than this (Meta's customer service window).
WINDOW_SECONDS = int(os.getenv("CLOUD_WINDOW_SECONDS", str(23 * 3600 + 30 * 60)))
SUFFIX = "@cloud"


def enabled() -> bool:
    return bool(CLOUD_INBOX_ID)


def is_cloud(jid: str) -> bool:
    return str(jid or "").endswith(SUFFIX)


def canonical_number(raw: Any) -> str:
    """Digits only; a Brazilian mobile written without the 9 (55 + DDD + 8 digits starting 6-9) gets it back."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) == 12 and digits.startswith("55") and digits[4] in "6789":
        digits = digits[:4] + "9" + digits[4:]
    return digits


def jid_for(raw: Any) -> str:
    number = canonical_number(raw)
    return f"{number}{SUFFIX}" if number else ""


def evolution_jids(raw: Any) -> list[str]:
    """The Evolution JIDs the same number may already have (Brazilian JIDs sometimes drop the 9)."""
    number = canonical_number(raw)
    if not number:
        return []
    forms = {number}
    if len(number) == 13 and number.startswith("55") and number[4] == "9":
        forms.add(number[:4] + number[5:])
    return [f"{n}@s.whatsapp.net" for n in sorted(forms)]


def is_inbox_event(payload: dict[str, Any]) -> bool:
    if not CLOUD_INBOX_ID:
        return False
    conversation = payload.get("conversation") or {}
    inbox = (payload.get("inbox") or {}).get("id") or conversation.get("inbox_id") or payload.get("inbox_id")
    try:
        return int(inbox or 0) == CLOUD_INBOX_ID
    except (TypeError, ValueError):
        return False


def attributes_of(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("content_attributes") or {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = {}
    return value if isinstance(value, dict) else {}


def conversation_of(payload: dict[str, Any]) -> tuple[int, int]:
    """(display id, internal id) of the event's conversation."""
    conversation = payload.get("conversation") or {}
    internal = int(conversation.get("id") or payload.get("conversation_id") or 0)
    return int(conversation.get("display_id") or internal), internal


def sender_number(payload: dict[str, Any]) -> str:
    conversation = payload.get("conversation") or {}
    sender = payload.get("sender") or ((conversation.get("meta") or {}).get("sender")) or {}
    return canonical_number(sender.get("phone_number") or (conversation.get("contact_inbox") or {}).get("source_id")
                            or sender.get("identifier"))


def sender_name(payload: dict[str, Any]) -> str:
    conversation = payload.get("conversation") or {}
    sender = payload.get("sender") or ((conversation.get("meta") or {}).get("sender")) or {}
    return str(sender.get("name") or "")


def _headers(json_body: bool = True) -> dict[str, str]:
    headers = {"api_access_token": CHATWOOT_APP_TOKEN}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def _account(path: str) -> str:
    return f"{CHATWOOT_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}{path}"


async def post_message(conversation_id: int, content: str, media: tuple[bytes, str, str] | None = None,
                       template: dict[str, Any] | None = None) -> dict[str, Any]:
    """Outgoing message on the official inbox; Chatwoot delivers it through the Cloud API.

    The bridge marks its own messages so the Chatwoot webhook never mistakes them for a human takeover.
    """
    attributes = {"skip_evolution_bridge": True, "bridge_agent": True}
    endpoint = _account(f"/conversations/{conversation_id}/messages")
    async with httpx.AsyncClient(timeout=60) as client:
        if media:
            payload, mimetype, filename = media
            fields = {"content": content, "message_type": "outgoing", "private": "false", "content_attributes": json.dumps(attributes)}
            r = await client.post(endpoint, headers=_headers(json_body=False), data=fields, files={"attachments[]": (filename, payload, mimetype)})
        else:
            body: dict[str, Any] = {"content": content, "message_type": "outgoing", "private": False, "content_attributes": attributes}
            if template:
                body["template_params"] = template
            r = await client.post(endpoint, headers=_headers(), json=body)
        r.raise_for_status()
        return r.json()


# Written by template_health every half hour; the env points both modules at the same file.
TEMPLATES_FILE = os.getenv("CLOUD_TEMPLATES_FILE", "/data/templates-pool.json")
# What goes inside {{1}} of the short "Olá, {{1}}. Obrigado!" templates: the customer-like test question.
# No final punctuation: the fixed text of the template continues right after it.
TEST_PHRASES = [
    "Vocês atendem por aqui? Queria tirar uma dúvida",
    "Vocês estão atendendo pelo WhatsApp? Queria tirar uma dúvida",
    "Consigo falar com alguém por aqui? Tenho uma dúvida",
    "Vocês respondem pelo WhatsApp? Queria uma informação",
    "Vocês estão atendendo hoje? Queria tirar uma dúvida",
    "Alguém pode me ajudar por aqui? Tenho uma dúvida",
    "Tem alguém atendendo por aqui? Queria tirar uma dúvida rapidinho",
    "Vocês atendem pelo WhatsApp? Precisava de uma informação",
    "Esse WhatsApp é de vocês mesmo? Queria tirar uma dúvida",
    "Vocês atendem por mensagem? Queria uma informação",
    "Consigo uma informação com vocês por aqui? É rapidinho",
    "Vocês estão respondendo por aqui? Tenho uma dúvida",
    "Esse é o WhatsApp de atendimento de vocês? Queria tirar uma dúvida",
    "Vocês conseguem me responder por aqui? Tenho uma dúvida",
    "É por aqui que eu falo com vocês? Queria uma informação",
]


def test_fields(saudacao_min: str, rng: Any = None) -> dict[str, str]:
    """Values the template variables can take: greeting alone, test phrase alone, or both."""
    import random
    phrase = (rng or random).choice(TEST_PHRASES)
    return {"saudacao_min": saudacao_min, "frase_teste": phrase, "abertura_teste": f"{saudacao_min}! {phrase}"}


def approved_templates() -> list[dict[str, Any]]:
    """Live list of approved first-contact templates (rotated so no single text carries the volume).

    Each entry: {"name", "language", "category", "text", "params": ["nome", ...]}. `params` fills {{1}}, {{2}}...
    from the business data in order. Missing or unreadable file: an empty list (the queue then pauses).
    """
    try:
        with open(TEMPLATES_FILE, encoding="utf-8") as fh:
            items = json.load(fh)
        items = [t for t in items if isinstance(t, dict) and t.get("name") and t.get("text") and t.get("status", "APPROVED") == "APPROVED"]
        return items
    except (OSError, json.JSONDecodeError):
        # No pool yet: nothing is approved as far as we know, so the queue pauses instead of guessing.
        return []


def render_template(template: dict[str, Any], business: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """(text the lead sees, Chatwoot template_params), or None when a variable has no value for this business."""
    values = []
    for field in template.get("params") or []:
        value = str(business.get(field) or "").strip()
        if not value:
            return None
        values.append(value)
    text = str(template["text"])
    for index, value in enumerate(values, start=1):
        text = text.replace("{{%d}}" % index, value)
    params: dict[str, Any] = {"name": template["name"], "category": template.get("category", TEMPLATE_CATEGORY),
                              "language": template.get("language", TEMPLATE_LANGUAGE)}
    if values:
        params["processed_params"] = {str(i): v for i, v in enumerate(values, start=1)}
    return text, params


async def sync_templates() -> None:
    """Chatwoot only sends a template it has in its own list: refresh it after Meta changes."""
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(_account(f"/inboxes/{CLOUD_INBOX_ID}/sync_templates"), headers=_headers())
        r.raise_for_status()


def pick_template(business: dict[str, Any], rng: Any = None, category: str | None = None) -> tuple[str, dict[str, Any]]:
    import random
    candidates = [t for t in approved_templates() if not category or t.get("category", "UTILITY") == category]
    (rng or random).shuffle(candidates)
    for template in candidates:
        rendered = render_template(template, business)
        if rendered:
            return rendered
    return TEMPLATE_TEXT, {"name": TEMPLATE_NAME, "category": TEMPLATE_CATEGORY, "language": TEMPLATE_LANGUAGE}


async def open_conversation(number: str, name: str) -> tuple[str, int, int]:
    """Contact + conversation on the official inbox for a number we write first. Returns (source_id, display id, internal id)."""
    number = canonical_number(number)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(_account("/contacts/search"), headers=_headers(), params={"q": number})
        r.raise_for_status()
        found = [c for c in (r.json().get("payload") or []) if canonical_number(c.get("phone_number")) == number]
        if found:
            contact_id = int(found[0]["id"])
        else:
            r = await client.post(_account("/contacts"), headers=_headers(),
                                  json={"inbox_id": CLOUD_INBOX_ID, "name": name or number, "phone_number": "+" + number})
            r.raise_for_status()
            data = r.json().get("payload") or r.json()
            contact_id = int((data.get("contact") or data).get("id"))
        r = await client.post(_account("/conversations"), headers=_headers(),
                              json={"inbox_id": CLOUD_INBOX_ID, "contact_id": contact_id, "source_id": number, "status": "open"})
        r.raise_for_status()
        conversation = r.json()
    internal = int(conversation["id"])
    return number, int(conversation.get("display_id") or internal), internal


async def resolve_conversation(conversation_id: int) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(_account(f"/conversations/{conversation_id}/toggle_status"), headers=_headers(), json={"status": "resolved"})
        r.raise_for_status()


def window_open(last_lead_ts: float | None, now: float | None = None) -> bool:
    """Whether free text may still go out: the lead wrote within the customer service window."""
    now = time.time() if now is None else now
    return bool(last_lead_ts) and now - float(last_lead_ts) < WINDOW_SECONDS
