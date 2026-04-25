import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Form
from bson import ObjectId
from pydantic import BaseModel, Field

try:
    from ..database import get_db, get_guards_collection
    from ..Models.schemas import LogbookEntry, DutyLogEntry
    from ..utils.identity_validation import normalize_phone, normalize_email
    from ..utils.security import send_whatsapp
    from ..utils.guard_whatsapp_text import normalize_guard_language, build_guard_duty_status_message
except ImportError:
    from database import get_db, get_guards_collection
    from Models.schemas import LogbookEntry, DutyLogEntry
    from utils.identity_validation import normalize_phone, normalize_email
    from utils.security import send_whatsapp
    from utils.guard_whatsapp_text import normalize_guard_language, build_guard_duty_status_message

router = APIRouter(prefix="/guard-duty", tags=["guard-duty"])


class GuardLanguagePreferencesRequest(BaseModel):
    phone_number: Optional[str] = Field(default=None, min_length=6)
    identifier: Optional[str] = Field(default=None)
    preferred_language: Optional[str] = Field(default=None)
    whatsapp_enabled: bool = Field(default=True)


def get_guard_duty_collection():
    """Get the guard_duty collection."""
    return get_db()["guard_duty"]


def get_duty_logs_collection():
    """Get the duty_logs collection."""
    return get_db()["duty_logs"]


def get_alerts_collection():
    """Get the alerts collection."""
    return get_db()["alerts"]


async def _find_guard(*, email: Optional[str] = None, phone_number: Optional[str] = None) -> Optional[dict]:
    guards = get_guards_collection()
    normalized_phone = normalize_phone(phone_number)
    if normalized_phone:
        guard = await guards.find_one({"phone_normalized": normalized_phone, "role": "guard"})
        if guard:
            return guard

    normalized_email = normalize_email(email)
    if normalized_email:
        guard = await guards.find_one({"email_normalized": normalized_email, "role": "guard"})
        if guard:
            return guard

    return None


def _guard_active_query(guard: dict) -> dict:
    return {
        "guard_id": str(guard.get("_id")),
        "logout_time": None,
    }


def _guard_active_query_with_identity(guard: dict) -> dict:
    """Match open duty records for this guard using id plus identity fallbacks.

    Older rows may have missing guard_id, so include normalized phone/email to
    ensure logout closes all currently-open sessions for the same person.
    """
    identity_filters: list[dict] = [{"guard_id": str(guard.get("_id"))}]

    normalized_phone = normalize_phone(guard.get("phone_number"))
    normalized_email = normalize_email(guard.get("email"))

    if normalized_phone:
        identity_filters.append({"phone_normalized": normalized_phone})
    if normalized_email:
        identity_filters.append({"email_normalized": normalized_email})

    return {
        "logout_time": None,
        "$or": identity_filters,
    }


def _fallback_active_query(email: Optional[str], phone_number: Optional[str]) -> Optional[dict]:
    normalized_email = normalize_email(email)
    normalized_phone = normalize_phone(phone_number)
    identity_filters: list[dict] = []

    if normalized_phone:
        identity_filters.append({"phone_normalized": normalized_phone})
    if normalized_email:
        identity_filters.append({"email_normalized": normalized_email})

    if not identity_filters:
        return None

    return {
        "logout_time": None,
        "$or": identity_filters,
    }


def _fallback_guard_name(email: Optional[str], phone_number: Optional[str]) -> str:
    if email and "@" in email:
        return email.split("@")[0]
    if phone_number:
        return f"Guard {str(phone_number)[-4:]}"
    return "Security Personnel"


async def _set_guard_duty_flag(guard: Optional[dict], is_on_duty: bool) -> None:
    if not guard:
        return
    guards = get_guards_collection()
    await guards.update_one(
        {"_id": guard["_id"]},
        {"$set": {"isOnDuty": bool(
            is_on_duty), "duty_updated_at": datetime.utcnow()}},
    )


async def _send_duty_status_notification(guard: Optional[dict], is_on_duty: bool) -> None:
    if not guard:
        return

    phone = normalize_phone(guard.get("phone_number"))
    if not phone:
        return

    if not bool(guard.get("whatsapp_enabled", True)):
        return

    language = normalize_guard_language(
        guard.get("preferred_language")
        or (guard.get("settings") or {}).get("preferred_language")
    )
    timestamp = (datetime.utcnow() + timedelta(hours=5, minutes=30)
                 ).strftime("%Y-%m-%d %H:%M:%S IST")
    message = build_guard_duty_status_message(
        is_on_duty=is_on_duty,
        full_name=guard.get("full_name"),
        language=language,
        timestamp=timestamp,
    )

    try:
        await asyncio.to_thread(send_whatsapp, phone, message)
    except Exception as exc:
        print(
            f"[GUARD_DUTY][WHATSAPP] Failed to send duty status message: {exc}")


