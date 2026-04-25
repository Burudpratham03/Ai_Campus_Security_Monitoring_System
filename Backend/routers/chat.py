import asyncio
import base64
from datetime import datetime, timedelta, timezone
import json
import mimetypes
import os
from pathlib import Path
import time
import traceback
from typing import Any, Optional
import re

try:
    import google.generativeai as genai
except Exception:
    genai = None

from fastapi import APIRouter, File, Form, UploadFile

try:
    from ..database import get_db
    from ..utils.security import send_whatsapp
    from ..utils.guard_whatsapp_text import (
        build_guard_admin_instruction_message,
        normalize_guard_language,
    )
except ImportError:
    from database import get_db
    from utils.security import send_whatsapp
    from utils.guard_whatsapp_text import (
        build_guard_admin_instruction_message,
        normalize_guard_language,
    )


router = APIRouter(prefix="/chat", tags=["chatbot"])
if genai is not None:
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
else:
    print("[CHAT][GEMINI][CONFIG] google-generativeai is not installed; chatbot will run in fallback mode.")


def _resolve_gemini_timeout_sec() -> float:
    """Ensure Gemini timeout stays in a safe range for image-analysis workloads."""
    raw = os.getenv("GEMINI_TIMEOUT_SEC", "45")
    try:
        parsed = float(str(raw).strip())
    except Exception:
        print(
            f"[CHAT][GEMINI][CONFIG] Invalid GEMINI_TIMEOUT_SEC={raw!r}. Falling back to 45 seconds.")
        parsed = 45.0
    # Enforce a practical floor for image understanding requests.
    return max(30.0, parsed)


GEMINI_TIMEOUT_SEC = _resolve_gemini_timeout_sec()
GEMINI_TEXT_TIMEOUT_SEC = max(
    8.0,
    float(os.getenv("GEMINI_TEXT_TIMEOUT_SEC", "12")),
)
CHAT_ENDPOINT_TIMEOUT_SEC = max(
    8.0,
    float(os.getenv("CHAT_ENDPOINT_TIMEOUT_SEC", "25")),
)
GEMINI_MAX_MODEL_ATTEMPTS = max(
    1,
    int(os.getenv("GEMINI_MAX_MODEL_ATTEMPTS", "2")),
)
GEMINI_MODEL_CACHE_TTL_SEC = 600
_DISCOVERED_GENERATE_MODELS: list[str] | None = None
_DISCOVERED_MODELS_AT: datetime | None = None
GEMINI_MODEL_NAME: str | None = None
CAPTURES_DIR = Path(__file__).resolve().parent.parent / "captures"
MAX_STORED_IMAGES_FOR_CHAT = int(
    os.getenv("MAX_STORED_IMAGES_FOR_CHAT", "3").strip())
SUPPORTED_LANGUAGE_CODES = {"en", "hi", "mr"}
CHAT_RATE_LIMIT_PER_WINDOW = int(
    os.getenv("CHAT_RATE_LIMIT_PER_WINDOW", "25").strip())
CHAT_RATE_LIMIT_WINDOW_SEC = int(
    os.getenv("CHAT_RATE_LIMIT_WINDOW_SEC", "60").strip())
_chat_rate_limit_buckets: dict[str, list[float]] = {}


def get_users_collection():
    return get_db()["users"]


def get_alerts_collection():
    return get_db()["alerts"]


def get_guard_duty_collection():
    return get_db()["guard_duty"]


def get_guards_collection():
    return get_db()["users"]


def get_pending_broadcasts_collection():
    return get_db()["pending_broadcasts"]


def get_chat_logs_collection():
    return get_db()["chat_logs"]


def _normalize_language_code(language: str | None) -> str:
    code = str(language or "en").strip().lower()
    return code if code in SUPPORTED_LANGUAGE_CODES else "en"


def _chat_identity_key(email: str | None) -> str:
    normalized = str(email or "").strip().lower()
    return f"email:{normalized}" if normalized else "anonymous"


def _check_chat_rate_limit(identity_key: str) -> tuple[bool, int]:
    """Return (is_limited, retry_after_seconds) for chat requests."""
    now = time.monotonic()
    bucket = _chat_rate_limit_buckets.setdefault(identity_key, [])
    cutoff = now - max(1, CHAT_RATE_LIMIT_WINDOW_SEC)

    while bucket and bucket[0] < cutoff:
        bucket.pop(0)

    allowed_count = max(1, CHAT_RATE_LIMIT_PER_WINDOW)
    if len(bucket) >= allowed_count:
        retry_after = max(
            1, int(CHAT_RATE_LIMIT_WINDOW_SEC - (now - bucket[0])))
        return True, retry_after

    bucket.append(now)
    return False, 0


async def _is_verified_admin(email: str | None) -> bool:
    normalized_email = str(email or "").strip().lower()
    if not normalized_email:
        return False

    users = get_users_collection()
    admin_doc = await users.find_one(
        {
            "$or": [
                {"email": normalized_email},
                {"email_normalized": normalized_email},
            ],
            "role": "admin",
            "is_verified": True,
        }
    )
    return bool(admin_doc)


async def _log_chat_interaction(
    *,
    query: str,
    response_payload: dict[str, Any],
    email: str | None,
    language: str,
    has_image: bool,
    image_content_type: str | None,
    image_name: str | None,
) -> None:
    """Persist each chat turn for auditability and NLP training datasets."""
    try:
        chat_logs = get_chat_logs_collection()
        await chat_logs.insert_one(
            {
                "query": str(query or "").strip(),
                "response": str(response_payload.get("response") or "").strip(),
                "intent": str(response_payload.get("intent") or "unknown"),
                "source": str(response_payload.get("source") or "fallback"),
                "email": str(email or "").strip().lower() or None,
                "language": _normalize_language_code(language),
                "has_image": bool(has_image),
                "image_content_type": image_content_type,
                "image_name": image_name,
                "suggestions": response_payload.get("suggestions") or [],
                "created_at": datetime.now(timezone.utc),
            }
        )
    except Exception as exc:
        # Logging must never break the user chat flow.
        print(f"[CHAT][LOGGING] Failed to save chat interaction: {exc}")


