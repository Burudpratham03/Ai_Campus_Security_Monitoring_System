from datetime import timedelta, datetime, timezone
import random
import string
import os
from typing import Optional, Any
import asyncio
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError
from bson import ObjectId

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
try:
    from fastapi_mail import FastMail, MessageSchema, ConnectionConfig
    _HAS_FASTAPI_MAIL = True
except Exception:
    FastMail = None
    MessageSchema = None
    ConnectionConfig = None
    _HAS_FASTAPI_MAIL = False

import logging
import traceback

try:
    from ..database import get_db, get_users_collection, get_settings_collection, get_system_admins_collection, get_guards_collection
    from ..Models.schemas import (
        UserCreate,
        UserLogin,
        Token,
        UserSettings,
        UserLanguageUpdateRequest,
        SystemSettings,
        MaintenanceSettings,
        SettingsHealthResponse,
    )
    from ..utils.security import (
        get_password_hash,
        verify_password,
        create_access_token,
        send_otp as smtp_send_otp,
    )
    from ..utils.identity_validation import enforce_unique_identity_across_roles
except ImportError:
    from database import get_db, get_users_collection, get_system_admins_collection, get_guards_collection
    from Models.schemas import (
        UserCreate,
        UserLogin,
        Token,
        UserSettings,
        UserLanguageUpdateRequest,
        SystemSettings,
        MaintenanceSettings,
        SettingsHealthResponse,
    )
    from utils.security import (
        get_password_hash,
        verify_password,
        create_access_token,
        send_otp as smtp_send_otp,
    )
    from utils.identity_validation import enforce_unique_identity_across_roles
try:
    from ..utils import security
except ImportError:
    from utils import security
try:
    from ..utils.email_templates import (
        get_signup_otp_template,
        get_signup_success_template,
        get_login_otp_template,
    )
except ImportError:
    from utils.email_templates import (
        get_signup_otp_template,
        get_signup_success_template,
        get_login_otp_template,
    )

load_dotenv()

# Logging for auth/mail flows
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai_campus.auth")

# --- MAIL CONFIGURATION ---
# We consolidate all mail config here to avoid the Pydantic ValidationError.
# Modern fastapi-mail uses MAIL_STARTTLS and MAIL_SSL_TLS.
conf = None
_mail_user = os.getenv("MAIL_USERNAME")
_mail_pass = os.getenv("MAIL_PASSWORD")

if _mail_user and _mail_pass and _HAS_FASTAPI_MAIL:
    try:
        conf = ConnectionConfig(
            MAIL_USERNAME=_mail_user,
            MAIL_PASSWORD=_mail_pass,
            MAIL_FROM=os.getenv("MAIL_FROM", _mail_user),
            MAIL_PORT=int(os.getenv("SMTP_PORT", "587")),
            MAIL_SERVER=os.getenv("MAIL_SERVER", "smtp.gmail.com"),
            MAIL_FROM_NAME=os.getenv("MAIL_FROM_NAME", "Campus Guard AI"),
            # Ensure we use boolean values for the modern keys
            MAIL_STARTTLS=os.getenv("MAIL_STARTTLS", "True").lower() == "true",
            MAIL_SSL_TLS=os.getenv("MAIL_SSL_TLS", "False").lower() == "true",
            USE_CREDENTIALS=True,
            VALIDATE_CERTS=True,
        )
        logger.info("[AUTH] FastMail ConnectionConfig created: server=%s port=%s starttls=%s ssl_tls=%s from=%s", os.getenv(
            "MAIL_SERVER"), os.getenv("SMTP_PORT"), os.getenv("MAIL_STARTTLS"), os.getenv("MAIL_SSL_TLS"), os.getenv("MAIL_FROM"))
    except Exception as exc:
        print(f"[AUTH] Could not create ConnectionConfig: {exc}")
        logger.error("[AUTH] ConnectionConfig error: %s", exc)
        logger.error(traceback.format_exc())
        conf = None