async def _create_duty_log(guard: Optional[dict], check_in_time: datetime) -> None:
    if not guard:
        return
    duty_logs = get_duty_logs_collection()

    # Prevent duplicate open log rows for the same guard.
    existing_open = await duty_logs.find_one(
        {
            "guardId": str(guard.get("_id")),
            "checkOutTime": None,
            "checkInTime": {"$exists": True},
            "$or": [
                {"log_type": {"$exists": False}},
                {"log_type": "session"},
            ],
        },
        sort=[("checkInTime", -1)],
    )
    if existing_open:
        return

    doc = DutyLogEntry(
        guardId=str(guard.get("_id")),
        checkInTime=check_in_time,
        checkOutTime=None,
        totalAlertsReceived=0,
    )
    payload = doc.dict()
    payload["log_type"] = "session"
    await duty_logs.insert_one(payload)


async def _close_duty_log(guard: Optional[dict], check_out_time: datetime) -> int:
    if not guard:
        return 0
    duty_logs = get_duty_logs_collection()
    result = await duty_logs.update_many(
        {
            "guardId": str(guard.get("_id")),
            "checkOutTime": None,
            "checkInTime": {"$exists": True},
            "$or": [
                {"log_type": {"$exists": False}},
                {"log_type": "session"},
            ],
        },
        {
            "$set": {
                "checkOutTime": check_out_time,
            }
        },
    )
    return int(result.modified_count or 0)


@router.get("/preferences/{identifier}")
async def get_guard_preferences(identifier: str):
    """Fetch persisted guard notification preferences."""
    guard = await _find_guard(email=identifier, phone_number=identifier)
    if not guard:
        raise HTTPException(status_code=404, detail="Guard profile not found")

    return {
        "preferred_language": normalize_guard_language(
            guard.get("preferred_language")
            or (guard.get("settings") or {}).get("preferred_language")
        ),
        "phone_number": guard.get("phone_number"),
        "whatsapp_enabled": bool(guard.get("whatsapp_enabled", True)),
    }


@router.post("/preferences")
async def update_guard_preferences(payload: GuardLanguagePreferencesRequest):
    """Persist guard language and WhatsApp delivery preference."""
    guards = get_guards_collection()
    identifier = (payload.identifier or "").strip()
    guard = await _find_guard(
        phone_number=payload.phone_number or identifier,
        email=identifier,
    )
    if not guard:
        raise HTTPException(status_code=404, detail="Guard profile not found")

    preferred_language = normalize_guard_language(
        payload.preferred_language or guard.get("preferred_language")
    )
    updates: Dict[str, Any] = {
        "whatsapp_enabled": bool(payload.whatsapp_enabled),
    }
    if payload.preferred_language is not None:
        updates["preferred_language"] = preferred_language

    await guards.update_one(
        {"_id": guard["_id"]},
        {"$set": updates},
    )

    return {
        "ok": True,
        "preferred_language": preferred_language,
        "phone_number": guard.get("phone_number"),
        "whatsapp_enabled": bool(payload.whatsapp_enabled),
    }


@router.post("/login")
async def guard_login(email: Optional[str] = Form(None), phone_number: Optional[str] = Form(None)):
    """Record a security guard's login."""
    duty_collection = get_guard_duty_collection()

    guard = await _find_guard(email=email, phone_number=phone_number)
    active_query = _guard_active_query_with_identity(
        guard) if guard else _fallback_active_query(email, phone_number)
    if active_query is None:
        raise HTTPException(
            status_code=400, detail="Email or phone_number is required.")

    # Check if guard is already on duty
    active_duty = await duty_collection.find_one(active_query)

    if active_duty:
        await _set_guard_duty_flag(guard, True)
        await _send_duty_status_notification(guard, True)
        return {
            "status": "already_on_duty",
            "message": f"Guard already clocked in at {active_duty['login_time']}",
            "login_time": active_duty["login_time"].isoformat(),
            "guard_name": active_duty.get("guard_name") or (guard.get("full_name") if guard else _fallback_guard_name(email, phone_number)),
            "phone_number": active_duty.get("phone_number") or (guard.get("phone_number") if guard else phone_number),
        }

    # Create new duty record
    duty_record = {
        "guard_id": str(guard.get("_id")) if guard else None,
        "guard_name": guard.get("full_name") if guard else _fallback_guard_name(email, phone_number),
        "phone_number": guard.get("phone_number") if guard else (phone_number.strip() if phone_number else None),
        "phone_normalized": normalize_phone(guard.get("phone_number")) if guard else normalize_phone(phone_number),
        "email": guard.get("email") if guard else (email.strip() if email else None),
        "email_normalized": normalize_email(guard.get("email")) if guard else normalize_email(email),
        "login_time": datetime.utcnow(),
        "logout_time": None,
        "alerts_handled": [],
        "duration_minutes": 0
    }

    validated = LogbookEntry(**duty_record)
    result = await duty_collection.insert_one(validated.dict())
    await _set_guard_duty_flag(guard, True)
    await _create_duty_log(guard, duty_record["login_time"])
    await _send_duty_status_notification(guard, True)

    return {
        "status": "logged_in",
        "message": f"Successfully clocked in at {duty_record['login_time']}",
        "duty_id": str(result.inserted_id),
        "login_time": duty_record["login_time"].isoformat(),
        "guard_name": duty_record.get("guard_name"),
        "phone_number": duty_record.get("phone_number"),
    }


