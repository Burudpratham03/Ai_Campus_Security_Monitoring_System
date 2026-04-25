import os
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from dotenv import load_dotenv

try:
    import certifi
except Exception:  # pragma: no cover - optional at runtime
    certifi = None


# Always load env from Backend/.env, even when uvicorn is started from repo root.
_BACKEND_DIR = Path(__file__).resolve().parent
_BACKEND_ENV = _BACKEND_DIR / ".env"
if _BACKEND_ENV.exists():
    load_dotenv(dotenv_path=_BACKEND_ENV)
else:
    load_dotenv()

# Trim environment values to avoid accidental trailing spaces (common cause
# of connecting to the wrong database name). Using .strip() keeps defaults
# intact when variables are not set.
MONGO_URL: str = os.getenv("MONGO_URL", "mongodb://localhost:27017").strip()
DB_NAME: str = os.getenv("DB_NAME", "campus_security").strip()

client: Optional[AsyncIOMotorClient] = None
db: Optional[AsyncIOMotorDatabase] = None


class DatabaseUnavailableError(RuntimeError):
    """Raised when MongoDB is not connected or unavailable."""


def _is_truthy_flag(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _should_use_tls_ca_file(mongo_url: str) -> bool:
    normalized = str(mongo_url or "").strip().lower()
    if normalized.startswith("mongodb+srv://"):
        return True

    parsed = urlparse(str(mongo_url or "").strip())
    query = parse_qs(parsed.query)
    tls_flags = query.get("tls", []) + query.get("ssl", [])
    if not tls_flags:
        return False
    return any(_is_truthy_flag(flag) for flag in tls_flags)


def _split_name(full_name: str | None) -> tuple[str, str, str]:
    parts = [p for p in str(full_name or "").strip().split() if p]
    if not parts:
        return "", "", ""
    if len(parts) == 1:
        return parts[0], "", ""
    if len(parts) == 2:
        return parts[0], "", parts[1]
    return parts[0], " ".join(parts[1:-1]), parts[-1]


def _normalize_name_part(value: str | None) -> str:
    return " ".join(str(value or "").strip().split()).lower()


async def migrate_users_to_unified_collection() -> None:
    """Migrate legacy admin/guard documents into one users collection."""
    if db is None:
        raise RuntimeError("Database not initialized.")

    users = db["users"]
    admins = db["system_admins"]
    guards = db["guards"]

    async for admin in admins.find({}):
        first_name, middle_name, last_name = _split_name(
            admin.get("full_name"))
        normalized_email = str(
            admin.get("email_normalized") or "").strip().lower()
        selector = {
            "role": "admin",
            "email_normalized": normalized_email,
        }
        update = {
            "$set": {
                "role": "admin",
                "first_name": first_name,
                "middle_name": middle_name,
                "last_name": last_name,
                "first_name_normalized": _normalize_name_part(first_name),
                "middle_name_normalized": _normalize_name_part(middle_name),
                "last_name_normalized": _normalize_name_part(last_name),
                "full_name": str(admin.get("full_name") or "").strip(),
                "normalized_full_name": str(admin.get("normalized_full_name") or "").strip().lower(),
                "email": admin.get("email"),
                "email_normalized": normalized_email,
                "phone_number": admin.get("phone_number"),
                "phone_normalized": admin.get("phone_normalized"),
                "hashed_password": admin.get("hashed_password"),
                "otp": admin.get("otp"),
                "otp_expires": admin.get("otp_expires"),
                "is_verified": bool(admin.get("is_verified", False)),
                "created_at": admin.get("created_at"),
                "last_login": admin.get("last_login"),
            }
        }
        await users.update_one(selector, update, upsert=True)

    async for guard in guards.find({}):
        first_name = str(guard.get("first_name") or "").strip()
        middle_name = str(guard.get("middle_name") or "").strip()
        last_name = str(guard.get("last_name") or "").strip()
        if not first_name and not last_name:
            first_name, middle_name, last_name = _split_name(
                guard.get("full_name"))
        normalized_phone = str(guard.get("phone_normalized") or "").strip()
        selector = {
            "role": "guard",
            "phone_normalized": normalized_phone,
        }
        update = {
            "$set": {
                "role": "guard",
                "first_name": first_name,
                "middle_name": middle_name,
                "last_name": last_name,
                "first_name_normalized": _normalize_name_part(first_name),
                "middle_name_normalized": _normalize_name_part(middle_name),
                "last_name_normalized": _normalize_name_part(last_name),
                "full_name": str(guard.get("full_name") or "").strip(),
                "normalized_full_name": str(guard.get("normalized_full_name") or "").strip().lower(),
                "email": guard.get("email"),
                "email_normalized": guard.get("email_normalized"),
                "phone_number": guard.get("phone_number"),
                "phone_normalized": normalized_phone,
                "otp": guard.get("otp"),
                "otp_expires": guard.get("otp_expires"),
                "otp_attempts": guard.get("otp_attempts", 0),
                "otp_locked_until": guard.get("otp_locked_until"),
                "is_verified": bool(guard.get("is_verified", False)),
                "isOnDuty": bool(guard.get("isOnDuty", guard.get("is_on_duty", False))),
                "preferred_language": guard.get("preferred_language", "en"),
                "whatsapp_enabled": bool(guard.get("whatsapp_enabled", True)),
                "welcome_message_sent": bool(guard.get("welcome_message_sent", False)),
                "created_at": guard.get("created_at"),
                "last_login": guard.get("last_login"),
                "last_otp_sent_at": guard.get("last_otp_sent_at"),
            }
        }
        await users.update_one(selector, update, upsert=True)


async def ensure_identity_indexes() -> None:
    """Create unique indexes used by auth identity validation.

    These indexes are idempotent and provide race-safe uniqueness enforcement.
    """
    if db is None:
        raise RuntimeError("Database not initialized.")

    users = db["users"]
    alerts = db["alerts"]
    media = db["media"]
    logbook = db["guard_duty"]

    # Legacy records may have empty-string normalized emails. Convert them to
    # missing fields so a unique partial index can be created safely.
    await users.update_many(
        {"email_normalized": ""},
        {"$unset": {"email_normalized": ""}},
    )

    index_jobs = [
        (users, "normalized_full_name", {
            "unique": True,
            "name": "uniq_users_normalized_full_name",
            "partialFilterExpression": {"normalized_full_name": {"$type": "string"}},
        }),
        (users, "email_normalized", {
            "unique": True,
            "name": "uniq_users_email_normalized",
            "partialFilterExpression": {"email_normalized": {"$type": "string"}},
        }),
        (users, "phone_normalized", {
            "unique": True,
            "name": "uniq_users_phone_normalized",
            "partialFilterExpression": {"phone_normalized": {"$type": "string"}},
        }),
        (users, [("first_name_normalized", 1), ("middle_name_normalized", 1), ("last_name_normalized", 1)], {
            "unique": True,
            "name": "uniq_users_name_triplet",
            "partialFilterExpression": {
                "first_name_normalized": {"$type": "string"},
                "last_name_normalized": {"$type": "string"},
            },
        }),
        (users, "role", {"name": "idx_users_role"}),
        (alerts, "timestamp", {"name": "idx_alerts_timestamp"}),
        (media, "incident_id", {"name": "idx_media_incident_id"}),
        (media, "created_at", {"name": "idx_media_created_at"}),
        (logbook, "guard_id", {"name": "idx_logbook_guard_id"}),
        (logbook, "login_time", {"name": "idx_logbook_login_time"}),
    ]

    for collection, fields, options in index_jobs:
        try:
            await collection.create_index(fields, **options)
        except Exception as exc:
            # Do not block startup; app-level checks still prevent most duplicates.
            print(
                f"[DB][INDEX][WARN] Failed to create index {options.get('name')}: {exc}")


async def migrate_duty_and_alert_status_fields() -> None:
    """Normalize guard duty and incident status fields to current schema."""
    if db is None:
        raise RuntimeError("Database not initialized.")

    users = db["users"]
    alerts = db["alerts"]

    # Hard migration: use isOnDuty only.
    await users.update_many(
        {"is_on_duty": {"$exists": True}},
        {"$rename": {"is_on_duty": "isOnDuty"}},
    )
    await users.update_many(
        {"role": "guard", "isOnDuty": {"$exists": False}},
        {"$set": {"isOnDuty": False}},
    )

    # Ensure every user has an isolated preferred_language at top level.
    # If missing, use settings.preferred_language when present, else default to "en".
    await users.update_many(
        {"preferred_language": {"$exists": False},
            "settings.preferred_language": {"$exists": True}},
        [{"$set": {"preferred_language": "$settings.preferred_language"}}],
    )
    await users.update_many(
        {"preferred_language": {"$exists": False}},
        {"$set": {"preferred_language": "en"}},
    )
    await users.update_many(
        {"preferred_language": {"$nin": ["en", "hi", "mr"]}},
        {"$set": {"preferred_language": "en"}},
    )

    # Status migration: verified -> resolved, false_alarm -> dismissed.
    await alerts.update_many({"status": "verified"}, {"$set": {"status": "resolved"}})
    await alerts.update_many({"status": "false_alarm"}, {"$set": {"status": "dismissed"}})

    valid_statuses = {"pending", "confirmed", "dismissed", "resolved"}
    now = datetime.now(timezone.utc)
    async for doc in alerts.find({}):
        status = str(doc.get("status") or "pending").strip().lower()
        patch: dict = {}
        if status not in valid_statuses:
            patch["status"] = "pending"
        if status == "confirmed" and not doc.get("dispatched_at"):
            patch["dispatched_at"] = now
        if patch:
            await alerts.update_one({"_id": doc["_id"]}, {"$set": patch})


async def get_database() -> AsyncIOMotorDatabase:
    """
    Dependency for FastAPI routes to get the active database instance.
    """
    if db is None:
        raise DatabaseUnavailableError(
            "Database not initialized. Ensure startup event has run.")
    return db


async def connect_to_mongo() -> None:
    """
    Initialize the global MongoDB client and database.
    """
    global client, db
    if client is None:
        mongo_options: dict = {
            "serverSelectionTimeoutMS": int(
                os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "12000")
            )
        }
        if certifi is not None and _should_use_tls_ca_file(MONGO_URL):
            mongo_options["tlsCAFile"] = certifi.where()

        try:
            client = AsyncIOMotorClient(MONGO_URL, **mongo_options)
            db = client[DB_NAME]
            # Force an early connection check so TLS/network issues fail fast.
            await client.admin.command("ping")
            await migrate_users_to_unified_collection()
            await migrate_duty_and_alert_status_fields()
            await ensure_identity_indexes()
        except Exception:
            if client is not None:
                client.close()
            client = None
            db = None
            raise