else:
    if not _HAS_FASTAPI_MAIL and (_mail_user and _mail_pass):
        logger.warning(
            "[AUTH] fastapi-mail not installed; skipping FastMail configuration")
    else:
        print("[AUTH] Email credentials missing in .env. Falling back to SMTP helper.")
        logger.info(
            "[AUTH] Email credentials missing; using SMTP fallback helper")

router = APIRouter(prefix="/auth", tags=["auth"])

BASE_DIR = Path(__file__).resolve().parent.parent
CAPTURES_DIR = BASE_DIR / "captures"

# --- HELPERS ---


async def get_user_by_email(email: str) -> Optional[dict]:
    users = get_users_collection()
    return await users.find_one({"email": email})


def _maintenance_collection():
    return get_db()["maintenance_settings"]


def _settings_audit_collection():
    return get_db()["settings_audit"]


async def _write_settings_audit_entries(
    *,
    actor: str,
    category: str,
    before: dict,
    after: dict,
) -> None:
    audit = _settings_audit_collection()
    rows = []
    keys = sorted(set(before.keys()) | set(after.keys()))
    now = datetime.now(timezone.utc)
    for key in keys:
        old_value = before.get(key)
        new_value = after.get(key)
        if old_value == new_value:
            continue
        rows.append(
            {
                "actor": actor,
                "category": category,
                "field": key,
                "old_value": None if old_value is None else str(old_value),
                "new_value": None if new_value is None else str(new_value),
                "timestamp": now,
            }
        )
    if rows:
        await audit.insert_many(rows)


async def _assert_admin_actor(actor_email: Optional[str]) -> str:
    """Validate actor identity for high-impact settings actions."""
    normalized_email = str(actor_email or "").strip().lower()
    if not normalized_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin email is required for this action.",
        )

    admins_col = get_system_admins_collection()
    admin_doc = await admins_col.find_one(
        {
            "$or": [
                {"email": normalized_email},
                {"email_normalized": normalized_email},
            ],
            "is_verified": True,
        }
    )
    if not admin_doc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only verified admins can perform this action.",
        )

    return normalized_email


def _is_env_enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _check_waha_health() -> bool:
    base_url = str(os.getenv("WAHA_API_URL", "")).strip().rstrip("/")
    if not base_url:
        return False

    api_key = str(os.getenv("WAHA_API_KEY", "")).strip()
    session_name = str(os.getenv("WAHA_SESSION", "default")
                       ).strip() or "default"

    headers: dict[str, str] = {}
    if api_key:
        headers["X-Api-Key"] = api_key

    candidate_urls = [
        f"{base_url}/api/sessions",
        f"{base_url}/api/sessions/{session_name}",
        f"{base_url}/ping",
        base_url,
    ]

    for target_url in candidate_urls:
        try:
            req = Request(url=target_url, headers=headers, method="GET")
            with urlopen(req, timeout=4) as response:
                code = int(getattr(response, "status", 200))
                if code < 500:
                    return True
        except URLError:
            continue
        except Exception:
            continue
    return False


def generate_otp(length: int = 4) -> str:
    return "".join(random.choices(string.digits, k=length))


async def _send_signup_success_email(email: str, full_name: str) -> None:
    """Send a beautiful success email after OTP verification."""
    try:
        template = get_signup_success_template(full_name)
        message = None
        if MessageSchema is not None:
            message = MessageSchema(
                subject=template["subject"],
                recipients=[email],
                body=template["html"],
                subtype="html",
            )

        if conf:
            try:
                fm = FastMail(conf)
                logger.info(
                    "[AUTH] Sending signup success email via FastMail to %s", email)
                await fm.send_message(message)
                logger.info("[AUTH] Signup success email sent to %s", email)
            except Exception as exc:
                logger.error("[AUTH] FastMail success email failed: %s", exc)
        else:
            logger.info(
                "[AUTH] Success email config not available for %s", email)
    except Exception as exc:
        logger.error(
            "[AUTH] Failed to send success email to %s: %s", email, exc)

# --- ROUTES ---