@router.post("/logout")
async def guard_logout(email: Optional[str] = Form(None), phone_number: Optional[str] = Form(None)):
    """Record a security guard's logout."""
    duty_collection = get_guard_duty_collection()

    guard = await _find_guard(email=email, phone_number=phone_number)
    active_query = _guard_active_query_with_identity(
        guard) if guard else _fallback_active_query(email, phone_number)
    if active_query is None:
        raise HTTPException(
            status_code=400, detail="Email or phone_number is required.")

    active_duties = await duty_collection.find(active_query).to_list(length=200)

    if not active_duties:
        await _set_guard_duty_flag(guard, False)
        await _send_duty_status_notification(guard, False)
        return {
            "status": "not_on_duty",
            "message": "Guard is not currently logged in"
        }

    logout_time = datetime.utcnow()
    latest_login_time = max(d.get("login_time", logout_time)
                            for d in active_duties)
    duration = (logout_time - latest_login_time).total_seconds() / 60

    for active_duty in active_duties:
        login_time = active_duty.get("login_time") or logout_time
        record_duration = (logout_time - login_time).total_seconds() / 60
        await duty_collection.update_one(
            {"_id": active_duty["_id"]},
            {
                "$set": {
                    "logout_time": logout_time,
                    "duration_minutes": max(0.0, record_duration)
                }
            }
        )

    await _set_guard_duty_flag(guard, False)
    closed_duty_logs = await _close_duty_log(guard, logout_time)
    await _send_duty_status_notification(guard, False)

    return {
        "status": "logged_out",
        "message": f"Successfully clocked out at {logout_time}",
        "closed_records": len(active_duties),
        "closed_duty_logs": closed_duty_logs,
        "duty_duration": f"{int(duration // 60)} hours {int(duration % 60)} minutes",
        "login_time": latest_login_time.isoformat(),
        "logout_time": logout_time.isoformat(),
        "guard_name": (active_duties[0].get("guard_name") if active_duties else None) or (guard.get("full_name") if guard else _fallback_guard_name(email, phone_number)),
        "phone_number": (active_duties[0].get("phone_number") if active_duties else None) or (guard.get("phone_number") if guard else phone_number),
    }


@router.get("/current-status/{identifier}")
async def get_current_status(identifier: str):
    """Get current guard duty status."""
    duty_collection = get_guard_duty_collection()

    guard = await _find_guard(email=identifier, phone_number=identifier)
    if not guard:
        fallback_query = _fallback_active_query(identifier, identifier)
        if fallback_query is None:
            return {
                "status": "off_duty",
                "message": "Guard profile not found",
            }

        active_duties = await duty_collection.find(fallback_query).sort("login_time", -1).to_list(length=5)
        if not active_duties:
            return {
                "status": "off_duty",
                "message": "Guard is not currently on duty",
            }

        active_duty = active_duties[0]
        now = datetime.utcnow()
        login_dt = active_duty.get("login_time")
        duration = 0.0
        login_time = None
        if isinstance(login_dt, datetime):
            duration = (now - login_dt).total_seconds() / 60
            login_time = login_dt.isoformat()

        return {
            "status": "on_duty",
            "login_time": login_time,
            "duration_minutes": duration,
            "duration_formatted": f"{int(duration // 60)} hours {int(duration % 60)} minutes",
            "alerts_handled": len(active_duty.get("alerts_handled", [])),
            "guard_name": active_duty.get("guard_name") or _fallback_guard_name(identifier, identifier),
            "phone_number": active_duty.get("phone_number") or identifier,
        }

    is_on_duty = bool(guard.get("isOnDuty", False))

    # Duty status endpoint must be read-only: never mutate isOnDuty here.
    # Source-of-truth is the persisted guard profile flag.
    active_query = _guard_active_query(guard)
    active_duties = await duty_collection.find(active_query).sort("login_time", -1).to_list(length=5)

    if not is_on_duty:
        return {
            "status": "off_duty",
            "message": "Guard is not currently on duty"
        }

    duration = 0.0
    login_time = None
    alerts_handled = 0
    if active_duties:
        active_duty = active_duties[0]
        now = datetime.utcnow()
        login_dt = active_duty.get("login_time")
        if isinstance(login_dt, datetime):
            duration = (now - login_dt).total_seconds() / 60
            login_time = login_dt.isoformat()
        alerts_handled = len(active_duty.get("alerts_handled", []))

    return {
        "status": "on_duty",
        "login_time": login_time,
        "duration_minutes": duration,
        "duration_formatted": f"{int(duration // 60)} hours {int(duration % 60)} minutes",
        "alerts_handled": alerts_handled,
        "guard_name": guard.get("full_name") or _fallback_guard_name(identifier, identifier),
        "phone_number": guard.get("phone_number") or identifier,
    }


