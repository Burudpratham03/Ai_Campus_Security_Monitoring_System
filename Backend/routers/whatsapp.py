import asyncio
from datetime import datetime, timedelta, timezone
import logging
import os
import re
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Request
import requests

try:
    from ..database import get_db, get_users_collection
    from ..utils.identity_validation import normalize_phone
    from ..utils.guard_whatsapp_text import normalize_guard_language
    from .guard_duty import _set_guard_duty_flag, _create_duty_log, _close_duty_log
    from .admin_notifications import notify_admins
except ImportError:
    from database import get_db, get_users_collection
    from utils.identity_validation import normalize_phone
    from utils.guard_whatsapp_text import normalize_guard_language
    from routers.guard_duty import _set_guard_duty_flag, _create_duty_log, _close_duty_log
    from routers.admin_notifications import notify_admins


router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

logger = logging.getLogger("ai_campus.whatsapp")

WAHA_DUTY_ON_ROW_ID = "duty:on"
WAHA_DUTY_OFF_ROW_ID = "duty:off"
WAHA_ALERT_RESPONDING_BUTTON_ID = "alert_responding"
WAHA_ACTION_RESOLVED_BUTTON_ID = "action_resolved"
WAHA_ACTION_NOT_FOUND_BUTTON_ID = "action_not_found"
WAHA_ALERT_NEED_HELP_BUTTON_ID = "alert_need_help"

_ACTION_BUTTON_IDS = {
    WAHA_ALERT_RESPONDING_BUTTON_ID,
    WAHA_ACTION_RESOLVED_BUTTON_ID,
    WAHA_ACTION_NOT_FOUND_BUTTON_ID,
    WAHA_ALERT_NEED_HELP_BUTTON_ID,
}

WAHA_NEW_INCOMING_EVENT_TYPE = "message"
WAHA_TEXT_MESSAGE_TYPE = "chat"
WAHA_INCOMING_EVENT_HINTS = ("message", "messages.upsert", "message_create")
WAHA_ALLOWED_TEXT_MESSAGE_TYPES = {"chat", "text"}
IST_TIMEZONE = timezone(timedelta(hours=5, minutes=30))
WEBHOOK_DEDUPE_TTL_SEC = 120
TERMINAL_ALERT_STATUSES = {"resolved", "dismissed", "false_alarm"}
_RECENT_WEBHOOK_MESSAGE_IDS: dict[str, datetime] = {}
GUARD_NOT_FOUND_REPLY_COOLDOWN_SEC = int(
    os.getenv("GUARD_NOT_FOUND_REPLY_COOLDOWN_SEC", "600")
)
_RECENT_GUARD_NOT_FOUND_REPLIES: dict[str, datetime] = {}
GUARD_UPDATE_MAX_CHARS = 500

_DUTY_STATUS_FOOTERS = {
    "ON": "Please keep monitoring the Guard Dashboard and respond immediately to confirmed threats.",
    "OFF": "Your shift has ended. Have a safe rest of your day.",
}

OFF_DUTY_KEYWORDS = [
    "off duty",
    "log out",
    "logout",
    "clock out",
    "going offline",
    "offline",
    "leave",
    "ऑफ ड्यूटी",
    "ड्यूटी बंद",
]
ON_DUTY_KEYWORDS = [
    "on duty",
    "log in",
    "login",
    "clock in",
    "here",
    "ready",
    "ऑन ड्यूटी",
    "ड्यूटी सुरू",
]

_COMMAND_FIELD_KEYS = {
    "body",
    "text",
    "conversation",
    "caption",
    "selecteddisplaytext",
    "selectedbuttonid",
    "selectedbutton",
    "buttonid",
    "buttontext",
    "selectedrowid",
    "rowid",
    "replyid",
    "replytitle",
    "title",
    "id",
    "name",
    "option",
    "vote",
}

_INCIDENT_RESOLVED_KEYWORDS = {
    "resolved",
    "solve",
    "solved",
    "done",
    "cleared",
    "all clear",
    "problem solved",
    "प्रकरण निकाली",
    "निकाली",
    "समाधान",
    "सोडवले",
    "प्रश्न सुटला",
    "निराकरण झाले",
    "सुटले",
}

_INCIDENT_SAFE_KEYWORDS = {
    "safe",
    "false alarm",
    "falsealarm",
    "wrong alert",
    "गलत अलार्म",
    "सुरक्षित",
    "चुकीचा अलर्ट",
    "चुकीचा इशारा",
}

_INCIDENT_NOT_FOUND_KEYWORDS = {
    "not found",
    "target not found",
    "did not find",
    "didnt find",
    "नहीं मिला",
    "नाही सापडला",
    "सापडला नाही",
}

_INCIDENT_NEED_HELP_KEYWORDS = {
    "need help",
    "help",
    "backup",
    "support",
    "urgent help",
    "मदद",
    "मदत",
    "बॅकअप",
}


def _normalize_alert_status(value: str | None) -> str:
    token = str(value or "").strip().lower()
    if token == "verified":
        return "resolved"
    if token == "false_alarm":
        return "dismissed"
    return token


def _extract_alert_location(alert_doc: dict[str, Any] | None) -> str:
    return str((alert_doc or {}).get("location") or "AI Camera").strip() or "AI Camera"


async def _get_alert_doc(alert_id: str | None) -> dict[str, Any] | None:
    token = str(alert_id or "").strip()
    object_id = _as_object_id(token)
    if object_id is None:
        return None
    return await _alerts_collection().find_one({"_id": object_id})


def _incident_status_phrase(status: str, language: str) -> str:
    code = normalize_guard_language(language)
    token = str(status or "").strip().upper()

    if code == "hi":
        return {
            "RESOLVED": "समाधान किया गया",
            "NOT_FOUND": "मौके पर नहीं मिला",
            "NEED_HELP": "तत्काल सहायता आवश्यक",
            "SAFE_FALSE_ALARM": "सुरक्षित (गलत अलार्म)",
        }.get(token, token)

    if code == "mr":
        return {
            "RESOLVED": "निकाली काढले",
            "NOT_FOUND": "ठिकाणी सापडला नाही",
            "NEED_HELP": "तात्काळ मदत आवश्यक",
            "SAFE_FALSE_ALARM": "सुरक्षित (चुकीचा इशारा)",
        }.get(token, token)

    return {
        "RESOLVED": "Resolved",
        "NOT_FOUND": "Not Found",
        "NEED_HELP": "Need Help",
        "SAFE_FALSE_ALARM": "Safe (False Alarm)",
    }.get(token, token.title())