@router.post("/signup")
async def signup(user: UserCreate):
    users = get_users_collection()
    system_admins = get_system_admins_collection()
    guards = get_guards_collection()

    await enforce_unique_identity_across_roles(
        system_admins_collection=system_admins,
        guards_collection=guards,
        full_name=user.full_name,
        email=user.email,
        phone_number=user.phone_number,
    )

    # Check for existing email
    existing = await users.find_one({"email": user.email})

    if existing:
        # If user is verified, reject signup (account already exists)
        if existing.get("is_verified", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User with this email already exists.",
            )
        # If user is unverified, allow retry by updating the record
        # This lets users retry signup without manual DB deletion
        user_id = existing["_id"]
    else:
        user_id = None

    # Prevent duplicate phone numbers (only for verified users or different emails)
    if user.phone_number:
        existing_phone = await users.find_one({"phone_number": user.phone_number})
        if existing_phone and existing_phone.get("is_verified", False):
            # Only reject if it's a different user who is verified
            if existing_phone.get("email") != user.email:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A user with this phone number already exists.",
                )

    hashed_password = get_password_hash(user.password)
    otp = generate_otp()

    user_doc = {
        "email": user.email,
        "full_name": user.full_name,
        "phone_number": user.phone_number,
        "hashed_password": hashed_password,
        "otp": otp,
        "is_verified": False,
        "preferred_language": "en",
        # default per-user settings
        "settings": UserSettings().dict(),
    }

    # If updating existing unverified user, use update_one; otherwise insert
    if user_id:
        await users.update_one({"_id": user_id}, {"$set": user_doc})
        # Mock result for consistency
        result = type('obj', (object,), {'inserted_id': user_id})()
    else:
        result = await users.insert_one(user_doc)

    # Get HTML email template
    template = get_signup_otp_template(user.full_name, otp)
    message = None
    if MessageSchema is not None:
        message = MessageSchema(
            subject=template["subject"],
            recipients=[user.email],
            body=template["html"],
            subtype="html",
        )

    # Attempt FastMail delivery; fallback to SMTP helper if it fails or isn't configured
    if conf:
        try:
            fm = FastMail(conf)
            logger.info(
                "[AUTH] Sending signup OTP via FastMail to %s", user.email)
            await fm.send_message(message)
            logger.info(
                "[AUTH] FastMail send_message completed for %s", user.email)
        except Exception as exc:
            print(
                f"[AUTH] Failed to send via FastMail: {exc}. Trying fallback...")
            logger.error("[AUTH] FastMail send_message exception: %s", exc)
            logger.error(traceback.format_exc())
            try:
                await asyncio.to_thread(smtp_send_otp, user.email, otp)
            except Exception as fallback_exc:
                logger.error(
                    "[AUTH] SMTP fallback also failed for %s: %s", user.email, fallback_exc)
                logger.error(traceback.format_exc())
    else:
        logger.info(
            "[AUTH] Using SMTP fallback helper to send OTP to %s", user.email)
        try:
            await asyncio.to_thread(smtp_send_otp, user.email, otp)
        except Exception as fallback_exc:
            logger.error("[AUTH] SMTP fallback failed for %s: %s",
                         user.email, fallback_exc)
            logger.error(traceback.format_exc())

    return {
        "message": "Signup successful. Verification code generated and sent.",
        "email": user.email,
        "full_name": user.full_name,
        "user_id": str(result.inserted_id),
    }


@router.get("/user-settings")
async def get_user_settings(email: str):
    users = get_users_collection()
    user = await users.find_one({"email": email})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"settings": user.get("settings", UserSettings().dict())}


@router.post("/user-settings")
async def update_user_settings(email: str, settings: UserSettings, actor_email: Optional[str] = None):
    users = get_users_collection()
    user = await users.find_one({"email": email})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    previous = user.get("settings", UserSettings().dict())
    await users.update_one({"_id": user["_id"]}, {"$set": {"settings": settings.dict()}})
    await _write_settings_audit_entries(
        actor=actor_email or email,
        category="user-settings",
        before=previous,
        after=settings.dict(),
    )
    return {"ok": True, "settings": settings.dict()}