async def close_mongo_connection() -> None:
    """
    Close the MongoDB connection.
    """
    global client, db
    if client is not None:
        client.close()
    client = None
    db = None


def get_db() -> AsyncIOMotorDatabase:
    """Get the active database instance."""
    if db is None:
        raise DatabaseUnavailableError("Database not initialized.")
    return db


def get_users_collection():
    if db is None:
        raise DatabaseUnavailableError("Database not initialized.")
    return db["users"]


def get_alerts_collection():
    if db is None:
        raise DatabaseUnavailableError("Database not initialized.")
    return db["alerts"]


def get_reports_collection():
    if db is None:
        raise DatabaseUnavailableError("Database not initialized.")
    return db["reports"]


def get_settings_collection():
    if db is None:
        raise DatabaseUnavailableError("Database not initialized.")
    return db["settings"]


def get_system_admins_collection():
    if db is None:
        raise DatabaseUnavailableError("Database not initialized.")
    return db["users"]


def get_guards_collection():
    if db is None:
        raise DatabaseUnavailableError("Database not initialized.")
    return db["users"]


def get_media_collection():
    if db is None:
        raise DatabaseUnavailableError("Database not initialized.")
    return db["media"]


def get_logbook_collection():
    if db is None:
        raise DatabaseUnavailableError("Database not initialized.")
    return db["guard_duty"]


def get_chat_logs_collection():
    if db is None:
        raise DatabaseUnavailableError("Database not initialized.")
    return db["chat_logs"]