async def save_draft_broadcast(email: str, message: str) -> str:
    """Upsert a pending WhatsApp broadcast draft for admin confirmation."""
    admin_email = str(email or "").strip().lower()
    draft_message = str(message or "").strip()
    if not admin_email:
        return "Cannot save draft because admin identity is missing."
    if not draft_message:
        return "Draft message is empty. Please provide a message to draft."

    pending = get_pending_broadcasts_collection()
    await pending.update_one(
        {"admin_email": admin_email},
        {
            "$set": {
                "admin_email": admin_email,
                "draft_message": draft_message,
                "updated_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )
    return (
        "Draft prepared successfully.\n"
        f"Message Draft: {draft_message}\n\n"
        "Should I send this to the active guards? (Yes/No)"
    )


async def get_and_clear_draft(email: str) -> str | None:
    """Fetch and delete pending broadcast draft for this admin."""
    admin_email = str(email or "").strip().lower()
    if not admin_email:
        return None

    pending = get_pending_broadcasts_collection()
    doc = await pending.find_one({"admin_email": admin_email})
    if not doc:
        return None

    await pending.delete_one({"_id": doc["_id"]})
    draft_message = str(doc.get("draft_message") or "").strip()
    return draft_message or None


def get_fire_protocol_response() -> str:
    return (
        "FIRE PROTOCOL:\n"
        "1. Activate the nearest fire alarm and notify security.\n"
        "2. Evacuate the building using the closest safe exit.\n"
        "3. Do NOT use elevators.\n"
        "4. Assemble at the designated muster point.\n"
        "5. Await instructions from campus security or emergency services."
    )


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        # Keep consistent timezone-aware output for model context.
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _serialize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize_value(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _normalize_query(query: str) -> str:
    normalized = (query or "").lower().strip()
    normalized = re.sub(r"[^a-z0-9+\s]", " ", normalized)
    normalized = " ".join(normalized.split())
    return normalized


def _contains_any(text: str, terms: set[str]) -> bool:
    for term in terms:
        escaped = re.escape(term.strip())
        if not escaped:
            continue
        # Match whole words/phrases to avoid false positives like "hi" in "this".
        if re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", text):
            return True
    return False


def _is_help_query(text: str) -> bool:
    return _contains_any(text, {"help", "support", "what can you do", "commands", "options"})


def _is_pending_alerts_query(text: str) -> bool:
    return _contains_any(
        text,
        {
            "pending alerts",
            "pending alert",
            "show pending alerts",
            "open alerts",
            "unresolved alerts",
        },
    )


def _is_latest_alert_query(text: str) -> bool:
    return _contains_any(
        text,
        {
            "latest alert",
            "last alert",
            "most recent alert",
            "newest alert",
        },
    )


def _is_recent_threats_query(text: str) -> bool:
    return _contains_any(
        text,
        {
            "recent threats",
            "threat summary",
            "incidents in last 24 hours",
            "alerts in last 24 hours",
        },
    )


def _is_on_duty_query(text: str) -> bool:
    return _contains_any(
        text,
        {
            "on duty guard count",
            "on-duty guard count",
            "who is on duty",
            "who is on-duty",
            "on duty guards",
            "on-duty guards",
        },
    )


def _is_my_duty_status_query(text: str) -> bool:
    return _contains_any(
        text,
        {
            "my duty status",
            "my shift status",
            "am i on duty",
            "duty status",
        },
    )


def _wants_full_context(text: str) -> bool:
    return _contains_any(
        text,
        {
            "all information",
            "all info",
            "all data",
            "database",
            "backend",
            "everything",
            "full details",
        },
    )


def _wants_stored_image_analysis(text: str) -> bool:
    return _contains_any(
        text,
        {
            "stored image",
            "stored images",
            "database image",
            "database images",
            "images in database",
            "images stored",
            "captured images",
            "saved images",
            "analyze images from database",
            "understand images in database",
        },
    )


def _is_explain_alert_query(text: str) -> bool:
    if _contains_any(
        text,
        {
            "explain alert",
            "explain the alert",
            "explain this alert",
            "alert explanation",
            "explain this image",
            "what happened in this alert",
            "summarize this alert",
        },
    ):
        return True

    return bool(
        re.search(r"(?<![a-z0-9])explain(?![a-z0-9])", text)
        and re.search(r"(?<![a-z0-9])(alert|event|detection)(?![a-z0-9])", text)
    )


def _to_simple_formal_paragraph(
    text: str,
    *,
    max_sentences: int = 3,
    max_chars: int = 360,
) -> str:
    """Normalize model output into one short, simple, formal paragraph."""
    raw = str(text or "").strip()
    if not raw:
        return "Alert explanation is currently unavailable."

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    normalized_lines: list[str] = []
    for line in lines:
        cleaned = re.sub(r"^\s*(?:[-*]\s+|\d+[.)]\s+|#+\s*)", "", line)
        if ":" in cleaned:
            left, right = cleaned.split(":", 1)
            if len(left.strip()) <= 32 and right.strip():
                cleaned = right.strip()
        normalized_lines.append(cleaned)

    merged = re.sub(r"\s+", " ", " ".join(normalized_lines)).strip()
    if not merged:
        return "Alert explanation is currently unavailable."

    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?।])\s+", merged)
        if sentence.strip()
    ]
    if sentences:
        merged = " ".join(sentences[: max(1, max_sentences)])

    if len(merged) > max_chars:
        clipped = merged[:max_chars].rsplit(" ", 1)[0].strip()
        merged = clipped or merged[:max_chars].strip()

    if merged and merged[-1] not in ".!?।":
        merged += "."

    return merged


async def lookup_user_by_phone(phone: str) -> Optional[dict]:
    users = get_users_collection()
    return await users.find_one({"phone_number": phone})


def get_system_status() -> str:
    # In a real implementation, this would check DB, camera stream health, etc.
    now = datetime.utcnow().isoformat() + "Z"
    return f"System status: Online. All monitored services are nominal as of {now}."


async def get_recent_threats() -> str:
    """Get summary of recent threats from captured data."""
    alerts = get_alerts_collection()

    # Get alerts from last 24 hours
    yesterday = datetime.utcnow() - timedelta(hours=24)
    recent = await alerts.find({
        "timestamp": {"$gte": yesterday}
    }).to_list(length=100)

    if not recent:
        return (
            "Threat Summary (Last 24 Hours)\n"
            "- Total Incidents: 0\n"
            "- Details: No threats were detected in the last 24 hours."
        )

    weapon_count = sum(1 for a in recent if a.get("type") == "weapon")
    violence_count = sum(1 for a in recent if a.get("type") == "violence")
    fire_count = sum(1 for a in recent if a.get("type") == "fire")

    return (
        "Threat Summary (Last 24 Hours)\n"
        f"- Total Incidents: {len(recent)}\n"
        f"- Weapon: {weapon_count}\n"
        f"- Violence: {violence_count}\n"
        f"- Fire: {fire_count}"
    )


async def get_pending_alerts_summary() -> str:
    alerts = get_alerts_collection()
    pending = await alerts.find({"status": "pending"}).to_list(length=200)

    if not pending:
        return (
            "Live Alerts (Pending)\n"
            "- Total Pending: 0\n"
            "- Status: No pending alerts at the moment."
        )

    weapon_count = sum(1 for a in pending if a.get("type") == "weapon")
    violence_count = sum(1 for a in pending if a.get("type") == "violence")
    fire_count = sum(1 for a in pending if a.get("type") == "fire")
    anomaly_count = sum(1 for a in pending if a.get("type") == "anomaly")

    return (
        "Live Alerts (Pending)\n"
        f"- Total Pending: {len(pending)}\n"
        f"- Weapon: {weapon_count}\n"
        f"- Violence: {violence_count}\n"
        f"- Fire: {fire_count}\n"
        f"- Anomaly: {anomaly_count}"
    )


async def get_latest_alert_summary() -> str:
    alerts = get_alerts_collection()
    latest = await alerts.find_one(sort=[("timestamp", -1)])

    if not latest:
        return (
            "Latest Live Alert\n"
            "- Status: No alert records were found."
        )

    alert_type = str(latest.get("type") or "unknown").lower()
    subtype = str(latest.get("subtype") or "general")
    confidence = round(float(latest.get("confidence") or 0.0) * 100, 2)
    status = str(latest.get("status") or "pending")
    ts = latest.get("timestamp")
    ts_text = ts.isoformat() if ts else "unknown"

    return (
        "Latest Live Alert\n"
        f"- Type: {alert_type}\n"
        f"- Class: {subtype}\n"
        f"- Confidence: {confidence}%\n"
        f"- Status: {status}\n"
        f"- Time: {ts_text}"
    )


async def get_latest_alert_confidence_explanation() -> str:
    """Return a short, formal paragraph explaining the latest alert confidence."""
    alerts = get_alerts_collection()
    latest = await alerts.find_one(sort=[("timestamp", -1)])

    if not latest:
        return (
            "No recent alert record is available, so a confidence explanation cannot be provided at this time."
        )

    alert_type = str(latest.get("type") or "unknown").lower()
    subtype = str(latest.get("subtype") or "general").lower()
    confidence_pct = round(float(latest.get("confidence") or 0.0) * 100, 2)
    status = str(latest.get("status") or "pending").lower()

    if confidence_pct >= 85:
        certainty = "high"
    elif confidence_pct >= 60:
        certainty = "moderate"
    else:
        certainty = "limited"

    return (
        f"The latest alert is classified as {alert_type} ({subtype}) with a confidence score of {confidence_pct}%, "
        f"which indicates {certainty} AI certainty for this detection. The alert is currently marked as {status}, "
        "and this score should be treated as a decision-support signal that must be confirmed with live camera context and guard review."
    )


async def get_guard_duty_info(email: str) -> str:
    """Get guard's current duty status and statistics."""
    duty = get_guard_duty_collection()

    # Check current shift
    active_shift = await duty.find_one({
        "email": email,
        "logout_time": None
    })

    if not active_shift:
        # Get last shift
        last_shift = await duty.find_one(
            {"email": email, "logout_time": {"$ne": None}},
            sort=[("logout_time", -1)]
        )

        if not last_shift:
            return f"Duty status: No duty records were found for {email}."

        duration = last_shift.get("duration_minutes", 0)
        return f"Duty status: Off duty. Last completed shift duration={duration / 60:.1f} hours."

    # Calculate current shift duration
    now = datetime.utcnow()
    duration = (now - active_shift["login_time"]).total_seconds() / 60
    hours = int(duration // 60)
    minutes = int(duration % 60)

    alerts_handled = len(active_shift.get("alerts_handled", []))

    return f"Duty status: On duty for {hours}h {minutes}m. Threats handled={alerts_handled}."


def _normalize_phone_digits(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


async def _resolve_guard_identity_by_email(email: str | None) -> tuple[str | None, str]:
    """Resolve guard identity fields for exclusion checks in duty summaries."""
    normalized_email = str(email or "").strip().lower()
    if not normalized_email:
        return None, ""

    users = get_users_collection()
    guard = await users.find_one(
        {
            "$or": [
                {"email": normalized_email},
                {"email_normalized": normalized_email},
            ],
            "role": "guard",
        },
        {"_id": 1, "phone_number": 1},
    )
    if not guard:
        return None, ""

    return str(guard.get("_id") or "") or None, _normalize_phone_digits(guard.get("phone_number"))


async def _get_report_aligned_on_duty_rows(limit: int = 500) -> list[dict[str, Any]] | None:
    """
    Fetch active duty rows using the same source used by Reports.
    Returns None when the report source is unavailable.
    """
    try:
        try:
            from .reports import duty_logs as get_report_duty_logs
        except ImportError:
            from reports import duty_logs as get_report_duty_logs

        rows = await get_report_duty_logs(limit=limit, include_history=False)
        if not isinstance(rows, list):
            return []

        return [row for row in rows if isinstance(row, dict) and not row.get("checkOutTime")]
    except Exception as exc:
        print(f"[CHAT] Failed to read report-aligned duty logs: {exc}")
        return None


async def get_on_duty_guard_summary(exclude_email: str | None = None) -> str:
    """Return a compact summary of on-duty guards, optionally excluding caller."""
    active = await _get_report_aligned_on_duty_rows(limit=500)

    # Safety fallback: preserve chatbot availability even if reports query fails.
    if active is None:
        duty = get_guard_duty_collection()
        legacy_rows = await duty.find({"logout_time": None}).sort("login_time", 1).to_list(length=200)
        active = [
            {
                "guardId": str(doc.get("guard_id") or doc.get("guardId") or ""),
                "guardName": doc.get("guard_name"),
                "email": doc.get("email"),
                "phone_number": doc.get("phone_number"),
            }
            for doc in legacy_rows
        ]

    normalized_exclude = str(exclude_email or "").strip().lower()
    exclude_guard_id, exclude_phone = await _resolve_guard_identity_by_email(normalized_exclude)
    if normalized_exclude:
        active = [
            row
            for row in active
            if str(row.get("email") or "").strip().lower() != normalized_exclude
            and (not exclude_guard_id or str(row.get("guardId") or "") != exclude_guard_id)
            and (not exclude_phone or _normalize_phone_digits(row.get("phone_number")) != exclude_phone)
        ]

    if not active:
        if normalized_exclude:
            return "On-duty guards: 0 (excluding you). No other guards are currently clocked in."
        return "On-duty guards: 0. No guards are currently clocked in."

    names: list[str] = []
    for row in active[:6]:
        label = (
            row.get("guardName")
            or row.get("guard_name")
            or row.get("email")
            or row.get("phone_number")
            or "Unknown"
        ).strip()
        names.append(label)

    names_text = ", ".join(names)
    more = len(active) - len(names)
    if more > 0:
        names_text = f"{names_text} (+{more} more)"

    if normalized_exclude:
        return f"On-duty guards: {len(active)} (excluding you). Active now: {names_text}."
    return f"On-duty guards: {len(active)}. Active now: {names_text}."


def _extract_admin_instruction(raw_query: str) -> str | None:
    """Parse admin instruction text from command-style prompts."""
    if not raw_query:
        return None

    lowered = raw_query.lower().strip()
    prefixes = [
        "broadcast to on-duty guards:",
        "broadcast instruction:",
        "instruction to guards:",
        "send instruction:",
        "notify guards:",
    ]
    for p in prefixes:
        if lowered.startswith(p):
            return raw_query[len(p):].strip()

    return None


async def _send_admin_instruction_to_on_duty_guards(instruction: str, admin_email: str | None = None) -> dict[str, Any]:
    """Deliver admin instruction to all on-duty guards via WhatsApp in real time."""
    if not await _is_verified_admin(admin_email):
        return {
            "sent": 0,
            "failed": 0,
            "total_targets": 0,
            "message": "Permission denied. Only verified administrators can dispatch guard instructions.",
        }

    db = get_db()
    guards_col = get_guards_collection()
    notifications_col = db["guard_notifications"]

    recipients: list[dict[str, Any]] = []
    # Read-only recipient selection for broadcast; no duty-state writes here.
    cursor = guards_col.find(
        {
            "role": "guard",
            "is_verified": True,
            "isOnDuty": True,
            "whatsapp_enabled": True,
        }
    )
    async for guard in cursor:
        if not guard.get("phone_number"):
            continue
        recipients.append(
            {
                "guard_id": str(guard.get("_id")),
                "guard_name": guard.get("full_name") or _normalize_phone_digits(guard.get("phone_number")),
                "email": guard.get("email"),
                "phone_number": guard.get("phone_number"),
                "preferred_language": normalize_guard_language(
                    guard.get("preferred_language")
                ),
            }
        )

    if not recipients:
        return {
            "sent": 0,
            "failed": 0,
            "total_targets": 0,
            "message": "No on-duty guards available. Instruction was not sent.",
        }

    timestamp = datetime.now(timezone.utc).strftime("%d-%m-%Y %I:%M:%S %p UTC")

    sent = 0
    failed = 0
    for recipient in recipients:
        preferred_language = normalize_guard_language(
            recipient.get("preferred_language")
        )
        message = build_guard_admin_instruction_message(
            instruction=instruction,
            admin_email=admin_email,
            timestamp=timestamp,
            language=preferred_language,
        )

        delivered = False
        failure_reason: str | None = None
        try:
            delivered = await asyncio.to_thread(
                send_whatsapp,
                recipient["phone_number"],
                message,
            )
        except Exception as exc:
            failure_reason = str(exc)

        if delivered:
            sent += 1
        else:
            failed += 1

        await notifications_col.insert_one(
            {
                "guard_id": recipient.get("guard_id"),
                "guard_name": recipient.get("guard_name"),
                "email": recipient.get("email"),
                "phone_number": recipient.get("phone_number"),
                "alert_id": None,
                "alert_type": "admin_instruction",
                "subtype": "manual_dispatch",
                "confidence": None,
                "frame_path": None,
                "location": "Command Center",
                "message": message,
                "language": preferred_language,
                "delivery_status": "sent" if delivered else "failed",
                "failure_reason": failure_reason,
                "ack_status": "pending",
                "created_at": datetime.now(timezone.utc),
                "instruction_by": admin_email,
            }
        )

    return {
        "sent": sent,
        "failed": failed,
        "total_targets": len(recipients),
        "message": f"Instruction dispatched to {sent}/{len(recipients)} on-duty guards in real time.",
    }


async def _build_security_context(email: str | None, include_full: bool = False) -> dict[str, Any]:
    db = get_db()
    alerts_col = get_alerts_collection()
    duty_col = get_guard_duty_collection()
    settings_col = db["settings"]

    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)

    recent_alerts_task = alerts_col.find(
        {"timestamp": {"$gte": since_24h}},
        sort=[("timestamp", -1)],
    ).to_list(length=120)
    pending_alerts_task = alerts_col.find(
        {"status": "pending"},
        sort=[("timestamp", -1)],
    ).to_list(length=80)
    latest_alert_task = alerts_col.find_one(sort=[("timestamp", -1)])
    active_guards_task = duty_col.find(
        {"logout_time": None}).to_list(length=60)
    settings_task = settings_col.find_one({})

    recent_alerts, pending_alerts, latest_alert, active_guards, settings = await asyncio.gather(
        recent_alerts_task,
        pending_alerts_task,
        latest_alert_task,
        active_guards_task,
        settings_task,
    )

    by_type_24h: dict[str, int] = {"weapon": 0,
                                   "violence": 0, "fire": 0, "anomaly": 0}
    for a in recent_alerts:
        key = str(a.get("type") or "unknown").lower()
        by_type_24h[key] = by_type_24h.get(key, 0) + 1

    context: dict[str, Any] = {
        "generated_at": now.isoformat(),
        "summary": {
            "recent_24h_total": len(recent_alerts),
            "pending_total": len(pending_alerts),
            "active_guard_count": len(active_guards),
            "alerts_by_type_24h": by_type_24h,
        },
        "settings": _serialize_value(
            {
                "detection_threshold": (settings or {}).get("detection_threshold"),
                "weapon_cooldown_seconds": (settings or {}).get("weapon_cooldown_seconds"),
                "preferred_language": (settings or {}).get("preferred_language"),
            }
        ),
        "latest_alert": _serialize_value(latest_alert or {}),
        "active_guards": _serialize_value(
            [
                {
                    "email": g.get("email"),
                    "phone_number": g.get("phone_number") or g.get("phone"),
                    "login_time": g.get("login_time"),
                }
                for g in active_guards
            ]
        ),
        "backend_capabilities": {
            "detection_types": ["weapon", "violence", "fire", "anomaly"],
            "chat_features": [
                "threat summary",
                "pending alerts",
                "latest alert",
                "duty status",
                "image-based detection diagnostics",
            ],
        },
        "request_user": email,
    }

    if include_full:
        # Keep payload bounded to avoid very large prompts while still sharing broad DB state.
        users = await db["users"].find({}, sort=[("_id", -1)]).to_list(length=100)
        guards = await db["users"].find({"role": "guard"}, sort=[("_id", -1)]).to_list(length=100)
        duty_recent = await duty_col.find({}, sort=[("login_time", -1)]).to_list(length=200)
        alerts_recent = await alerts_col.find({}, sort=[("timestamp", -1)]).to_list(length=300)
        reports_recent = await db["reports"].find({}, sort=[("created_at", -1)]).to_list(length=100)
        context["database_snapshot"] = _serialize_value(
            {
                "limits": {
                    "users": 100,
                    "guards": 100,
                    "guard_duty": 200,
                    "alerts": 300,
                    "reports": 100,
                },
                "users": users,
                "guards": guards,
                "guard_duty": duty_recent,
                "alerts": alerts_recent,
                "reports": reports_recent,
            }
        )

    return _serialize_value(context)


def _extract_gemini_text(response_payload: dict[str, Any]) -> str | None:
    candidates = response_payload.get("candidates") or []
    if not candidates:
        return None
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    text_parts = [p.get("text", "") for p in parts if isinstance(p, dict)]
    combined = "\n".join(t for t in text_parts if t).strip()
    return combined or None


def _extract_gemini_function_call(response_payload: dict[str, Any]) -> dict[str, Any] | None:
    candidates = response_payload.get("candidates") or []
    if not candidates:
        return None
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    for part in parts:
        if not isinstance(part, dict):
            continue
        function_call = part.get("functionCall") or part.get("function_call")
        if isinstance(function_call, dict):
            return function_call
    return None


def _normalize_image_mime(mime_type: str | None) -> str:
    value = str(mime_type or "").strip().lower()
    if not value.startswith("image/"):
        return "image/jpeg"
    return value


def _build_sdk_image_part_from_bytes(image_data: bytes, mime_type: str | None) -> dict[str, Any]:
    return {
        "mime_type": _normalize_image_mime(mime_type),
        "data": image_data,
    }


def _build_sdk_image_part_from_base64(image_base64: str, mime_type: str | None) -> dict[str, Any]:
    # Validate that base64 payload is decodable before sending to Gemini.
    decoded = base64.b64decode(str(image_base64 or ""), validate=True)
    return _build_sdk_image_part_from_bytes(decoded, mime_type)


def _gemini_friendly_error_message(exc: Exception) -> str:
    raw = str(exc or "").lower()

    if "google-generativeai package is not installed" in raw:
        return "AI analysis mode is unavailable because Gemini dependencies are not installed in the active backend environment."

    if "gemini_api_key is not configured" in raw:
        return "AI analysis mode is unavailable because the backend AI key is not configured."

    if "401" in raw or "403" in raw or "permission" in raw or "api key" in raw:
        return "AI analysis mode is unavailable because the backend AI key was rejected. Please verify key validity and permissions."

    if "timeout" in raw or "timed out" in raw or "connection" in raw or "dns" in raw:
        return "AI analysis mode is temporarily unreachable due to network/API timeout."

    return "AI analysis mode is temporarily unavailable due to a backend AI service error."


def _default_suggestions() -> list[str]:
    return [
        "Pending alerts",
        "On-duty guard count",
        "Who is on duty",
        "Latest alert",
        "Recent threats",
        "Fire protocol",
        "Broadcast to on-duty guards: Proceed to Block A immediately",
        "Analyze stored images from database",
    ]


def _intent_suggestions(intent: str) -> list[str]:
    suggestions_by_intent: dict[str, list[str]] = {
        "pending_alerts": [
            "Show pending alerts by type",
            "On-duty guard count",
            "Latest alert",
            "Who is on duty",
        ],
        "latest_alert": [
            "Explain latest alert confidence",
            "Pending alerts",
            "Recent threats",
        ],
        "on_duty_summary": [
            "Pending alerts",
            "Latest alert",
            "Recent threats",
        ],
        "threat_analysis": [
            "Pending alerts",
            "Latest alert",
            "Fire protocol",
        ],
        "fire_protocol": [
            "Evacuation checklist",
            "Pending alerts",
            "Latest alert",
        ],
        "duty_status": [
            "Who is on duty",
            "On-duty guard count",
            "Broadcast to on-duty guards: Acknowledge status at Gate 2",
            "Pending alerts",
            "Latest alert",
        ],
        "fallback_error": [
            "Pending alerts",
            "On-duty guard count",
            "Latest alert",
            "Recent threats",
            "Fire protocol",
        ],
        "help": _default_suggestions(),
    }
    return suggestions_by_intent.get(intent, _default_suggestions())


def _with_suggestions(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach suggestion options for the frontend dropdown."""
    suggestions = payload.get("suggestions")
    if not isinstance(suggestions, list) or not suggestions:
        payload["suggestions"] = _intent_suggestions(
            str(payload.get("intent") or ""))
    return payload


def _discover_generate_models_sync() -> list[str]:
    if genai is None:
        return []

    discovered: list[str] = []
    for model in genai.list_models():
        methods = set(getattr(model, "supported_generation_methods", []) or [])
        if "generateContent" not in methods:
            continue
        model_name = str(getattr(model, "name", "") or "").strip()
        if model_name:
            discovered.append(model_name)
    return discovered


def _order_flash_first(models: list[str]) -> list[str]:
    flash_models = [m for m in models if "flash" in m.lower()]
    non_flash_models = [m for m in models if m not in flash_models]
    return flash_models + non_flash_models


def _initialize_gemini_model_name() -> str:
    global _DISCOVERED_GENERATE_MODELS, _DISCOVERED_MODELS_AT

    try:
        discovered = _discover_generate_models_sync()
        _DISCOVERED_GENERATE_MODELS = discovered
        _DISCOVERED_MODELS_AT = datetime.now(timezone.utc)
        ordered = _order_flash_first(discovered)
        if ordered:
            selected = ordered[0]
            print(f"[CHAT][GEMINI][INIT] selected model={selected}")
            return selected
    except Exception as exc:
        print(f"[CHAT][GEMINI][INIT_ERROR] {exc}")
        traceback.print_exc()

    # Last-resort fallback when model listing fails; still let runtime retries work.
    return "models/gemini-1.5-flash-latest"


def _get_runtime_model_candidates() -> list[str]:
    global _DISCOVERED_GENERATE_MODELS, _DISCOVERED_MODELS_AT, GEMINI_MODEL_NAME

    now = datetime.now(timezone.utc)
    should_refresh = (
        _DISCOVERED_GENERATE_MODELS is None
        or _DISCOVERED_MODELS_AT is None
        or (now - _DISCOVERED_MODELS_AT).total_seconds() > GEMINI_MODEL_CACHE_TTL_SEC
    )

    if should_refresh:
        try:
            _DISCOVERED_GENERATE_MODELS = _discover_generate_models_sync()
            _DISCOVERED_MODELS_AT = now
            print(
                "[CHAT][GEMINI][DISCOVERY] generateContent models="
                f"{_DISCOVERED_GENERATE_MODELS}"
            )
        except Exception as exc:
            print(f"[CHAT][GEMINI][DISCOVERY_ERROR] {exc}")
            traceback.print_exc()
            _DISCOVERED_GENERATE_MODELS = _DISCOVERED_GENERATE_MODELS or []

    ordered = _order_flash_first(list(_DISCOVERED_GENERATE_MODELS or []))

    if GEMINI_MODEL_NAME and GEMINI_MODEL_NAME in ordered:
        ordered = [GEMINI_MODEL_NAME] + \
            [m for m in ordered if m != GEMINI_MODEL_NAME]

    if ordered:
        return ordered

    if GEMINI_MODEL_NAME:
        return [GEMINI_MODEL_NAME]

    return ["models/gemini-1.5-flash-latest"]


GEMINI_MODEL_NAME = _initialize_gemini_model_name()


async def _build_gemini_fallback_response(exc: Exception) -> str:
    """Return a clearer fallback answer with immediate operational context."""
    reason = _gemini_friendly_error_message(exc)

    # Provide actionable live data so user still gets value when Gemini is down.
    try:
        pending = await get_pending_alerts_summary()
    except Exception:
        pending = "Pending alerts: unavailable right now."

    try:
        latest = await get_latest_alert_summary()
    except Exception:
        latest = "Latest alert: unavailable right now."

    try:
        recent = await get_recent_threats()
    except Exception:
        recent = "Threat summary (24h): unavailable right now."

    return (
        "Security Assistant - Operational Fallback\n"
        f"Status: {reason}\n\n"
        "Live Dashboard Data\n"
        f"1. {pending}\n"
        f"2. {latest}\n"
        f"3. {recent}\n\n"
        "You can continue with structured commands: pending alerts, latest alert, recent threats, fire protocol, duty status."
    )


async def _query_gemini(
    query: str,
    context: dict[str, Any],
    email: str | None,
    language: str,
    image_data: bytes | None,
    image_mime: str | None,
    extra_images: list[dict[str, Any]] | None = None,
    simple_formal_paragraph: bool = False,
) -> str:
    global GEMINI_MODEL_NAME

    if genai is None:
        raise RuntimeError(
            "google-generativeai package is not installed on backend")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[CHAT][GEMINI][CONFIG] GEMINI_API_KEY missing or empty in environment.")
        raise RuntimeError("GEMINI_API_KEY is not configured on backend")
    if api_key.lower().startswith("your_") or "changeme" in api_key.lower():
        print("[CHAT][GEMINI][CONFIG] GEMINI_API_KEY appears to be a placeholder value.")
        raise RuntimeError("GEMINI_API_KEY is not configured on backend")

    # Reconfigure per-call to avoid stale key state in long-running reload sessions.
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

    has_uploaded_image = image_data is not None
    stored_image_count = len(extra_images or [])

    system_text = (
        "You are GuardGPT, a professional campus security operations assistant for administrators and guards. "
        "Use only the provided context and user question; do not invent facts. "
        "Use a concise professional tone. Avoid slang, jokes, and emojis. "
        "Structure responses when useful as: Situation, Assessment, Recommended Actions. "
        "If data is missing, explicitly state what is missing. "
        "If an image is attached, analyze the visual content directly and provide concrete observations. "
        "When user asks why detection failed, include likely causes: low confidence, class mismatch, occlusion, blur, lighting, motion, model bias, threshold settings, frame skip, and camera angle. "
        "Provide actionable checks for admins. Keep default responses brief unless the user asks for detail. "
        "If responding in Hindi or Marathi, use native Devanagari script and never use Romanized transliteration. "
        f"Respond in language code '{_normalize_language_code(language)}'."
    )

    if simple_formal_paragraph:
        system_text += (
            " For alert explanation requests, respond as one short formal paragraph in very simple language. "
            "Use 2-3 sentences only. Do not use headings, bullets, or markdown."
        )

    context_text = json.dumps(context, ensure_ascii=True)
    user_text = (
        f"Image attached: {'yes' if has_uploaded_image else 'no'}\n"
        f"Stored evidence images attached: {stored_image_count}\n\n"
        "Context JSON:\n"
        f"{context_text}\n\n"
        "User question:\n"
        f"{query}\n\n"
        "Return a concise operational answer.\n"
        "If image attached is yes, include: what is visible, confidence cues, and why detection may have passed or failed."
    )

    if simple_formal_paragraph:
        user_text += "\nKeep the final answer to one short, formal paragraph in simple words."

    parts: list[Any] = [user_text]
    if image_data:
        parts.append(_build_sdk_image_part_from_bytes(image_data, image_mime))
    if extra_images:
        for img in extra_images:
            parts.append(
                (
                    "Stored evidence image metadata: "
                    f"type={img.get('type')} subtype={img.get('subtype')} "
                    f"confidence={img.get('confidence')} timestamp={img.get('timestamp')} "
                    f"frame_path={img.get('frame_path')}"
                )
            )
            try:
                parts.append(
                    _build_sdk_image_part_from_base64(
                        str(img.get("data") or ""),
                        str(img.get("mime_type") or "image/jpeg"),
                    )
                )
            except Exception as image_parse_error:
                print(
                    "[CHAT][GEMINI][IMAGE_FORMAT_ERROR] "
                    f"frame_path={img.get('frame_path')} mime={img.get('mime_type')} "
                    f"error={image_parse_error}"
                )

    request_timeout = GEMINI_TIMEOUT_SEC if (
        image_data or extra_images) else max(10.0, GEMINI_TEXT_TIMEOUT_SEC)

    response = None
    last_error: Exception | None = None
    candidates = _get_runtime_model_candidates()[:GEMINI_MAX_MODEL_ATTEMPTS]
    for model_name in candidates:
        try:
            model = genai.GenerativeModel(
                model_name,
                system_instruction=system_text,
            )
            response = await asyncio.to_thread(
                model.generate_content,
                parts,
                generation_config={
                    "temperature": 0.1,
                    "top_p": 0.9,
                    "max_output_tokens": 420,
                },
                request_options={"timeout": request_timeout},
            )
            GEMINI_MODEL_NAME = model_name
            print(f"[CHAT][GEMINI][MODEL_OK] model={model_name}")
            break
        except Exception as model_error:
            last_error = model_error
            print(
                f"[CHAT][GEMINI][MODEL_ERROR] model={model_name} "
                f"error={repr(model_error)}"
            )
            traceback.print_exc()

    if response is None:
        raise RuntimeError(
            "All Gemini model attempts failed. "
            f"Last error: {repr(last_error)}"
        )

    result: dict[str, Any] = {}
    if hasattr(response, "to_dict"):
        try:
            result = response.to_dict()
        except Exception:
            result = {}

    function_call = _extract_gemini_function_call(result)
    if function_call is not None:
        name = str(function_call.get("name") or "").strip()
        args = function_call.get("args") or {}
        if name == "save_draft_broadcast":
            message = str((args or {}).get("message") or "").strip()
            if not await _is_verified_admin(email):
                return "Only verified administrators can draft or send guard broadcast instructions."
            return await save_draft_broadcast(email or "", message)

    text = None
    if hasattr(response, "text"):
        try:
            text = response.text
        except Exception:
            text = None
    if not text:
        text = _extract_gemini_text(result)
    if not text:
        raise RuntimeError("Gemini returned no text response")
    return text


async def _load_recent_stored_images(limit: int) -> list[dict[str, Any]]:
    """Load recent capture images referenced by alerts for AI analysis."""
    alerts = get_alerts_collection()
    docs = await alerts.find(
        {"frame_path": {"$exists": True, "$nin": [None, ""]}},
        sort=[("timestamp", -1)],
    ).to_list(length=80)

    loaded: list[dict[str, Any]] = []
    for doc in docs:
        frame_path = str(doc.get("frame_path") or "").strip().lstrip("/\\")
        if not frame_path:
            continue

        full_path = (CAPTURES_DIR / frame_path).resolve()
        try:
            full_path.relative_to(CAPTURES_DIR.resolve())
        except Exception:
            continue

        if not full_path.is_file():
            continue

        try:
            raw = await asyncio.to_thread(full_path.read_bytes)
        except Exception:
            continue

        # Keep payload bounded for API reliability.
        if len(raw) > 4 * 1024 * 1024:
            continue

        mime_type = mimetypes.guess_type(str(full_path))[0] or "image/jpeg"
        loaded.append(
            {
                "data": base64.b64encode(raw).decode("ascii"),
                "mime_type": mime_type,
                "frame_path": frame_path,
                "type": str(doc.get("type") or "unknown"),
                "subtype": str(doc.get("subtype") or "general"),
                "confidence": float(doc.get("confidence") or 0.0),
                "timestamp": _serialize_value(doc.get("timestamp")),
            }
        )
        if len(loaded) >= max(1, limit):
            break

    return loaded


async def _chat_core(
    query: str,
    email: str | None,
    image: UploadFile | None,
    language: str | None,
):
    q = _normalize_query(query)
    normalized_email = str(email or "").strip().lower()
    normalized_language = _normalize_language_code(language)

    if not q:
        return _with_suggestions({
            "intent": "empty",
            "response": "Please enter a security operations question.",
            "source": "fallback",
        })

    identity_key = _chat_identity_key(normalized_email)
    is_limited, retry_after = _check_chat_rate_limit(identity_key)
    if is_limited:
        return _with_suggestions(
            {
                "intent": "rate_limited",
                "response": (
                    "Too many chat requests in a short time. "
                    f"Please wait about {retry_after} seconds and try again."
                ),
                "source": "fallback",
                "suggestions": [
                    "Pending alerts",
                    "Latest alert",
                    "On-duty guard count",
                ],
            }
        )

    is_verified_admin = await _is_verified_admin(normalized_email)

    # Fast path commands that should remain deterministic.
    if "fire protocol" in q or ("fire" in q and "protocol" in q):
        return _with_suggestions({"intent": "fire_protocol", "response": get_fire_protocol_response(), "source": "fallback"})

    yes_variants = {"yes", "yes send it", "send it", "approve"}
    no_variants = {"no", "cancel", "dont send", "don t send"}

    instruction = _extract_admin_instruction(query)
    if instruction:
        if not is_verified_admin:
            return _with_suggestions(
                {
                    "intent": "admin_permission_denied",
                    "response": "Only verified administrators can draft or send guard broadcast instructions.",
                    "source": "fallback",
                    "suggestions": [
                        "Pending alerts",
                        "Latest alert",
                        "On-duty guard count",
                    ],
                }
            )

        draft_response = await save_draft_broadcast(normalized_email, instruction)
        return _with_suggestions(
            {
                "intent": "instruction_draft",
                "response": draft_response,
                "source": "fallback",
            }
        )

    if q in yes_variants:
        if not is_verified_admin:
            return _with_suggestions({
                "intent": "instruction_approve_error",
                "response": "Only verified administrators can approve and dispatch guard broadcast instructions.",
                "source": "fallback",
            })

        draft_message = await get_and_clear_draft(normalized_email)
        if not draft_message:
            return _with_suggestions({
                "intent": "instruction_approve_error",
                "response": "No pending draft found to approve.",
                "source": "fallback",
            })

        dispatch_result = await _send_admin_instruction_to_on_duty_guards(draft_message, admin_email=normalized_email)
        return _with_suggestions({
            "intent": "instruction_approved",
            "response": (
                "Draft Approved and Dispatched\n"
                f"- Sent: {dispatch_result.get('sent', 0)}\n"
                f"- Failed: {dispatch_result.get('failed', 0)}\n"
                f"- Targets: {dispatch_result.get('total_targets', 0)}\n"
                f"- Status: {dispatch_result.get('message')}"
            ),
            "source": "fallback",
            "suggestions": [
                "On-duty guard count",
                "Pending alerts",
                "Latest alert",
            ],
        })

    if q in no_variants:
        if not is_verified_admin:
            return _with_suggestions({
                "intent": "instruction_cancel_error",
                "response": "Only verified administrators can cancel broadcast drafts.",
                "source": "fallback",
            })

        draft_message = await get_and_clear_draft(normalized_email)
        if draft_message:
            return _with_suggestions({
                "intent": "instruction_cancel",
                "response": "Draft cancelled. I will not send that message to active guards.",
                "source": "fallback",
            })
        return _with_suggestions({
            "intent": "instruction_cancel",
            "response": "No pending draft found to cancel.",
            "source": "fallback",
        })

    if "system status" in q or q == "status":
        return _with_suggestions({"intent": "system_status", "response": get_system_status(), "source": "fallback"})

    if _is_pending_alerts_query(q):
        return _with_suggestions({
            "intent": "pending_alerts",
            "response": await get_pending_alerts_summary(),
            "source": "fallback",
        })

    if _is_latest_alert_query(q) and _is_explain_alert_query(q):
        return _with_suggestions({
            "intent": "latest_alert_explained",
            "response": await get_latest_alert_confidence_explanation(),
            "source": "fallback",
        })

    if _is_latest_alert_query(q):
        return _with_suggestions({
            "intent": "latest_alert",
            "response": await get_latest_alert_summary(),
            "source": "fallback",
        })

    if _is_recent_threats_query(q):
        return _with_suggestions({
            "intent": "threat_analysis",
            "response": await get_recent_threats(),
            "source": "fallback",
        })

    if _is_on_duty_query(q):
        return _with_suggestions({
            "intent": "on_duty_summary",
            "response": await get_on_duty_guard_summary(exclude_email=normalized_email or None),
            "source": "fallback",
        })

    if _is_my_duty_status_query(q) and normalized_email:
        return _with_suggestions({
            "intent": "duty_status",
            "response": await get_guard_duty_info(normalized_email),
            "source": "fallback",
        })

    if q.startswith("who is "):
        phone = q.replace("who is", "", 1).strip()
        user = await lookup_user_by_phone(phone)
        if not user:
            return _with_suggestions({
                "intent": "user_lookup",
                "response": f"User lookup result: No user was found for phone number {phone}.",
                "source": "fallback",
            })
        return _with_suggestions({
            "intent": "user_lookup",
            "response": f"User lookup result: {user.get('full_name', 'Unknown Name')} ({user.get('email')}) is registered with phone {phone}.",
            "source": "fallback",
        })

    if _is_help_query(q):
        return _with_suggestions({
            "intent": "help",
            "response": (
                "Supported security queries: fire protocol, recent threats, pending alerts, latest alert, "
                "system status, duty status, who is <phone number>, and image-based detection analysis."
            ),
            "source": "fallback",
        })

    include_full = _wants_full_context(q)
    wants_stored_images = _wants_stored_image_analysis(q)
    wants_simple_explain = _is_explain_alert_query(q)
    context = await _build_security_context(email=email, include_full=include_full)

    image_bytes: bytes | None = None
    image_mime: str | None = None
    stored_images: list[dict[str, Any]] = []
    if image is not None:
        image_bytes = await image.read()
        image_mime = image.content_type or "image/jpeg"
    elif wants_stored_images:
        stored_images = await _load_recent_stored_images(MAX_STORED_IMAGES_FOR_CHAT)
        context["stored_images_loaded"] = len(stored_images)
        context["stored_image_paths"] = [
            img.get("frame_path") for img in stored_images]

    try:
        request_timeout = GEMINI_TIMEOUT_SEC if (
            image_bytes or stored_images) else max(8.0, GEMINI_TEXT_TIMEOUT_SEC)
        response_text = await asyncio.wait_for(
            _query_gemini(
                query=query,
                context=context,
                email=normalized_email,
                language=normalized_language,
                image_data=image_bytes,
                image_mime=image_mime,
                extra_images=stored_images,
                simple_formal_paragraph=wants_simple_explain,
            ),
            timeout=request_timeout + 2.0,
        )

        if wants_simple_explain:
            response_text = _to_simple_formal_paragraph(response_text)

        return _with_suggestions({
            "intent": "ai_response",
            "response": response_text,
            "source": "gemini",
            "context_mode": "full" if include_full else "summary",
            "stored_images_used": len(stored_images),
        })
    except Exception as gemini_error:
        print(f"[CHAT][GEMINI] {gemini_error}")
        traceback.print_exc()
        if wants_simple_explain:
            fallback_response = (
                "The alert explanation is temporarily unavailable because the AI service could not be reached. "
                "Please try again in a moment."
            )
        else:
            fallback_response = await _build_gemini_fallback_response(gemini_error)
        return _with_suggestions({
            "intent": "fallback_error",
            "response": fallback_response,
            "source": "fallback",
            "context_mode": "full" if include_full else "summary",
            "stored_images_used": len(stored_images),
        })


@router.get("/")
async def chat(query: str, email: str = None, language: str | None = None):
    try:
        result = await asyncio.wait_for(
            _chat_core(query=query, email=email,
                       image=None, language=language),
            timeout=CHAT_ENDPOINT_TIMEOUT_SEC,
        )
        await _log_chat_interaction(
            query=query,
            response_payload=result,
            email=email,
            language=language or "en",
            has_image=False,
            image_content_type=None,
            image_name=None,
        )
        return result
    except asyncio.TimeoutError:
        timeout_payload = _with_suggestions({
            "intent": "timeout",
            "response": (
                "Chat processing took too long and was safely stopped. "
                "Please retry with a shorter query or check backend load."
            ),
            "source": "fallback",
        })
        await _log_chat_interaction(
            query=query,
            response_payload=timeout_payload,
            email=email,
            language=language or "en",
            has_image=False,
            image_content_type=None,
            image_name=None,
        )
        return timeout_payload
    except Exception as e:
        print(f"[CHAT ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        error_payload = _with_suggestions({
            "intent": "error",
            "response": f"Error: {str(e)}. Please try again.",
            "source": "fallback",
        })
        await _log_chat_interaction(
            query=query,
            response_payload=error_payload,
            email=email,
            language=language or "en",
            has_image=False,
            image_content_type=None,
            image_name=None,
        )
        return error_payload


@router.post("/ask")
async def chat_ask(
    query: str = Form(...),
    email: str | None = Form(None),
    language: str | None = Form(None),
    image: UploadFile | None = File(None),
):
    try:
        result = await asyncio.wait_for(
            _chat_core(query=query, email=email,
                       image=image, language=language),
            timeout=CHAT_ENDPOINT_TIMEOUT_SEC,
        )
        await _log_chat_interaction(
            query=query,
            response_payload=result,
            email=email,
            language=language or "en",
            has_image=image is not None,
            image_content_type=image.content_type if image is not None else None,
            image_name=image.filename if image is not None else None,
        )
        return result
    except asyncio.TimeoutError:
        timeout_payload = _with_suggestions({
            "intent": "timeout",
            "response": (
                "Chat processing took too long and was safely stopped. "
                "Please retry with a shorter query or check backend load."
            ),
            "source": "fallback",
        })
        await _log_chat_interaction(
            query=query,
            response_payload=timeout_payload,
            email=email,
            language=language or "en",
            has_image=image is not None,
            image_content_type=image.content_type if image is not None else None,
            image_name=image.filename if image is not None else None,
        )
        return timeout_payload
    except Exception as e:
        print(f"[CHAT ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        error_payload = _with_suggestions({
            "intent": "error",
            "response": f"Error: {str(e)}. Please try again.",
            "source": "fallback",
        })
        await _log_chat_interaction(
            query=query,
            response_payload=error_payload,
            email=email,
            language=language or "en",
            has_image=image is not None,
            image_content_type=image.content_type if image is not None else None,
            image_name=image.filename if image is not None else None,
        )
        return error_payload