async def _get_authenticated_user_from_request(request: Request) -> tuple[dict, Any, str]:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = auth_header.split(" ", 1)[1].strip()
    payload = security.decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get("sub")
    token_role = str(payload.get("role") or "").strip().lower()
    token_email = str(payload.get("email") or "").strip().lower()
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    users = get_users_collection()
    admins = get_system_admins_collection()
    guards = get_guards_collection()

    search_order: list[tuple[str, Any]]
    if token_role == "admin":
        search_order = [("admin", admins)]
    elif token_role == "guard":
        search_order = [("guard", guards)]
    else:
        search_order = [("user", users), ("admin", admins), ("guard", guards)]

    async def _find_actor(collection: Any) -> dict | None:
        actor = None
        try:
            actor = await collection.find_one({"_id": ObjectId(str(user_id))})
        except Exception:
            actor = await collection.find_one({"_id": str(user_id)})

        if actor:
            return actor

        if token_email:
            actor = await collection.find_one(
                {
                    "$or": [
                        {"email": token_email},
                        {"email_normalized": token_email},
                    ]
                }
            )
        return actor

    for role_name, collection in search_order:
        actor = await _find_actor(collection)
        if actor:
            resolved_role = str(actor.get("role") or role_name)
            return actor, collection, resolved_role

    # Fallback across all collections in case token role claim is stale.
    for role_name, collection in [("user", users), ("admin", admins), ("guard", guards)]:
        actor = await _find_actor(collection)
        if actor:
            resolved_role = str(actor.get("role") or role_name)
            return actor, collection, resolved_role

    raise HTTPException(status_code=404, detail="Authenticated user not found")


@router.put("/users/settings/language")
async def update_authenticated_user_language(payload: UserLanguageUpdateRequest, request: Request):
    user, actor_collection, actor_role = await _get_authenticated_user_from_request(request)

    next_lang = str(payload.preferred_language or "en").strip().lower()
    if next_lang not in {"en", "hi", "mr"}:
        raise HTTPException(
            status_code=400, detail="Unsupported language code")

    existing = user.get("settings") or UserSettings().dict()
    before = dict(existing)
    existing["preferred_language"] = next_lang

    await actor_collection.update_one(
        {"_id": user["_id"]},
        {"$set": {"settings": existing, "preferred_language": next_lang}},
    )
    await _write_settings_audit_entries(
        actor=str(user.get("email") or user.get("_id")),
        category="user-settings-language",
        before=before,
        after=existing,
    )

    return {
        "ok": True,
        "preferred_language": next_lang,
        "email": user.get("email"),
        "user_id": str(user.get("_id")),
        "role": actor_role,
    }


@router.get("/users/settings/language")
async def get_authenticated_user_language(request: Request):
    user, _, actor_role = await _get_authenticated_user_from_request(request)
    stored = user.get("preferred_language")
    if not stored:
        stored = (user.get("settings") or {}).get("preferred_language")
    next_lang = str(stored or "en").strip().lower()
    if next_lang not in {"en", "hi", "mr"}:
        next_lang = "en"

    return {
        "ok": True,
        "preferred_language": next_lang,
        "email": user.get("email"),
        "user_id": str(user.get("_id")),
        "role": actor_role,
    }


@router.get("/system-settings")
async def get_system_settings():
    settings_col = get_settings_collection()
    doc = await settings_col.find_one({})
    if not doc:
        sys = SystemSettings()
        await settings_col.insert_one(sys.dict())
        return {"system_settings": sys.dict()}
    # strip Mongo id
    doc.pop("_id", None)
    return {"system_settings": doc}


@router.post("/system-settings")
async def update_system_settings(settings: SystemSettings, actor_email: Optional[str] = None):
    settings_col = get_settings_collection()
    previous_doc = await settings_col.find_one({}) or {}
    previous = {
        "detection_threshold": previous_doc.get("detection_threshold", SystemSettings().detection_threshold),
        "weapon_cooldown_seconds": previous_doc.get("weapon_cooldown_seconds", SystemSettings().weapon_cooldown_seconds),
    }
    await settings_col.replace_one({}, settings.dict(), upsert=True)
    await _write_settings_audit_entries(
        actor=actor_email or "system",
        category="system-settings",
        before=previous,
        after=settings.dict(),
    )
    return {"ok": True, "system_settings": settings.dict()}