def _build_admin_incident_whatsapp_text(
    *,
    status: str,
    guard_name: str,
    alert_id: str | None,
    location: str | None,
    language: str,
) -> str:
    code = normalize_guard_language(language)
    localized_status = _incident_status_phrase(status, code)
    incident_id = str(alert_id or "N/A")
    incident_location = str(location or "AI Camera")
    timestamp = datetime.now(IST_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S IST")

    if code == "hi":
        return (
            "*कंट्रोल रूम अपडेट*\n"
            f"स्थिति: *{localized_status}*\n"
            f"गार्ड: {guard_name}\n"
            f"अलर्ट आईडी: {incident_id}\n"
            f"स्थान: {incident_location}\n"
            f"समय: {timestamp}"
        )

    if code == "mr":
        return (
            "*कंट्रोल रूम अपडेट*\n"
            f"स्थिती: *{localized_status}*\n"
            f"गार्ड: {guard_name}\n"
            f"अलर्ट आयडी: {incident_id}\n"
            f"ठिकाण: {incident_location}\n"
            f"वेळ: {timestamp}"
        )

    return (
        "*CONTROL ROOM UPDATE*\n"
        f"Status: *{localized_status}*\n"
        f"Guard: {guard_name}\n"
        f"Alert ID: {incident_id}\n"
        f"Location: {incident_location}\n"
        f"Time: {timestamp}"
    )


async def _notify_active_admins_whatsapp(
    *,
    status: str,
    guard_name: str,
    alert_id: str | None,
    location: str | None,
) -> list[dict[str, Any]]:
    users = get_users_collection()
    cursor = users.find(
        {
            "role": "admin",
            "is_verified": True,
            "session_active": True,
            "phone_number": {"$exists": True, "$ne": None},
        },
        {
            "phone_number": 1,
            "preferred_language": 1,
            "settings.preferred_language": 1,
            "email": 1,
        },
    )

    deliveries: list[dict[str, Any]] = []
    async for admin in cursor:
        admin_phone = _normalize_phone_digits(admin.get("phone_number"))
        if not admin_phone:
            continue

        admin_language = normalize_guard_language(
            admin.get("preferred_language")
            or (admin.get("settings") or {}).get("preferred_language")
        )
        text = _build_admin_incident_whatsapp_text(
            status=status,
            guard_name=guard_name,
            alert_id=alert_id,
            location=location,
            language=admin_language,
        )

        sent, send_error = await asyncio.to_thread(_waha_send_text, admin_phone, text)
        deliveries.append(
            {
                "admin_email": str(admin.get("email") or ""),
                "phone_number": admin_phone,
                "language": admin_language,
                "sent": bool(sent),
                "error": send_error,
            }
        )

    return deliveries


async def _notify_admin_incident_update(
    *,
    event_type: str,
    status: str,
    guard_name: str,
    guard_id: str,
    alert_id: str | None,
    location: str | None,
    priority: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": event_type,
        "guard_name": guard_name,
        "guard_id": guard_id,
        "status": status,
        "source": "WhatsApp",
        "alert_id": alert_id,
        "location": location,
    }
    if priority:
        payload["priority"] = priority

    await notify_admins(payload)
    deliveries = await _notify_active_admins_whatsapp(
        status=status,
        guard_name=guard_name,
        alert_id=alert_id,
        location=location,
    )
    return {
        "delivery_count": len(deliveries),
        "deliveries": deliveries,
    }


def _normalize_phone_digits(value: str | None) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _extract_message_id(message: dict[str, Any]) -> str:
    raw_id = message.get("id")
    if isinstance(raw_id, dict):
        for key in ("_serialized", "id"):
            token = str(raw_id.get(key) or "").strip()
            if token:
                return token

    direct = str(raw_id or "").strip()
    if direct:
        return direct

    for key in ("messageId", "msgId", "_id"):
        token = str(message.get(key) or "").strip()
        if token:
            return token

    return ""


def _is_duplicate_webhook_message(message: dict[str, Any]) -> bool:
    message_id = _extract_message_id(message)
    if not message_id:
        return False

    now = datetime.utcnow()
    cutoff = now.timestamp() - WEBHOOK_DEDUPE_TTL_SEC
    stale_keys = [
        key
        for key, seen_at in _RECENT_WEBHOOK_MESSAGE_IDS.items()
        if seen_at.timestamp() < cutoff
    ]
    for key in stale_keys:
        _RECENT_WEBHOOK_MESSAGE_IDS.pop(key, None)

    if message_id in _RECENT_WEBHOOK_MESSAGE_IDS:
        return True

    _RECENT_WEBHOOK_MESSAGE_IDS[message_id] = now
    return False


def _should_send_guard_not_found_reply(sender_digits: str) -> bool:
    sender_key = _normalize_phone_digits(sender_digits)
    if not sender_key:
        return False

    # Set env to 0 (or negative) to fully disable this auto-reply.
    if GUARD_NOT_FOUND_REPLY_COOLDOWN_SEC <= 0:
        return False

    now = datetime.utcnow()
    cutoff = now.timestamp() - GUARD_NOT_FOUND_REPLY_COOLDOWN_SEC
    stale_keys = [
        key
        for key, sent_at in _RECENT_GUARD_NOT_FOUND_REPLIES.items()
        if sent_at.timestamp() < cutoff
    ]
    for key in stale_keys:
        _RECENT_GUARD_NOT_FOUND_REPLIES.pop(key, None)

    if sender_key in _RECENT_GUARD_NOT_FOUND_REPLIES:
        return False

    _RECENT_GUARD_NOT_FOUND_REPLIES[sender_key] = now
    return True


def _build_duty_status_message(guard_name: str, status: str) -> str:
    status_upper = "ON" if str(status or "").strip().upper() == "ON" else "OFF"
    clean_guard_name = str(
        guard_name or "Security Guard").strip() or "Security Guard"
    formatted_time = datetime.now(IST_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
    footer_note = _DUTY_STATUS_FOOTERS[status_upper]
    return (
        "GUARD DUTY STATUS - CAMPUS GUARD AI\n\n"
        f"Hello {clean_guard_name},\n"
        f"You are now {status_upper} DUTY.\n"
        f"Time: {formatted_time} IST\n\n"
        f"{footer_note}"
    )


def _build_peer_help_dispatch_text(
    *,
    language: str,
    requester_name: str,
    location: str,
    alert_id: str | None,
) -> str:
    code = normalize_guard_language(language)
    incident_id = str(alert_id or "N/A")

    if code == "hi":
        return (
            "🚨 *गार्ड सहायता अनुरोध* 🚨\n"
            f"गार्ड *{requester_name}* ने तत्काल सहायता मांगी है।\n"
            f"स्थान: *{location}*\n"
            f"अलर्ट आईडी: *{incident_id}*\n"
            "कृपया तुरंत स्थान पर पहुंचें और सहायता दें।"
        )

    if code == "mr":
        return (
            "🚨 *गार्ड मदत विनंती* 🚨\n"
            f"गार्ड *{requester_name}* यांनी तात्काळ मदत मागितली आहे।\n"
            f"ठिकाण: *{location}*\n"
            f"अलर्ट आयडी: *{incident_id}*\n"
            "कृपया लगेच त्या ठिकाणी जाऊन मदत करा."
        )

    return (
        "🚨 *GUARD ASSIST REQUEST* 🚨\n"
        f"Guard *{requester_name}* requested immediate backup.\n"
        f"Location: *{location}*\n"
        f"Alert ID: *{incident_id}*\n"
        "Proceed to the location now and assist."
    )


async def _notify_peer_guards_for_help(
    *,
    requesting_guard: dict[str, Any],
    alert_id: str | None,
    location: str,
) -> list[dict[str, Any]]:
    users = get_users_collection()
    requester_id = requesting_guard.get("_id")
    requester_name = str(
        requesting_guard.get("full_name") or "Security Guard").strip() or "Security Guard"

    cursor = users.find(
        {
            "role": "guard",
            "is_verified": True,
            "isOnDuty": True,
            "whatsapp_enabled": {"$ne": False},
            "_id": {"$ne": requester_id},
        },
        {
            "_id": 1,
            "full_name": 1,
            "phone_number": 1,
            "phone_normalized": 1,
            "preferred_language": 1,
            "settings.preferred_language": 1,
        },
    )

    deliveries: list[dict[str, Any]] = []
    async for peer in cursor:
        peer_phone = _normalize_phone_digits(
            str(peer.get("phone_number") or peer.get("phone_normalized") or "")
        )
        if not peer_phone:
            continue

        peer_language = normalize_guard_language(
            peer.get("preferred_language")
            or (peer.get("settings") or {}).get("preferred_language")
        )
        text = _build_peer_help_dispatch_text(
            language=peer_language,
            requester_name=requester_name,
            location=location,
            alert_id=alert_id,
        )
        sent, send_error = await asyncio.to_thread(_waha_send_text, peer_phone, text)
        deliveries.append(
            {
                "guard_id": str(peer.get("_id") or ""),
                "guard_name": str(peer.get("full_name") or "").strip(),
                "phone_number": peer_phone,
                "sent": bool(sent),
                "error": send_error,
            }
        )

    return deliveries


def _build_peer_live_location_dispatch_text(
    *,
    language: str,
    requester_name: str,
    location: str,
    alert_id: str | None,
    maps_url: str,
) -> str:
    code = normalize_guard_language(language)
    incident_id = str(alert_id or "N/A")

    if code == "hi":
        return (
            "📍 *लाइव लोकेशन शेयर की गई*\n"
            f"गार्ड *{requester_name}* ने सहायता के लिए लाइव लोकेशन भेजी है।\n"
            f"स्थान: *{location}*\n"
            f"अलर्ट आईडी: *{incident_id}*\n"
            f"Google Maps: {maps_url}\n"
            "कृपया तुरंत सहायता के लिए पहुंचें।"
        )

    if code == "mr":
        return (
            "📍 *लाइव्ह लोकेशन शेअर केली आहे*\n"
            f"गार्ड *{requester_name}* यांनी मदतीसाठी लाइव्ह लोकेशन पाठवली आहे.\n"
            f"ठिकाण: *{location}*\n"
            f"अलर्ट आयडी: *{incident_id}*\n"
            f"Google Maps: {maps_url}\n"
            "कृपया तात्काळ मदतीसाठी पोहोचा."
        )

    return (
        "📍 *LIVE LOCATION SHARED*\n"
        f"Guard *{requester_name}* shared live location for backup.\n"
        f"Location: *{location}*\n"
        f"Alert ID: *{incident_id}*\n"
        f"Google Maps: {maps_url}\n"
        "Proceed immediately to assist."
    )


async def _notify_peer_guards_with_live_location(
    *,
    requesting_guard: dict[str, Any],
    alert_id: str | None,
    location: str,
    maps_url: str,
) -> list[dict[str, Any]]:
    users = get_users_collection()
    requester_id = requesting_guard.get("_id")
    requester_name = str(
        requesting_guard.get("full_name") or "Security Guard").strip() or "Security Guard"

    cursor = users.find(
        {
            "role": "guard",
            "is_verified": True,
            "isOnDuty": True,
            "whatsapp_enabled": {"$ne": False},
            "_id": {"$ne": requester_id},
        },
        {
            "_id": 1,
            "full_name": 1,
            "phone_number": 1,
            "phone_normalized": 1,
            "preferred_language": 1,
            "settings.preferred_language": 1,
        },
    )

    deliveries: list[dict[str, Any]] = []
    async for peer in cursor:
        peer_phone = _normalize_phone_digits(
            str(peer.get("phone_number") or peer.get("phone_normalized") or "")
        )
        if not peer_phone:
            continue

        peer_language = normalize_guard_language(
            peer.get("preferred_language")
            or (peer.get("settings") or {}).get("preferred_language")
        )
        text = _build_peer_live_location_dispatch_text(
            language=peer_language,
            requester_name=requester_name,
            location=location,
            alert_id=alert_id,
            maps_url=maps_url,
        )

        sent, send_error = await asyncio.to_thread(_waha_send_text, peer_phone, text)
        deliveries.append(
            {
                "guard_id": str(peer.get("_id") or ""),
                "guard_name": str(peer.get("full_name") or "").strip(),
                "phone_number": peer_phone,
                "sent": bool(sent),
                "error": send_error,
            }
        )

    return deliveries


def _extract_sender_digits(waha_from: str | None) -> str:
    raw = str(waha_from or "").strip()
    if raw.endswith("@c.us"):
        raw = raw[:-5]
    return _normalize_phone_digits(raw)


def _normalize_chat_jid(value: str | None) -> str:
    return str(value or "").strip().lower()


def _validate_guard_control_chat(
    incoming: dict[str, Any],
    waha_payload: dict[str, Any],
) -> tuple[bool, str | None]:
    sender_jid = _normalize_chat_jid(waha_payload.get("from"))
    target_jid = _normalize_chat_jid(
        waha_payload.get("to") or waha_payload.get("chatId")
    )
    me_jid = ""
    if isinstance(incoming, dict):
        me_value = incoming.get("me")
        if isinstance(me_value, dict):
            me_jid = _normalize_chat_jid(me_value.get("id"))

    if bool(waha_payload.get("fromMe", False)):
        return False, "from_me_message"

    # Guard controls must come only from direct chats, never groups.
    if sender_jid.endswith("@g.us") or target_jid.endswith("@g.us"):
        return False, "group_chat_not_allowed"

    # Target must be a personal WhatsApp JID (business number chat), not channels/groups.
    if target_jid and not target_jid.endswith("@c.us"):
        return False, "unsupported_target_chat"

    # When WAHA provides business identity, ensure message is addressed to that same account.
    if me_jid and target_jid and me_jid != target_jid:
        return False, "non_business_target_chat"

    return True, None


def _normalize_command_text(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    normalized = raw.replace("_", " ").replace("-", " ")
    normalized = re.sub(r"[^a-z0-9\u0900-\u097f\s]", " ", normalized)
    normalized = " ".join(normalized.split())
    return normalized


def _collect_command_candidates(payload: dict[str, Any]) -> list[str]:
    candidates: list[str] = []

    def _visit(value: Any, parent_key: str | None = None) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                key_norm = str(key).strip().lower()
                if key_norm in _COMMAND_FIELD_KEYS and isinstance(nested, (str, int, float)):
                    candidates.append(str(nested))
                _visit(nested, key_norm)
            return

        if isinstance(value, list):
            for item in value:
                _visit(item, parent_key)
            return

        if isinstance(value, (str, int, float)) and parent_key in {"selectedoptions", "votes", "selectedoption", "selectedvote"}:
            candidates.append(str(value))

    _visit(payload)

    # Explicitly include canonical row identifiers so list taps map reliably.
    for key in (
        "selectedRowId",
        "rowId",
        "selectedButtonId",
        "selectedButtonID",
        "buttonId",
        "replyId",
    ):
        val = payload.get(key)
        if val is not None:
            candidates.append(str(val))

    deduped: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        token = str(c).strip()
        if not token:
            continue
        if token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped


def _is_clock_in_message(text: str) -> bool:
    normalized = _normalize_command_text(text)
    if not normalized:
        return False
    if normalized in {"duty on", WAHA_DUTY_ON_ROW_ID}:
        return True
    if normalized in {"on duty", "on", "login", "log in", "clock in", "ready", "here", "ऑन", "ऑन ड्यूटी", "ड्यूटी सुरू"}:
        return True
    return any(word in normalized for word in ON_DUTY_KEYWORDS)


def _is_clock_out_message(text: str) -> bool:
    normalized = _normalize_command_text(text)
    if not normalized:
        return False
    if normalized in {"duty off", WAHA_DUTY_OFF_ROW_ID}:
        return True
    if normalized in {"off duty", "off", "logout", "log out", "clock out", "offline", "leave", "ऑफ", "ऑफ ड्यूटी", "ड्यूटी बंद"}:
        return True
    return any(word in normalized for word in OFF_DUTY_KEYWORDS)


def _resolve_duty_intent(candidates: list[str]) -> str | None:
    wants_in = False
    wants_out = False

    for candidate in candidates:
        normalized = _normalize_command_text(candidate)
        if not normalized:
            continue
        if _is_clock_in_message(normalized):
            wants_in = True
        if _is_clock_out_message(normalized):
            wants_out = True

    if wants_in and wants_out:
        return None
    if wants_out:
        return "off"
    if wants_in:
        return "on"
    return None


def _resolve_incident_intent(candidates: list[str]) -> str | None:
    for candidate in candidates:
        normalized = _normalize_command_text(candidate)
        if not normalized:
            continue
        if normalized in _INCIDENT_SAFE_KEYWORDS:
            return "SAFE"
        if normalized in _INCIDENT_RESOLVED_KEYWORDS:
            return "RESOLVED"
        if normalized in _INCIDENT_NOT_FOUND_KEYWORDS:
            return "NOT_FOUND"
        if normalized in _INCIDENT_NEED_HELP_KEYWORDS:
            return "NEED_HELP"
    return None


def _duty_logs_collection():
    return get_db()["duty_logs"]


def _alerts_collection():
    return get_db()["alerts"]


def _guard_notifications_collection():
    return get_db()["guard_notifications"]


async def _insert_whatsapp_duty_event(guard: dict[str, Any], action: str) -> None:
    duty_logs = _duty_logs_collection()
    now = datetime.utcnow()
    guard_id = str(guard.get("_id") or "")
    guard_name = str(guard.get("full_name")
                     or "Security Guard").strip() or "Security Guard"
    await duty_logs.insert_one(
        {
            "log_type": "status_event",
            "event_type": "whatsapp_duty_status",
            "guard_id": guard_id,
            "guardId": guard_id,
            "name": guard_name,
            "action": action,
            "source": "WhatsApp",
            "timestamp": now,
        }
    )


def _waha_send_text(chat_digits: str, text: str) -> tuple[bool, str | None]:
    base_url = str(
        os.getenv("WAHA_API_URL", "http://localhost:3000")).rstrip("/")
    session = str(os.getenv("WAHA_SESSION", "default")).strip() or "default"
    api_key = str(os.getenv("WAHA_API_KEY", "")).strip()
    timeout_sec = float(os.getenv("WAHA_TIMEOUT_SEC", "10"))

    url = f"{base_url}/api/sendText"
    payload = {
        "chatId": f"{chat_digits}@c.us",
        "text": text,
        "session": session,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-Api-Key"] = api_key

    try:
        response = requests.post(
            url, json=payload, headers=headers, timeout=timeout_sec)
        if response.ok:
            return True, None
        return False, f"status={response.status_code} body={response.text[:400]}"
    except Exception as exc:
        return False, str(exc)


def _waha_send_buttons(
    chat_digits: str,
    *,
    title: str,
    body: str,
    footer: str,
    buttons: list[dict[str, str]],
) -> tuple[bool, str | None]:
    base_url = str(
        os.getenv("WAHA_API_URL", "http://localhost:3000")).rstrip("/")
    session = str(os.getenv("WAHA_SESSION", "default")).strip() or "default"
    api_key = str(os.getenv("WAHA_API_KEY", "")).strip()
    timeout_sec = float(os.getenv("WAHA_TIMEOUT_SEC", "10"))

    url = f"{base_url}/api/sendButtons"
    payload = {
        "chatId": f"{chat_digits}@c.us",
        "session": session,
        "title": title,
        "body": body,
        "footer": footer,
        "buttons": buttons,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-Api-Key"] = api_key

    try:
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=timeout_sec,
        )
        if response.ok:
            return True, None
        return False, f"status={response.status_code} body={response.text[:400]}"
    except Exception as exc:
        return False, str(exc)


def _build_action_button_id(base_id: str, alert_id: str | None) -> str:
    token = str(alert_id or "").strip()
    if not token:
        return base_id
    return f"{base_id}:{token}"


def _waha_send_incident_action_buttons(chat_digits: str, alert_id: str | None) -> tuple[bool, str | None]:
    return _waha_send_buttons(
        chat_digits,
        title="Incident Status Update",
        body="You are assigned to this incident. Update your on-scene status:",
        footer="Campus Guard AI",
        buttons=[
            {
                "id": _build_action_button_id(WAHA_ACTION_RESOLVED_BUTTON_ID, alert_id),
                "text": "Resolved",
            },
            {
                "id": _build_action_button_id(WAHA_ACTION_NOT_FOUND_BUTTON_ID, alert_id),
                "text": "Not Found",
            },
            {
                "id": _build_action_button_id(WAHA_ALERT_NEED_HELP_BUTTON_ID, alert_id),
                "text": "Need Help",
            },
        ],
    )


def _waha_send_duty_control_buttons(chat_digits: str) -> tuple[bool, str | None]:
    return _waha_send_buttons(
        chat_digits,
        title="Duty Control",
        body="Tap ON DUTY to go ON DUTY or OFF DUTY to go OFF DUTY",
        footer="Campus Guard AI",
        buttons=[
            {
                "id": WAHA_DUTY_ON_ROW_ID,
                "text": "ON DUTY",
            },
            {
                "id": WAHA_DUTY_OFF_ROW_ID,
                "text": "OFF DUTY",
            },
        ],
    )


def _extract_guard_field_update(raw_text: str | None) -> str | None:
    text = str(raw_text or "").strip()
    if not text:
        return None

    upper = text.upper()
    prefixes = ("UPDATE", "UPDATE:", "NOTE", "NOTE:", "REPORT", "REPORT:")
    for prefix in prefixes:
        if not upper.startswith(prefix):
            continue
        note = text[len(prefix):].strip(" :-\t")
        if not note:
            return None
        if len(note) > GUARD_UPDATE_MAX_CHARS:
            note = note[:GUARD_UPDATE_MAX_CHARS].rstrip()
        return note

    return None


def _parse_action_button(candidates: list[str]) -> tuple[str | None, str | None]:
    for raw in candidates:
        token = str(raw or "").strip()
        lowered = token.lower()
        if not lowered:
            continue

        if lowered in _ACTION_BUTTON_IDS:
            return lowered, None

        for action_id in _ACTION_BUTTON_IDS:
            prefix = f"{action_id}:"
            if lowered.startswith(prefix):
                payload_token = token[len(prefix):].strip()
                return action_id, payload_token or None

    return None, None


def _as_object_id(value: str | None) -> ObjectId | None:
    token = str(value or "").strip()
    if not token:
        return None
    try:
        return ObjectId(token)
    except Exception:
        return None


async def _set_guard_activity_status(guard: dict[str, Any], status: str) -> None:
    users = get_users_collection()
    await users.update_one(
        {"_id": guard.get("_id")},
        {
            "$set": {
                "duty_activity_status": str(status or "").strip().upper() or "UNKNOWN",
                "duty_activity_updated_at": datetime.utcnow(),
            }
        },
    )


async def _find_latest_guard_alert_id(guard: dict[str, Any], sender_digits: str) -> str | None:
    notifications = _guard_notifications_collection()

    query = _build_guard_alert_query(guard, sender_digits)
    if query is None:
        return None

    doc = await notifications.find_one(
        query,
        sort=[("created_at", -1), ("_id", -1)],
    )
    if not doc:
        return None

    return str(doc.get("alert_id") or "").strip() or None


def _build_guard_alert_query(guard: dict[str, Any], sender_digits: str) -> dict[str, Any] | None:
    guard_id = str(guard.get("_id") or "").strip()
    normalized_sender = _normalize_phone_digits(sender_digits)
    last10 = normalized_sender[-10:] if normalized_sender else ""

    or_filters: list[dict[str, Any]] = []
    if guard_id:
        or_filters.append({"guard_id": guard_id})
    if normalized_sender:
        or_filters.append({"phone_number": normalized_sender})
    if last10:
        suffix_pattern = re.escape(last10) + r"$"
        or_filters.append({"phone_number": {"$regex": suffix_pattern}})

    if not or_filters:
        return None

    return {
        "$or": or_filters,
        "alert_id": {"$exists": True, "$nin": [None, ""]},
    }


async def _find_latest_active_alert_id_for_guard(
    guard: dict[str, Any],
    sender_digits: str,
) -> str | None:
    notifications = _guard_notifications_collection()
    alerts = _alerts_collection()

    query = _build_guard_alert_query(guard, sender_digits)
    if query is None:
        return None

    cursor = notifications.find(
        query,
        sort=[("created_at", -1), ("_id", -1)],
    ).limit(25)

    checked_alert_ids: set[str] = set()
    async for note in cursor:
        alert_id = str(note.get("alert_id") or "").strip()
        if not alert_id or alert_id in checked_alert_ids:
            continue
        checked_alert_ids.add(alert_id)

        object_id = _as_object_id(alert_id)
        if object_id is None:
            continue

        alert_doc = await alerts.find_one({"_id": object_id})
        if not alert_doc:
            continue

        note_location = str(note.get("location") or "").strip().lower()
        alert_location = str(alert_doc.get("location") or "").strip().lower()
        if note_location and alert_location and note_location != alert_location:
            continue

        status = str(alert_doc.get("status") or "pending").strip().lower()
        if status in TERMINAL_ALERT_STATUSES:
            continue

        return alert_id

    return None


async def _resolve_action_alert_id(
    *,
    button_alert_id: str | None,
    guard: dict[str, Any],
    sender_digits: str,
) -> str | None:
    if str(button_alert_id or "").strip():
        return str(button_alert_id).strip()
    return await _find_latest_guard_alert_id(guard, sender_digits)


async def _acknowledge_lockdown_from_text(
    *,
    guard: dict[str, Any],
    sender_digits: str,
    command: str,
) -> tuple[bool, str | None]:
    alerts = _alerts_collection()
    latest_active_alert = await alerts.find_one(
        {"status": {"$in": ["active", "pending"]}},
        sort=[("timestamp", -1)],
    )
    if not latest_active_alert:
        logger.info(
            "[WHATSAPP][LOCKDOWN] No active/pending alert found for text ack sender=%s",
            sender_digits,
        )
        return False, None

    object_id = latest_active_alert.get("_id")
    if object_id is None:
        logger.warning(
            "[WHATSAPP][LOCKDOWN] Latest active/pending alert missing _id sender=%s",
            sender_digits,
        )
        return False, None

    alert_id = str(object_id)

    guard_id = str(guard.get("_id") or "")
    guard_name = str(guard.get("full_name") or "Security Guard")
    now = datetime.utcnow()
    result = await alerts.update_one(
        {"_id": object_id},
        {
            "$set": {
                "status": "acknowledged",
                "acknowledged_by": guard_name,
                "acknowledged_guard_id": guard_id,
                "acknowledged_via": "whatsapp_text",
                "acknowledged_command": str(command or "").strip().upper(),
                "acknowledged_at": now,
            },
            "$push": {
                "action_history": {
                    "action": "acknowledged",
                    "by": guard_name,
                    "guard_id": guard_id,
                    "source": "whatsapp",
                    "timestamp": now,
                }
            },
        },
    )

    if not bool(result.matched_count):
        logger.warning(
            "[WHATSAPP][LOCKDOWN] Acknowledge update had no match alert_id=%s sender=%s",
            alert_id,
            sender_digits,
        )
        return False, alert_id

    print(
        f"[WHATSAPP][LOCKDOWN] Alert acknowledged successfully. alert_id={alert_id} sender={sender_digits} command={str(command or '').strip().upper()}"
    )
    logger.info(
        "[WHATSAPP][LOCKDOWN] Alert acknowledged successfully alert_id=%s sender=%s command=%s",
        alert_id,
        sender_digits,
        str(command or "").strip().upper(),
    )

    await notify_admins(
        {
            "type": "LOCKDOWN_ACKNOWLEDGED",
            "guard_name": guard_name,
            "guard_id": guard_id,
            "status": "ACKNOWLEDGED",
            "source": "WhatsApp",
            "alert_id": alert_id,
        }
    )
    return True, alert_id


def _extract_location_coordinates(
    message: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[float | None, float | None]:
    def _to_float(value: Any) -> float | None:
        try:
            return float(value)
        except Exception:
            return None

    containers: list[dict[str, Any]] = []
    if isinstance(message, dict):
        containers.append(message)
        nested_message_location = message.get("location")
        if isinstance(nested_message_location, dict):
            containers.append(nested_message_location)

    if isinstance(payload, dict):
        containers.append(payload)
        nested_payload_location = payload.get("location")
        if isinstance(nested_payload_location, dict):
            containers.append(nested_payload_location)

    latitude_keys = ("latitude", "lat", "Latitude")
    longitude_keys = ("longitude", "lng", "lon", "Longitude")

    for container in containers:
        lat_value = None
        lng_value = None
        for key in latitude_keys:
            if key in container:
                lat_value = _to_float(container.get(key))
                if lat_value is not None:
                    break
        for key in longitude_keys:
            if key in container:
                lng_value = _to_float(container.get(key))
                if lng_value is not None:
                    break
        if lat_value is not None and lng_value is not None:
            return lat_value, lng_value

    return None, None


async def _mark_help_requested_and_prompt_location(
    *,
    guard: dict[str, Any],
    sender_digits: str,
) -> dict[str, Any]:
    alerts = _alerts_collection()
    guard_id = str(guard.get("_id") or "")
    guard_name = str(guard.get("full_name") or "Security Guard")

    alert_id = await _find_latest_active_alert_id_for_guard(guard, sender_digits)
    alert_updated = False
    alert_location = "AI Camera"

    if alert_id:
        object_id = _as_object_id(alert_id)
        if object_id is not None:
            now = datetime.utcnow()
            action_entry = {
                "action": "needs_backup",
                "by": guard_name,
                "guard_id": guard_id,
                "source": "whatsapp",
                "timestamp": now,
            }
            result = await alerts.update_one(
                {
                    "_id": object_id,
                    "status": {"$nin": list(TERMINAL_ALERT_STATUSES)},
                },
                {
                    "$set": {
                        "status": "needs_backup",
                        "backup_requested_at": now,
                    },
                    "$push": {"action_history": action_entry},
                },
            )
            alert_updated = bool(result.matched_count)
            latest = await alerts.find_one({"_id": object_id}, {"location": 1})
            if latest:
                alert_location = _extract_alert_location(latest)

    await _notify_admin_incident_update(
        event_type="ALERT_ESCALATION",
        status="NEED_HELP",
        guard_name=guard_name,
        guard_id=guard_id,
        alert_id=alert_id,
        location=alert_location,
        priority="high",
    )

    sent, send_error = await asyncio.to_thread(
        _waha_send_text,
        sender_digits,
        "🚨 Backup requested! Please tap the 📎 (attachment) icon -> Location -> 'Send your current location' immediately.",
    )

    return {
        "ok": True,
        "status": "help_location_requested",
        "sender": sender_digits,
        "guard_id": guard_id,
        "alert_id": alert_id,
        "alert_updated": bool(alert_updated),
        "reply_sent": bool(sent),
        "reply_error": send_error,
    }


async def _append_alert_action(alert_id: str, action: str, guard: dict[str, Any]) -> bool:
    alerts = _alerts_collection()
    object_id = _as_object_id(alert_id)
    if object_id is None:
        return False

    action_entry = {
        "action": action,
        "by": str(guard.get("full_name") or "Security Guard"),
        "guard_id": str(guard.get("_id") or ""),
        "source": "whatsapp",
        "timestamp": datetime.utcnow(),
    }
    result = await alerts.update_one(
        {"_id": object_id},
        {"$push": {"action_history": action_entry}},
    )
    return bool(result.matched_count)


async def _resolve_alert_in_db(alert_id: str, guard: dict[str, Any]) -> tuple[bool, str]:
    alerts = _alerts_collection()
    object_id = _as_object_id(alert_id)
    if object_id is None:
        return False, "invalid_alert_id"

    existing = await alerts.find_one({"_id": object_id}, {"status": 1})
    if not existing:
        return False, "not_found"

    status = _normalize_alert_status(existing.get("status"))
    if status == "resolved":
        return False, "already_resolved"
    if status in {"dismissed", "false_alarm"}:
        return False, "already_closed"

    action_entry = {
        "action": "resolved",
        "by": str(guard.get("full_name") or "Security Guard"),
        "guard_id": str(guard.get("_id") or ""),
        "source": "whatsapp",
        "timestamp": datetime.utcnow(),
    }

    result = await alerts.update_one(
        {"_id": object_id},
        {
            "$set": {"verified": True, "status": "resolved"},
            "$push": {"action_history": action_entry},
        },
    )
    return bool(result.matched_count), "updated"


async def _handle_incident_text_command(
    *,
    guard: dict[str, Any],
    sender_digits: str,
    command: str,
) -> dict[str, Any]:
    guard_id = str(guard.get("_id") or "").strip()
    guard_name = str(guard.get("full_name")
                     or "Security Guard").strip() or "Security Guard"
    normalized_command = str(command or "").strip().upper()

    if normalized_command == "SAFE":
        target_status = "false_alarm"
        admin_status = "SAFE_FALSE_ALARM"
        reply_text = "✅ *INCIDENT UPDATE:* The area has been marked as SAFE (False Alarm). The control room has been notified."
    else:
        target_status = "resolved"
        admin_status = "RESOLVED"
        reply_text = "✅ *INCIDENT UPDATE:* The threat has been marked as RESOLVED. The control room has been notified."

    alert_id = await _find_latest_active_alert_id_for_guard(guard, sender_digits)
    if not alert_id:
        latest_alert_id = await _find_latest_guard_alert_id(guard, sender_digits)
        latest_alert = await _get_alert_doc(latest_alert_id)
        latest_status = _normalize_alert_status(
            str((latest_alert or {}).get("status") or "")
        )

        if normalized_command == "RESOLVED" and latest_status == "resolved":
            sent, send_error = await asyncio.to_thread(
                _waha_send_text,
                sender_digits,
                "✅ This incident was already marked as RESOLVED.",
            )
            return {
                "ok": True,
                "status": "already_resolved",
                "sender": sender_digits,
                "guard_id": guard_id,
                "alert_id": latest_alert_id,
                "reply_sent": bool(sent),
                "reply_error": send_error,
            }

        sent, send_error = await asyncio.to_thread(
            _waha_send_text,
            sender_digits,
            "No active incident was found for your current assignment.",
        )
        return {
            "ok": True,
            "status": "no_active_alert",
            "sender": sender_digits,
            "guard_id": guard_id,
            "reply_sent": bool(sent),
            "reply_error": send_error,
        }

    alert_doc = await _get_alert_doc(alert_id)
    alert_location = _extract_alert_location(alert_doc)

    object_id = _as_object_id(alert_id)
    if object_id is None:
        sent, send_error = await asyncio.to_thread(
            _waha_send_text,
            sender_digits,
            "Could not process this incident update because the alert ID is invalid.",
        )
        return {
            "ok": True,
            "status": "invalid_alert_id",
            "sender": sender_digits,
            "guard_id": guard_id,
            "alert_id": alert_id,
            "reply_sent": bool(sent),
            "reply_error": send_error,
        }

    update_set: dict[str, Any] = {"status": target_status}
    update_set["verified"] = normalized_command == "RESOLVED"

    action_entry = {
        "action": target_status,
        "by": guard_name,
        "guard_id": guard_id,
        "source": "whatsapp",
        "timestamp": datetime.utcnow(),
    }

    result = await _alerts_collection().update_one(
        {"_id": object_id, "status": {"$nin": list(TERMINAL_ALERT_STATUSES)}},
        {
            "$set": update_set,
            "$push": {"action_history": action_entry},
        },
    )

    if not bool(result.matched_count):
        latest_doc = await _get_alert_doc(alert_id)
        latest_status = _normalize_alert_status(
            str((latest_doc or {}).get("status") or "")
        )
        if normalized_command == "RESOLVED" and latest_status == "resolved":
            reply_text = "✅ This incident was already marked as RESOLVED."
        elif normalized_command == "RESOLVED" and latest_status in {"dismissed", "false_alarm"}:
            reply_text = "⚠️ This incident was already closed as a false alarm."

    if bool(result.matched_count):
        await _set_guard_activity_status(guard, "ON_DUTY")
        if normalized_command == "RESOLVED" and not bool(guard.get("isOnDuty", False)):
            await _set_guard_duty_flag(guard, True)
            await _create_duty_log(guard, datetime.utcnow())

        await _notify_admin_incident_update(
            event_type="ALERT_STATUS_UPDATE",
            status=admin_status,
            guard_name=guard_name,
            guard_id=guard_id,
            alert_id=alert_id,
            location=alert_location,
        )

    sent, send_error = await asyncio.to_thread(
        _waha_send_text,
        sender_digits,
        reply_text,
    )
    return {
        "ok": True,
        "status": f"incident_{target_status}",
        "sender": sender_digits,
        "guard_id": guard_id,
        "alert_id": alert_id,
        "alert_updated": bool(result.matched_count),
        "reply_sent": bool(sent),
        "reply_error": send_error,
    }


async def _handle_guard_field_update_command(
    *,
    guard: dict[str, Any],
    sender_digits: str,
    note: str,
) -> dict[str, Any]:
    guard_id = str(guard.get("_id") or "").strip()
    guard_name = str(guard.get("full_name")
                     or "Security Guard").strip() or "Security Guard"
    clean_note = str(note or "").strip()
    if not clean_note:
        sent, send_error = await asyncio.to_thread(
            _waha_send_text,
            sender_digits,
            "Please send update as: UPDATE <your message>",
        )
        return {
            "ok": True,
            "status": "empty_update_note",
            "sender": sender_digits,
            "guard_id": guard_id,
            "reply_sent": bool(sent),
            "reply_error": send_error,
        }

    alert_id = await _find_latest_active_alert_id_for_guard(guard, sender_digits)
    if not alert_id:
        sent, send_error = await asyncio.to_thread(
            _waha_send_text,
            sender_digits,
            "No active incident found. If you are reporting a live scene, contact control room immediately.",
        )
        return {
            "ok": True,
            "status": "no_active_alert_for_update",
            "sender": sender_digits,
            "guard_id": guard_id,
            "reply_sent": bool(sent),
            "reply_error": send_error,
        }

    object_id = _as_object_id(alert_id)
    if object_id is None:
        sent, send_error = await asyncio.to_thread(
            _waha_send_text,
            sender_digits,
            "Could not attach this update because alert reference is invalid.",
        )
        return {
            "ok": True,
            "status": "invalid_alert_for_update",
            "sender": sender_digits,
            "guard_id": guard_id,
            "alert_id": alert_id,
            "reply_sent": bool(sent),
            "reply_error": send_error,
        }

    action_entry = {
        "action": "guard_update",
        "note": clean_note,
        "by": guard_name,
        "guard_id": guard_id,
        "source": "whatsapp",
        "timestamp": datetime.utcnow(),
    }
    result = await _alerts_collection().update_one(
        {"_id": object_id},
        {"$push": {"action_history": action_entry}},
    )

    if bool(result.matched_count):
        await notify_admins(
            {
                "type": "GUARD_FIELD_UPDATE",
                "guard_name": guard_name,
                "guard_id": guard_id,
                "source": "WhatsApp",
                "alert_id": alert_id,
                "note": clean_note,
            }
        )

    sent, send_error = await asyncio.to_thread(
        _waha_send_text,
        sender_digits,
        "✅ Incident update received. Control room has been notified.",
    )

    return {
        "ok": True,
        "status": "guard_update_logged",
        "sender": sender_digits,
        "guard_id": guard_id,
        "alert_id": alert_id,
        "alert_updated": bool(result.matched_count),
        "reply_sent": bool(sent),
        "reply_error": send_error,
    }


async def _find_guard_by_phone(phone_digits: str) -> dict[str, Any] | None:
    users = get_users_collection()
    normalized_phone = normalize_phone(phone_digits)
    if not normalized_phone:
        return None

    candidate_numbers: list[str] = []
    for value in [normalized_phone, normalized_phone[-10:]]:
        token = str(value or "").strip()
        if token and token not in candidate_numbers:
            candidate_numbers.append(token)

    # Try exact matches first across normalized and raw phone fields.
    guard = await users.find_one(
        {
            "role": "guard",
            "$or": [
                {"phone_normalized": {"$in": candidate_numbers}},
                {"phone_number": {"$in": candidate_numbers}},
            ],
        }
    )
    if guard:
        return guard

    # Fallback: suffix match to tolerate country code inconsistencies.
    last10 = normalized_phone[-10:]
    if not last10:
        return None

    suffix_pattern = re.escape(last10) + r"$"
    guard = await users.find_one(
        {
            "role": "guard",
            "$or": [
                {"phone_normalized": {"$regex": suffix_pattern}},
                {"phone_number": {"$regex": suffix_pattern}},
            ],
        }
    )
    return guard


async def _handle_action_button(
    *,
    action_id: str,
    action_alert_id: str | None,
    guard: dict[str, Any],
    sender_digits: str,
) -> dict[str, Any]:
    guard_id = str(guard.get("_id") or "")
    guard_name = str(guard.get("full_name") or "Security Guard")

    alert_id = await _resolve_action_alert_id(
        button_alert_id=action_alert_id,
        guard=guard,
        sender_digits=sender_digits,
    )
    alert_doc = await _get_alert_doc(alert_id)
    alert_location = _extract_alert_location(alert_doc)

    if action_id == WAHA_ALERT_RESPONDING_BUTTON_ID:
        if alert_id:
            object_id = _as_object_id(alert_id)
            if object_id is not None:
                await _alerts_collection().update_one(
                    {
                        "_id": object_id,
                        "status": {"$nin": list(TERMINAL_ALERT_STATUSES)},
                    },
                    {
                        "$set": {
                            "status": "responding",
                            "responding_guard_id": guard_id,
                            "responding_guard_name": guard_name,
                            "responding_at": datetime.utcnow(),
                        },
                        "$push": {
                            "action_history": {
                                "action": "responding",
                                "by": guard_name,
                                "guard_id": guard_id,
                                "source": "whatsapp",
                                "timestamp": datetime.utcnow(),
                            }
                        },
                    },
                )

        await _set_guard_activity_status(guard, "BUSY")
        await notify_admins(
            {
                "type": "STATUS_CHANGE",
                "guard_name": guard_name,
                "guard_id": guard_id,
                "status": "BUSY",
                "source": "WhatsApp",
                "alert_id": alert_id,
            }
        )

        buttons_sent, buttons_error = await asyncio.to_thread(
            _waha_send_incident_action_buttons,
            sender_digits,
            alert_id,
        )
        if not buttons_sent:
            await asyncio.to_thread(
                _waha_send_text,
                sender_digits,
                "You are marked as RESPONDING. Reply RESOLVED, NOT FOUND, or NEED HELP.",
            )

        return {
            "ok": True,
            "status": "alert_responding",
            "sender": sender_digits,
            "guard_id": guard_id,
            "alert_id": alert_id,
            "reply_sent": bool(buttons_sent),
            "reply_error": buttons_error,
        }

    if action_id == WAHA_ACTION_RESOLVED_BUTTON_ID:
        resolved = False
        resolved_state = "not_found"
        if alert_id:
            resolved, resolved_state = await _resolve_alert_in_db(alert_id, guard)

        if resolved_state == "already_resolved":
            sent, send_error = await asyncio.to_thread(
                _waha_send_text,
                sender_digits,
                "✅ This incident was already marked as RESOLVED.",
            )
            return {
                "ok": True,
                "status": "action_resolved_duplicate",
                "sender": sender_digits,
                "guard_id": guard_id,
                "alert_id": alert_id,
                "alert_updated": False,
                "reply_sent": bool(sent),
                "reply_error": send_error,
            }

        if resolved_state == "already_closed":
            sent, send_error = await asyncio.to_thread(
                _waha_send_text,
                sender_digits,
                "⚠️ This incident is already closed and cannot be marked RESOLVED again.",
            )
            return {
                "ok": True,
                "status": "action_resolved_already_closed",
                "sender": sender_digits,
                "guard_id": guard_id,
                "alert_id": alert_id,
                "alert_updated": False,
                "reply_sent": bool(sent),
                "reply_error": send_error,
            }

        if not resolved:
            sent, send_error = await asyncio.to_thread(
                _waha_send_text,
                sender_digits,
                "No active incident was found to mark as RESOLVED.",
            )
            return {
                "ok": True,
                "status": "action_resolved_no_active_alert",
                "sender": sender_digits,
                "guard_id": guard_id,
                "alert_id": alert_id,
                "alert_updated": False,
                "reply_sent": bool(sent),
                "reply_error": send_error,
            }

        await _set_guard_activity_status(guard, "ON_DUTY")
        if not bool(guard.get("isOnDuty", False)):
            await _set_guard_duty_flag(guard, True)
            await _create_duty_log(guard, datetime.utcnow())

        await _notify_admin_incident_update(
            event_type="ALERT_STATUS_UPDATE",
            status="RESOLVED",
            guard_name=guard_name,
            guard_id=guard_id,
            alert_id=alert_id,
            location=alert_location,
        )

        sent, send_error = await asyncio.to_thread(
            _waha_send_text,
            sender_digits,
            "Great job. Alert cleared. You are back ON DUTY.",
        )
        return {
            "ok": True,
            "status": "action_resolved",
            "sender": sender_digits,
            "guard_id": guard_id,
            "alert_id": alert_id,
            "alert_updated": bool(resolved),
            "reply_sent": bool(sent),
            "reply_error": send_error,
        }

    if action_id == WAHA_ACTION_NOT_FOUND_BUTTON_ID:
        updated = False
        if alert_id:
            updated = await _append_alert_action(alert_id, "not_found", guard)

        await _set_guard_activity_status(guard, "ON_DUTY")
        await _notify_admin_incident_update(
            event_type="ALERT_STATUS_UPDATE",
            status="NOT_FOUND",
            guard_name=guard_name,
            guard_id=guard_id,
            alert_id=alert_id,
            location=alert_location,
        )

        sent, send_error = await asyncio.to_thread(
            _waha_send_text,
            sender_digits,
            "Update received: Not Found. Control room has been notified.",
        )
        return {
            "ok": True,
            "status": "action_not_found",
            "sender": sender_digits,
            "guard_id": guard_id,
            "alert_id": alert_id,
            "alert_updated": bool(updated),
            "reply_sent": bool(sent),
            "reply_error": send_error,
        }

    await _set_guard_activity_status(guard, "BUSY")
    if alert_id:
        await _append_alert_action(alert_id, "need_help", guard)

    await _notify_admin_incident_update(
        event_type="ALERT_ESCALATION",
        status="NEED_HELP",
        guard_name=guard_name,
        guard_id=guard_id,
        alert_id=alert_id,
        location=alert_location,
        priority="high",
    )

    peer_dispatches = await _notify_peer_guards_for_help(
        requesting_guard=guard,
        alert_id=alert_id,
        location=alert_location,
    )
    peer_sent_count = sum(1 for row in peer_dispatches if row.get("sent"))

    sent, send_error = await asyncio.to_thread(
        _waha_send_text,
        sender_digits,
        (
            "Help request sent. Control room and nearby on-duty guards have been notified. "
            f"Backup alerts delivered: {peer_sent_count}."
        ),
    )
    return {
        "ok": True,
        "status": "alert_need_help",
        "sender": sender_digits,
        "guard_id": guard_id,
        "alert_id": alert_id,
        "peer_backup_notified": int(peer_sent_count),
        "peer_backup_total": int(len(peer_dispatches)),
        "peer_backup_delivery": peer_dispatches,
        "reply_sent": bool(sent),
        "reply_error": send_error,
    }


@router.post("/webhook")
async def whatsapp_webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        return {"ok": False, "status": "invalid_json"}

    incoming = payload or {}
    waha_payload = incoming.get(
        "payload") if isinstance(incoming, dict) else {}
    if not isinstance(waha_payload, dict) or not waha_payload:
        # Some WAHA setups post message fields at root instead of payload wrapper.
        waha_payload = incoming if isinstance(incoming, dict) else {}

    message = waha_payload.get("message") if isinstance(
        waha_payload, dict) else None
    if not isinstance(message, dict) or not message:
        message = waha_payload if isinstance(waha_payload, dict) else {}

    if not isinstance(message, dict) or not message:
        return {
            "ok": True,
            "status": "ignored",
            "reason": "missing_message_payload",
        }

    # Strictly ignore outgoing echoes immediately to avoid duplicate auto-replies.
    if message.get("fromMe") == True or waha_payload.get("fromMe") == True:
        return {
            "ok": True,
            "status": "ignored",
            "reason": "from_me_echo",
        }

    event_type = str(
        incoming.get("event")
        or incoming.get("eventType")
        or incoming.get("type")
        or waha_payload.get("event")
        or waha_payload.get("eventType")
        or ""
    ).strip().lower()
    # WAHA event names vary across versions; accept known incoming message variants.
    if event_type and all(hint not in event_type for hint in WAHA_INCOMING_EVENT_HINTS):
        return {
            "ok": True,
            "status": "ignored",
            "reason": "non_message_event",
            "event_type": event_type or None,
        }

    candidates = _collect_command_candidates(message)
    if message is not waha_payload:
        for candidate in _collect_command_candidates(waha_payload):
            if candidate not in candidates:
                candidates.append(candidate)

    action_id, action_alert_id = _parse_action_button(candidates)
    duty_intent = _resolve_duty_intent(candidates)
    incident_intent = _resolve_incident_intent(candidates)
    has_interactive_command = bool(action_id) or duty_intent is not None

    message_type = str(
        message.get("type")
        or waha_payload.get("type")
        or ""
    ).strip().lower()
    is_location_payload = bool(
        message_type == "location"
        or isinstance(message.get("location"), dict)
        or isinstance(waha_payload.get("location"), dict)
    )
    has_text_payload = any(
        str(message.get(key) or "").strip()
        for key in ("body", "text", "conversation")
    )

    if message_type and message_type not in WAHA_ALLOWED_TEXT_MESSAGE_TYPES:
        if not has_interactive_command and not is_location_payload:
            return {
                "ok": True,
                "status": "ignored",
                "reason": "non_text_event",
                "message_type": message_type or None,
            }

    if not message_type and not has_text_payload and not has_interactive_command and not is_location_payload:
        return {
            "ok": True,
            "status": "ignored",
            "reason": "missing_text_payload",
        }

    if _is_duplicate_webhook_message(message):
        return {
            "ok": True,
            "status": "ignored",
            "reason": "duplicate_message",
        }

    sender_raw = str(
        message.get("from")
        or message.get("chatId")
        or message.get("author")
        or waha_payload.get("from")
        or waha_payload.get("chatId")
        or waha_payload.get("author")
        or ""
    ).strip()

    if not sender_raw:
        return {
            "ok": True,
            "status": "ignored",
            "reason": "missing_from",
        }

    sender_digits = _extract_sender_digits(sender_raw)
    if not sender_digits:
        return {
            "ok": True,
            "status": "ignored",
            "reason": "unusable_sender",
        }

    chat_allowed, chat_reason = _validate_guard_control_chat(
        incoming, message)
    if not chat_allowed:
        logger.info(
            "[WHATSAPP] ignored: invalid chat context sender=%s reason=%s",
            sender_digits,
            chat_reason,
        )
        return {
            "ok": True,
            "status": "ignored",
            "reason": chat_reason or "invalid_chat_context",
            "sender": sender_digits,
        }

    if not candidates and not is_location_payload:
        logger.info(
            "[WHATSAPP] ignored: no command payload sender=%s", sender_digits)
        return {
            "ok": True,
            "status": "ignored",
            "reason": "no_command_payload",
            "sender": sender_digits,
        }

    guard = await _find_guard_by_phone(sender_digits)
    if not guard:
        logger.info("[WHATSAPP] guard not found sender=%s", sender_digits)
        sent = False
        send_error = None
        if _should_send_guard_not_found_reply(sender_digits):
            sent, send_error = await asyncio.to_thread(
                _waha_send_text,
                sender_digits,
                "This number is not linked to a guard account. Contact admin to map your WhatsApp number.",
            )
        else:
            logger.info(
                "[WHATSAPP] muted guard_not_found reply sender=%s cooldown_sec=%s",
                sender_digits,
                GUARD_NOT_FOUND_REPLY_COOLDOWN_SEC,
            )
        return {
            "ok": True,
            "status": "guard_not_found",
            "sender": sender_digits,
            "reply_sent": bool(sent),
            "reply_error": send_error,
        }

    incoming_text = str(
        message.get("body")
        or message.get("text")
        or message.get("conversation")
        or ""
    )
    cleaned_text = incoming_text.strip().upper()

    if is_location_payload:
        latitude, longitude = _extract_location_coordinates(
            message, waha_payload)
        if latitude is None or longitude is None:
            return {
                "ok": True,
                "status": "ignored",
                "reason": "invalid_location_payload",
                "sender": sender_digits,
            }

        maps_url = f"http://maps.google.com/?q={latitude},{longitude}"
        related_alert_id = await _find_latest_active_alert_id_for_guard(guard, sender_digits)
        related_alert_location = "AI Camera"
        if related_alert_id:
            object_id = _as_object_id(related_alert_id)
            if object_id is not None:
                await _alerts_collection().update_one(
                    {"_id": object_id},
                    {
                        "$set": {
                            "backup_location_latitude": latitude,
                            "backup_location_longitude": longitude,
                            "backup_location_map_url": maps_url,
                            "backup_location_updated_at": datetime.utcnow(),
                        },
                        "$push": {
                            "action_history": {
                                "action": "guard_location_shared",
                                "by": str(guard.get("full_name") or "Security Guard"),
                                "guard_id": str(guard.get("_id") or ""),
                                "source": "whatsapp",
                                "timestamp": datetime.utcnow(),
                                "map_url": maps_url,
                            }
                        },
                    },
                )
                latest_alert = await _alerts_collection().find_one(
                    {"_id": object_id},
                    {"location": 1},
                )
                if latest_alert:
                    related_alert_location = _extract_alert_location(
                        latest_alert)

        print(f"🚨 OFFICER NEEDS BACKUP AT: {maps_url}")
        peer_location_dispatches = await _notify_peer_guards_with_live_location(
            requesting_guard=guard,
            alert_id=related_alert_id,
            location=related_alert_location,
            maps_url=maps_url,
        )
        peer_location_sent_count = sum(
            1 for row in peer_location_dispatches if row.get("sent")
        )

        sent, send_error = await asyncio.to_thread(
            _waha_send_text,
            sender_digits,
            f"✅ Location received. Control room has your live location: {maps_url}",
        )
        return {
            "ok": True,
            "status": "location_received",
            "sender": sender_digits,
            "guard_id": str(guard.get("_id") or ""),
            "alert_id": related_alert_id,
            "maps_url": maps_url,
            "peer_location_notified": int(peer_location_sent_count),
            "peer_location_total": int(len(peer_location_dispatches)),
            "peer_location_delivery": peer_location_dispatches,
            "reply_sent": bool(sent),
            "reply_error": send_error,
        }

    if cleaned_text == "HELP":
        return await _mark_help_requested_and_prompt_location(
            guard=guard,
            sender_digits=sender_digits,
        )

    if action_id:
        logger.info(
            "[WHATSAPP] action button sender=%s action=%s alert_id=%s",
            sender_digits,
            action_id,
            action_alert_id,
        )
        return await _handle_action_button(
            action_id=action_id,
            action_alert_id=action_alert_id,
            guard=guard,
            sender_digits=sender_digits,
        )

    if incident_intent == "NOT_FOUND":
        return await _handle_action_button(
            action_id=WAHA_ACTION_NOT_FOUND_BUTTON_ID,
            action_alert_id=None,
            guard=guard,
            sender_digits=sender_digits,
        )

    if incident_intent == "NEED_HELP":
        return await _handle_action_button(
            action_id=WAHA_ALERT_NEED_HELP_BUTTON_ID,
            action_alert_id=None,
            guard=guard,
            sender_digits=sender_digits,
        )

    if cleaned_text in {"RESPONDING", "SAFE"}:
        acknowledged, acknowledged_alert_id = await _acknowledge_lockdown_from_text(
            guard=guard,
            sender_digits=sender_digits,
            command=cleaned_text,
        )
        if acknowledged:
            sent, send_error = await asyncio.to_thread(
                _waha_send_text,
                sender_digits,
                "✅ Lockdown acknowledgment received. Continue campus safety protocol.",
            )
            return {
                "ok": True,
                "status": "lockdown_acknowledged",
                "sender": sender_digits,
                "guard_id": str(guard.get("_id") or ""),
                "alert_id": acknowledged_alert_id,
                "reply_sent": bool(sent),
                "reply_error": send_error,
            }

    text = cleaned_text
    if text == "SAFE" or incident_intent == "SAFE":
        return await _handle_incident_text_command(
            guard=guard,
            sender_digits=sender_digits,
            command="SAFE",
        )

    if text == "RESOLVED" or incident_intent == "RESOLVED":
        return await _handle_incident_text_command(
            guard=guard,
            sender_digits=sender_digits,
            command="RESOLVED",
        )

    field_update_note = _extract_guard_field_update(incoming_text)
    if field_update_note is not None:
        return await _handle_guard_field_update_command(
            guard=guard,
            sender_digits=sender_digits,
            note=field_update_note,
        )

    guard_name = str(guard.get("full_name")
                     or "Security Guard").strip() or "Security Guard"

    intent = duty_intent
    if intent is None:
        logger.info("[WHATSAPP] ignored: no duty intent sender=%s candidates=%s",
                    sender_digits, candidates[:5])
        return {
            "ok": True,
            "status": "ignored",
            "reason": "no_duty_command",
            "sender": sender_digits,
            "candidates": candidates[:5],
        }

    wants_out = intent == "off"

    is_currently_on_duty = bool(guard.get("isOnDuty", False))

    if wants_out:
        logger.info("[WHATSAPP] duty command OFF sender=%s guard_id=%s",
                    sender_digits, str(guard.get("_id")))
        if not is_currently_on_duty:
            reconciled_closed_logs = await _close_duty_log(guard, datetime.utcnow())
            reply_text = _build_duty_status_message(guard_name, "OFF")
            sent, send_error = await asyncio.to_thread(
                _waha_send_text,
                sender_digits,
                reply_text,
            )
            duty_buttons_sent, duty_buttons_error = await asyncio.to_thread(
                _waha_send_duty_control_buttons,
                sender_digits,
            )
            return {
                "ok": True,
                "status": "already_off_duty",
                "sender": sender_digits,
                "guard_id": str(guard.get("_id")),
                "reply_sent": bool(sent),
                "reply_error": send_error,
                "duty_buttons_sent": bool(duty_buttons_sent),
                "duty_buttons_error": duty_buttons_error,
                "closed_duty_logs": int(reconciled_closed_logs or 0),
            }

        await _set_guard_duty_flag(guard, False)
        closed_logs = await _close_duty_log(guard, datetime.utcnow())
        await _insert_whatsapp_duty_event(guard, "OFF_DUTY")
        reply_text = _build_duty_status_message(guard_name, "OFF")
        state = "clocked_out"
        admin_status = "OFF DUTY"
    else:
        logger.info("[WHATSAPP] duty command ON sender=%s guard_id=%s",
                    sender_digits, str(guard.get("_id")))
        if is_currently_on_duty:
            # Keep data consistent: ensure an open session row exists while guard is on duty.
            await _create_duty_log(guard, datetime.utcnow())
            reply_text = _build_duty_status_message(guard_name, "ON")
            sent, send_error = await asyncio.to_thread(
                _waha_send_text,
                sender_digits,
                reply_text,
            )
            duty_buttons_sent, duty_buttons_error = await asyncio.to_thread(
                _waha_send_duty_control_buttons,
                sender_digits,
            )
            return {
                "ok": True,
                "status": "already_on_duty",
                "sender": sender_digits,
                "guard_id": str(guard.get("_id")),
                "reply_sent": bool(sent),
                "reply_error": send_error,
                "duty_buttons_sent": bool(duty_buttons_sent),
                "duty_buttons_error": duty_buttons_error,
                "closed_duty_logs": 0,
            }

        await _set_guard_duty_flag(guard, True)
        await _create_duty_log(guard, datetime.utcnow())
        await _insert_whatsapp_duty_event(guard, "ON_DUTY")
        closed_logs = 0
        reply_text = _build_duty_status_message(guard_name, "ON")
        state = "clocked_in"
        admin_status = "ON DUTY"

    await notify_admins(
        {
            "type": "STATUS_CHANGE",
            "guard_name": guard_name,
            "guard_id": str(guard.get("_id") or ""),
            "status": admin_status,
            "source": "WhatsApp",
        }
    )

    sent, send_error = await asyncio.to_thread(_waha_send_text, sender_digits, reply_text)
    duty_buttons_sent, duty_buttons_error = await asyncio.to_thread(
        _waha_send_duty_control_buttons,
        sender_digits,
    )

    return {
        "ok": True,
        "status": state,
        "sender": sender_digits,
        "guard_id": str(guard.get("_id")),
        "reply_sent": bool(sent),
        "reply_error": send_error,
        "duty_buttons_sent": bool(duty_buttons_sent),
        "duty_buttons_error": duty_buttons_error,
        "closed_duty_logs": int(closed_logs or 0),
    }