@router.get("/statistics/{identifier}")
async def get_guard_statistics(identifier: str, days: int = 7):
    """Get guard duty statistics for the past N days."""
    duty_collection = get_guard_duty_collection()
    alerts_collection = get_alerts_collection()

    # Get completed duty records
    start_date = datetime.utcnow() - timedelta(days=days)

    guard = await _find_guard(email=identifier, phone_number=identifier)
    stats_query = {
        "guard_id": str(guard.get("_id")),
        "logout_time": {"$ne": None},
        "login_time": {"$gte": start_date}
    } if guard else {
        "$or": [
            {"email_normalized": normalize_email(identifier)},
            {"phone_normalized": normalize_phone(identifier)},
        ],
        "logout_time": {"$ne": None},
        "login_time": {"$gte": start_date}
    }

    duty_records = await duty_collection.find(stats_query).to_list(length=None)

    total_minutes = sum(record.get("duration_minutes", 0)
                        for record in duty_records)
    total_hours = total_minutes / 60

    # Get alerts for this period
    alerts = await alerts_collection.find({
        "timestamp": {"$gte": start_date}
    }).to_list(length=None)

    # Count by type
    weapon_alerts = sum(1 for a in alerts if a.get("type") == "weapon")
    violence_alerts = sum(1 for a in alerts if a.get("type") == "violence")
    fire_alerts = sum(1 for a in alerts if a.get("type") == "fire")

    return {
        "email": guard.get("email") if guard else identifier,
        "guard_name": guard.get("full_name") if guard else _fallback_guard_name(identifier, identifier),
        "phone_number": guard.get("phone_number") if guard else identifier,
        "period_days": days,
        "duty_stats": {
            "total_shifts": len(duty_records),
            "total_hours": round(total_hours, 2),
            "average_shift_hours": round(total_hours / len(duty_records), 2) if duty_records else 0
        },
        "alerts_in_period": {
            "weapons": weapon_alerts,
            "violence": violence_alerts,
            "fire": fire_alerts,
            "total": len(alerts)
        },
        "recent_shifts": [
            {
                "login": r["login_time"].isoformat(),
                "logout": r["logout_time"].isoformat() if r["logout_time"] else None,
                "duration_hours": round(r.get("duration_minutes", 0) / 60, 2)
            }
            for r in sorted(duty_records, key=lambda x: x["login_time"], reverse=True)[:10]
        ]
    }


@router.post("/log-alert")
async def log_alert_to_duty(email: Optional[str] = Form(None), phone_number: Optional[str] = Form(None), alert_id: str = Form(...)):
    """Associate an alert with guard's current duty."""
    duty_collection = get_guard_duty_collection()

    guard = await _find_guard(email=email, phone_number=phone_number)
    active_query = _guard_active_query(
        guard) if guard else _fallback_active_query(email, phone_number)
    if active_query is None:
        return {
            "status": "error",
            "message": "Guard identity is required"
        }

    active_duty = await duty_collection.find_one(active_query)

    if not active_duty:
        return {
            "status": "error",
            "message": "Guard is not currently on duty"
        }

    # Add alert to the current duty record
    await duty_collection.update_one(
        {"_id": active_duty["_id"]},
        {
            "$addToSet": {"alerts_handled": alert_id}
        }
    )

    return {
        "status": "logged",
        "message": "Alert associated with current shift"
    }