@router.get("/maintenance-settings")
async def get_maintenance_settings():
    maintenance_col = _maintenance_collection()
    doc = await maintenance_col.find_one({})
    if not doc:
        defaults = MaintenanceSettings().dict()
        await maintenance_col.insert_one(defaults)
        return {"maintenance_settings": defaults}
    doc.pop("_id", None)
    return {"maintenance_settings": doc}


@router.post("/maintenance-settings")
async def update_maintenance_settings(settings: MaintenanceSettings, actor_email: Optional[str] = None):
    maintenance_col = _maintenance_collection()
    previous_doc = await maintenance_col.find_one({}) or {}
    previous = {
        "retention_days": previous_doc.get("retention_days", MaintenanceSettings().retention_days),
        "auto_archive": previous_doc.get("auto_archive", MaintenanceSettings().auto_archive),
    }
    await maintenance_col.replace_one({}, settings.dict(), upsert=True)
    await _write_settings_audit_entries(
        actor=actor_email or "system",
        category="maintenance-settings",
        before=previous,
        after=settings.dict(),
    )
    return {"ok": True, "maintenance_settings": settings.dict()}


@router.post("/maintenance/clear-old-footage")
async def clear_old_footage(retention_days: Optional[int] = None, actor_email: Optional[str] = None):
    maintenance_col = _maintenance_collection()
    doc = await maintenance_col.find_one({}) or MaintenanceSettings().dict()
    effective_retention_days = int(
        retention_days or doc.get("retention_days") or 30)

    deleted_files = 0
    scanned_files = 0
    freed_bytes = 0
    deleted_media_docs = 0
    deleted_alert_docs = 0
    deleted_notification_docs = 0

    if CAPTURES_DIR.exists():
        for path in CAPTURES_DIR.rglob("*"):
            if not path.is_file():
                continue
            scanned_files += 1
            try:
                stat = path.stat()
                freed_bytes += stat.st_size
                path.unlink(missing_ok=True)
                deleted_files += 1
            except Exception:
                continue

    # Remove footage-linked DB records so report evidence sections are cleared too.
    db = get_db()
    media_col = db["media"]
    alerts_col = db["alerts"]
    notifications_col = db["guard_notifications"]

    try:
        media_result = await media_col.delete_many({
            "frame_path": {"$exists": True, "$ne": None}
        })
        deleted_media_docs = int(
            getattr(media_result, "deleted_count", 0) or 0)
    except Exception:
        deleted_media_docs = 0

    try:
        alerts_result = await alerts_col.delete_many(
            {"frame_path": {"$exists": True, "$ne": None}},
        )
        deleted_alert_docs = int(
            getattr(alerts_result, "deleted_count", 0) or 0)
    except Exception:
        deleted_alert_docs = 0

    try:
        notifications_result = await notifications_col.delete_many(
            {"frame_path": {"$exists": True, "$ne": None}},
        )
        deleted_notification_docs = int(
            getattr(notifications_result, "deleted_count", 0) or 0
        )
    except Exception:
        deleted_notification_docs = 0

    await _write_settings_audit_entries(
        actor=actor_email or "system",
        category="maintenance-action",
        before={"clear_old_footage": "idle"},
        after={
            "clear_old_footage": (
                f"deleted={deleted_files},scanned={scanned_files},freed_bytes={freed_bytes},"
                f"media_deleted={deleted_media_docs},alerts_deleted={deleted_alert_docs},"
                f"notifications_deleted={deleted_notification_docs}"
            )
        },
    )

    return {
        "ok": True,
        "retention_days": effective_retention_days,
        "deleted_files": deleted_files,
        "scanned_files": scanned_files,
        "freed_bytes": freed_bytes,
        "db_cleanup": {
            "deleted_media_docs": deleted_media_docs,
            "deleted_alert_docs": deleted_alert_docs,
            "deleted_notification_docs": deleted_notification_docs,
            # Backward-compatible aliases
            "alerts_frame_path_cleared": deleted_alert_docs,
            "notifications_frame_path_cleared": deleted_notification_docs,
        },
    }


@router.post("/maintenance/reset-defaults")
async def reset_defaults(confirm: bool = False, actor_email: Optional[str] = None):
    """Reset maintenance/system settings to defaults and clear all captures."""
    if not confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation is required to reset defaults.",
        )

    actor = await _assert_admin_actor(actor_email)

    settings_col = get_settings_collection()
    maintenance_col = _maintenance_collection()

    default_system = SystemSettings().dict()
    default_maintenance = MaintenanceSettings().dict()

    previous_system = await settings_col.find_one({}) or {}
    previous_maintenance = await maintenance_col.find_one({}) or {}

    await settings_col.replace_one({}, default_system, upsert=True)
    await maintenance_col.replace_one({}, default_maintenance, upsert=True)

    deleted_files = 0
    scanned_files = 0
    freed_bytes = 0
    deleted_media_docs = 0
    deleted_alert_docs = 0
    deleted_notification_docs = 0
    if CAPTURES_DIR.exists():
        for path in CAPTURES_DIR.rglob("*"):
            if not path.is_file():
                continue
            scanned_files += 1
            try:
                file_size = path.stat().st_size
                path.unlink(missing_ok=True)
                deleted_files += 1
                freed_bytes += file_size
            except Exception:
                continue

    # Ensure reset also purges footage-linked DB records.
    db = get_db()
    media_col = db["media"]
    alerts_col = db["alerts"]
    notifications_col = db["guard_notifications"]

    try:
        media_result = await media_col.delete_many(
            {"frame_path": {"$exists": True, "$ne": None}}
        )
        deleted_media_docs = int(
            getattr(media_result, "deleted_count", 0) or 0)
    except Exception:
        deleted_media_docs = 0

    try:
        alerts_result = await alerts_col.delete_many(
            {"frame_path": {"$exists": True, "$ne": None}}
        )
        deleted_alert_docs = int(
            getattr(alerts_result, "deleted_count", 0) or 0)
    except Exception:
        deleted_alert_docs = 0

    try:
        notifications_result = await notifications_col.delete_many(
            {"frame_path": {"$exists": True, "$ne": None}}
        )
        deleted_notification_docs = int(
            getattr(notifications_result, "deleted_count", 0) or 0
        )
    except Exception:
        deleted_notification_docs = 0

    await _write_settings_audit_entries(
        actor=actor,
        category="system-settings",
        before={
            "detection_threshold": previous_system.get("detection_threshold", default_system["detection_threshold"]),
            "weapon_cooldown_seconds": previous_system.get("weapon_cooldown_seconds", default_system["weapon_cooldown_seconds"]),
        },
        after=default_system,
    )
    await _write_settings_audit_entries(
        actor=actor,
        category="maintenance-settings",
        before={
            "retention_days": previous_maintenance.get("retention_days", default_maintenance["retention_days"]),
            "auto_archive": previous_maintenance.get("auto_archive", default_maintenance["auto_archive"]),
        },
        after=default_maintenance,
    )
    await _write_settings_audit_entries(
        actor=actor,
        category="maintenance-action",
        before={"reset_defaults": "idle"},
        after={
            "reset_defaults": (
                f"deleted={deleted_files},scanned={scanned_files},freed_bytes={freed_bytes},"
                f"media_deleted={deleted_media_docs},alerts_deleted={deleted_alert_docs},"
                f"notifications_deleted={deleted_notification_docs}"
            )
        },
    )

    return {
        "ok": True,
        "message": "Defaults restored and all captured footage cleared.",
        "deleted_files": deleted_files,
        "scanned_files": scanned_files,
        "freed_bytes": freed_bytes,
        "db_cleanup": {
            "deleted_media_docs": deleted_media_docs,
            "deleted_alert_docs": deleted_alert_docs,
            "deleted_notification_docs": deleted_notification_docs,
            # Backward-compatible aliases
            "alerts_frame_path_cleared": deleted_alert_docs,
            "notifications_frame_path_cleared": deleted_notification_docs,
        },
        "system_settings": default_system,
        "maintenance_settings": default_maintenance,
    }


@router.get("/settings-health")
async def get_settings_health():
    waha_connected = await asyncio.to_thread(_check_waha_health)
    gemini_connected = bool(os.getenv("GEMINI_API_KEY", "").strip())
    email_connected = bool(os.getenv("MAIL_USERNAME", "").strip(
    ) and os.getenv("MAIL_PASSWORD", "").strip())
    model = SettingsHealthResponse(
        waha_connected=waha_connected,
        gemini_connected=gemini_connected,
        email_connected=email_connected,
    )
    return model.dict()


@router.get("/settings-audit")
async def get_settings_audit(limit: int = 20):
    audit = _settings_audit_collection()
    safe_limit = max(1, min(int(limit), 100))
    rows = await audit.find({}).sort("timestamp", -1).limit(safe_limit).to_list(length=safe_limit)
    payload = []
    for row in rows:
        payload.append(
            {
                "id": str(row.get("_id")),
                "actor": row.get("actor", "system"),
                "category": row.get("category", "settings"),
                "field": row.get("field", "unknown"),
                "old_value": row.get("old_value"),
                "new_value": row.get("new_value"),
                "timestamp": row.get("timestamp"),
            }
        )
    return {"entries": payload}


@router.post("/login")
async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    email = form_data.username
    password = form_data.password

    # Fallback if client sent JSON instead of form-data
    if not email and not password:
        try:
            body = await request.json()
            email = body.get("email") or body.get("username")
            password = body.get("password")
        except Exception:
            pass

    user = await get_user_by_email(email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user.get("is_verified", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please verify your email before logging in.",
        )

    try:
        valid = verify_password(password, user.get("hashed_password", ""))
    except Exception as exc:
        print(f"[AUTH] Password verification error: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication error"
        )

    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    access_token = create_access_token(
        {"sub": str(user["_id"])}, expires_delta=timedelta(minutes=60))

    return {
        "status": "Login Successful",
        "user_id": str(user["_id"]),
        "name": user.get("full_name", ""),
        "token": access_token,
    }


@router.post("/request-otp")
async def request_otp(email: str):
    user = await get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    otp = generate_otp()
    users = get_users_collection()
    await users.update_one({"_id": user["_id"]}, {"$set": {"otp": otp}})

    # Get HTML email template
    template = get_login_otp_template(user.get("full_name", "User"), otp)
    message = None
    if MessageSchema is not None:
        message = MessageSchema(
            subject=template["subject"],
            recipients=[email],
            body=template["html"],
            subtype="html",
        )

    # Send OTP with beautiful template
    if conf:
        try:
            fm = FastMail(conf)
            logger.info("[AUTH] Sending login OTP via FastMail to %s", email)
            await fm.send_message(message)
            logger.info("[AUTH] FastMail login OTP sent to %s", email)
        except Exception as exc:
            logger.error("[AUTH] FastMail login OTP failed: %s", exc)
            try:
                await asyncio.to_thread(smtp_send_otp, email, otp)
            except Exception as fallback_exc:
                logger.error(
                    "[AUTH] SMTP fallback failed for login OTP: %s", fallback_exc)
    else:
        logger.info("[AUTH] Using SMTP fallback for login OTP to %s", email)
        try:
            await asyncio.to_thread(smtp_send_otp, email, otp)
        except Exception as fallback_exc:
            logger.error("[AUTH] SMTP fallback failed: %s", fallback_exc)

    return {"message": "OTP generated and sent."}


@router.post("/request-password-reset")
async def request_password_reset(email: str):
    """Generate a one-time code for password reset and email it to the user.

    Stores `password_reset_otp` and `password_reset_expires` on the user document.
    """
    user = await get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    otp = generate_otp()
    expires = datetime.utcnow() + timedelta(minutes=10)
    users = get_users_collection()
    await users.update_one({"_id": user["_id"]}, {"$set": {"password_reset_otp": otp, "password_reset_expires": expires}})

    # Use login OTP template for reset email (keeps UI consistent)
    template = get_login_otp_template(user.get("full_name", "User"), otp)
    message = None
    if MessageSchema is not None:
        message = MessageSchema(
            subject=f"Password Reset Code - {otp}",
            recipients=[email],
            body=template["html"],
            subtype="html",
        )

    if conf:
        try:
            fm = FastMail(conf)
            logger.info(
                "[AUTH] Sending password reset OTP via FastMail to %s", email)
            await fm.send_message(message)
            logger.info("[AUTH] FastMail password reset OTP sent to %s", email)
        except Exception as exc:
            logger.error("[AUTH] FastMail password reset OTP failed: %s", exc)
            try:
                await asyncio.to_thread(smtp_send_otp, email, otp)
            except Exception as fallback_exc:
                logger.error(
                    "[AUTH] SMTP fallback failed for password reset OTP: %s", fallback_exc)
    else:
        logger.info(
            "[AUTH] Using SMTP fallback for password reset OTP to %s", email)
        try:
            await asyncio.to_thread(smtp_send_otp, email, otp)
        except Exception as fallback_exc:
            logger.error(
                "[AUTH] SMTP fallback failed for password reset OTP: %s", fallback_exc)

    return {"message": "Password reset OTP generated and sent."}


@router.post("/reset-password")
async def reset_password(email: str, otp: str, new_password: str):
    """Verify password-reset OTP and set new password.

    This endpoint performs the second step: verify the OTP and update the user's password.
    """
    user = await get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    stored_otp = user.get("password_reset_otp")
    expires = user.get("password_reset_expires")
    if not stored_otp or stored_otp != otp:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP.")
    # Check expiry
    if not expires or (isinstance(expires, datetime) and expires < datetime.utcnow()):
        raise HTTPException(status_code=400, detail="OTP expired.")

    # Hash new password and update DB
    hashed = get_password_hash(new_password)
    users = get_users_collection()
    await users.update_one({"_id": user["_id"]}, {"$set": {"hashed_password": hashed}, "$unset": {"password_reset_otp": "", "password_reset_expires": ""}})

    return {"message": "Password updated successfully."}


@router.post("/verify-otp")
async def verify_otp(email: str, otp: str):
    user = await get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    stored_otp = user.get("otp")
    if not stored_otp or stored_otp != otp:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP.")

    # Update: Mark user as verified and clear the OTP
    users = get_users_collection()
    await users.update_one(
        {"_id": user["_id"]},
        {"$set": {"is_verified": True}, "$unset": {"otp": ""}}
    )

    # Send success email asynchronously (don't block login)
    try:
        asyncio.create_task(_send_signup_success_email(
            email, user.get("full_name", "User")))
    except Exception as exc:
        logger.error("[AUTH] Failed to schedule success email: %s", exc)

    access_token = create_access_token(
        {"sub": str(user["_id"])}, expires_delta=timedelta(minutes=60))

    return Token(
        access_token=access_token,
        email=user.get("email"),
        full_name=user.get("full_name")
    )


@router.post("/test-email")
async def test_email(email: str):
    """Attempt a direct SMTP connection and send a small test message.

    Returns detailed error trace on failure to help debugging.
    """
    import smtplib
    from email.mime.text import MIMEText
    try:
        subject = "Campus Guard AI SMTP Test"
        body = "This is a test message to verify SMTP connectivity."
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = f"{os.getenv('MAIL_FROM_NAME', 'Campus Guard AI')} <{os.getenv('MAIL_USERNAME')}>"
        msg["To"] = email

        logger.info("[AUTH] test-email: connecting to %s:%s",
                    security.SMTP_HOST, security.SMTP_PORT)
        with smtplib.SMTP(security.SMTP_HOST, security.SMTP_PORT, timeout=20) as server:
            server.set_debuglevel(1)
            server.ehlo()
            if security.SMTP_PORT == 587:
                server.starttls()
                server.ehlo()
            server.login(security.MAIL_USERNAME, security.MAIL_PASSWORD)
            server.sendmail(security.MAIL_USERNAME, [email], msg.as_string())

        return {"ok": True, "message": f"Test email sent to {email}"}
    except Exception as exc:
        logger.error("[AUTH] test-email failed: %s", exc)
        logger.error(traceback.format_exc())
        return {"ok": False, "error": str(exc), "trace": traceback.format_exc()}
