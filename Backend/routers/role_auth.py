from datetime import datetime, timedelta
import asyncio
import os

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

try:
    from ..database import get_system_admins_collection, get_guards_collection
    from ..Models.schemas import (
        AdminLoginRequest,
        AdminSignupRequest,
        AdminVerifyOtpRequest,
        GuardLoginRequest,
        GuardSignInRequest,
        GuardVerifyOtpRequest,
        Token,
    )
    from ..utils.security import (
        create_access_token,
        verify_password,
        get_password_hash,
        send_otp as smtp_send_otp,
        send_email,
        send_whatsapp,
    )
    from ..utils.identity_validation import (
        DUPLICATE_EMAIL_DETAIL,
        DUPLICATE_FULL_NAME_DETAIL,
        DUPLICATE_PHONE_DETAIL,
        enforce_unique_identity_across_roles,
        normalize_email,
        normalize_full_name,
        normalize_phone,
    )
    from ..utils.guard_whatsapp_text import (
        build_guard_onboarding_message,
        build_guard_otp_message,
        normalize_guard_language,
    )
except ImportError:
    from database import get_system_admins_collection, get_guards_collection
    from Models.schemas import (
        AdminLoginRequest,
        AdminSignupRequest,
        AdminVerifyOtpRequest,
        GuardLoginRequest,
        GuardSignInRequest,
        GuardVerifyOtpRequest,
        Token,
    )
    from utils.security import (
        create_access_token,
        verify_password,
        get_password_hash,
        send_otp as smtp_send_otp,
        send_email,
        send_whatsapp,
    )
    from utils.identity_validation import (
        DUPLICATE_EMAIL_DETAIL,
        DUPLICATE_FULL_NAME_DETAIL,
        DUPLICATE_PHONE_DETAIL,
        enforce_unique_identity_across_roles,
        normalize_email,
        normalize_full_name,
        normalize_phone,
    )
    from utils.guard_whatsapp_text import (
        build_guard_onboarding_message,
        build_guard_otp_message,
        normalize_guard_language,
    )

router = APIRouter(prefix="", tags=["role-auth"])

OTP_EXPIRY_MINUTES = 10
OTP_RESEND_COOLDOWN_SECONDS = 30
OTP_MAX_ATTEMPTS = 5
OTP_LOCK_MINUTES = 10
PHONE_ALREADY_REGISTERED_DETAIL = "This phone number is already registered. Please log in."


class GuardResendOtpRequest(BaseModel):
    phone_number: str = Field(min_length=6)


class AdminLogoutRequest(BaseModel):
    email: str


class AdminForgotPasswordRequest(BaseModel):
    email: str


def _duplicate_identity_detail_from_error(error: DuplicateKeyError) -> str:
    message = str(getattr(error, "details", None) or error)
    lowered = message.lower()
    if "normalized_full_name" in lowered:
        return DUPLICATE_FULL_NAME_DETAIL
    if "first_name_normalized" in lowered or "last_name_normalized" in lowered or "uniq_users_name_triplet" in lowered:
        return DUPLICATE_FULL_NAME_DETAIL
    if "email_normalized" in lowered:
        return DUPLICATE_EMAIL_DETAIL
    if "phone_normalized" in lowered:
        return DUPLICATE_PHONE_DETAIL
    return "Duplicate identity detected. Please use unique details."


def _should_expose_otp_preview() -> bool:
    runtime_env = os.getenv("ENV", "development").strip().lower()
    if runtime_env == "production":
        return False
    flag = os.getenv("ENABLE_OTP_PREVIEW", "false").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def _generate_otp(length: int = 4) -> str:
    import random
    import string

    return "".join(random.choices(string.digits, k=length))


def _generate_temporary_password(length: int = 10) -> str:
    import random
    import string

    alphabet = string.ascii_letters + string.digits
    return "".join(random.choices(alphabet, k=length))


@router.post("/admin/signup")
async def admin_signup(payload: AdminSignupRequest):
    admins = get_system_admins_collection()
    guards = get_guards_collection()

    first_name_clean = " ".join(payload.first_name.strip().split())
    middle_name_clean = " ".join(payload.middle_name.strip().split())
    last_name_clean = " ".join(payload.last_name.strip().split())
    full_name_clean = " ".join(
        p for p in [first_name_clean, middle_name_clean, last_name_clean] if p
    )
    normalized_full_name = normalize_full_name(full_name_clean)
    normalized_email = normalize_email(payload.email)
    normalized_phone = normalize_phone(payload.phone_number)
    first_name_normalized = normalize_full_name(first_name_clean)
    middle_name_normalized = normalize_full_name(middle_name_clean)
    last_name_normalized = normalize_full_name(last_name_clean)

    if not normalized_full_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Full Name is required.",
        )

    verified_phone_user = await admins.find_one(
        {
            "phone_normalized": normalized_phone,
            "is_verified": True,
        }
    )
    if verified_phone_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=PHONE_ALREADY_REGISTERED_DETAIL,
        )

    existing_admin = await admins.find_one(
        {
            "phone_normalized": normalized_phone,
            "role": "admin",
        }
    )

    if existing_admin:
        otp = _generate_otp()
        otp_expires = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MINUTES)
        update_doc = {
            "first_name": first_name_clean,
            "middle_name": middle_name_clean,
            "last_name": last_name_clean,
            "first_name_normalized": first_name_normalized,
            "middle_name_normalized": middle_name_normalized,
            "last_name_normalized": last_name_normalized,
            "full_name": full_name_clean,
            "normalized_full_name": normalized_full_name,
            "email": payload.email,
            "email_normalized": normalized_email,
            "otp": otp,
            "otp_expires": otp_expires,
            "is_verified": False,
            "preferred_language": normalize_guard_language(existing_admin.get("preferred_language")),
            "session_active": False,
            "last_logout": datetime.utcnow(),
        }
        try:
            await admins.update_one(
                {"_id": existing_admin["_id"]},
                {"$set": update_doc},
            )
        except DuplicateKeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_duplicate_identity_detail_from_error(exc),
            ) from exc

        await asyncio.to_thread(smtp_send_otp, payload.email, otp)
        return {
            "message": "Administrator signup successful. OTP sent to email.",
            "email": payload.email,
        }

    await enforce_unique_identity_across_roles(
        system_admins_collection=admins,
        guards_collection=guards,
        full_name=normalized_full_name,
        first_name=first_name_clean,
        middle_name=middle_name_clean,
        last_name=last_name_clean,
        email=normalized_email,
        phone_number=normalized_phone,
    )

    otp = _generate_otp()
    otp_expires = datetime.utcnow() + timedelta(minutes=10)

    insert_doc = {
        "first_name": first_name_clean,
        "middle_name": middle_name_clean,
        "last_name": last_name_clean,
        "first_name_normalized": first_name_normalized,
        "middle_name_normalized": middle_name_normalized,
        "last_name_normalized": last_name_normalized,
        "full_name": full_name_clean,
        "normalized_full_name": normalized_full_name,
        "email": payload.email,
        "email_normalized": normalized_email,
        "phone_number": payload.phone_number.strip(),
        "phone_normalized": normalized_phone,
        "hashed_password": get_password_hash(payload.password),
        "otp": otp,
        "otp_expires": otp_expires,
        "is_verified": False,
        "role": "admin",
        "preferred_language": "en",
        "session_active": False,
        "last_logout": None,
        "created_at": datetime.utcnow(),
    }

    try:
        await admins.insert_one(insert_doc)
    except DuplicateKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_duplicate_identity_detail_from_error(exc),
        ) from exc
    await asyncio.to_thread(smtp_send_otp, payload.email, otp)

    return {
        "message": "Administrator signup successful. OTP sent to email.",
        "email": payload.email,
    }


@router.post("/admin/login")
async def admin_login(payload: AdminLoginRequest):
    admins = get_system_admins_collection()
    email_normalized = normalize_email(payload.email)
    admin = await admins.find_one({"email_normalized": email_normalized, "role": "admin"})
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not verify_password(payload.password, admin.get("hashed_password", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not admin.get("is_verified", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please complete OTP verification.",
        )

    now = datetime.utcnow()
    await admins.update_many(
        {
            "role": "admin",
            "session_active": True,
            "email_normalized": {"$ne": email_normalized},
        },
        {
            "$set": {
                "session_active": False,
                "last_logout": now,
            }
        },
    )
    await admins.update_one(
        {"_id": admin["_id"]},
        {
            "$set": {
                "last_login": now,
                "session_active": True,
            },
            "$unset": {"last_logout": ""},
        },
    )

    access_token = create_access_token(
        {
            "sub": str(admin.get("_id")),
            "role": "admin",
            "email": admin.get("email"),
        },
        expires_delta=timedelta(minutes=60),
    )

    return Token(
        access_token=access_token,
        email=admin.get("email"),
        full_name=admin.get("full_name"),
        role="admin",
    )


@router.post("/admin/forgot-password")
async def admin_forgot_password(payload: AdminForgotPasswordRequest):
    admins = get_system_admins_collection()
    email_normalized = normalize_email(payload.email)
    admin = await admins.find_one({"email_normalized": email_normalized, "role": "admin"})

    if not admin:
        raise HTTPException(status_code=404, detail="Administrator not found.")

    temp_password = _generate_temporary_password()
    old_hash = admin.get("hashed_password", "")
    now = datetime.utcnow()

    await admins.update_one(
        {"_id": admin["_id"]},
        {
            "$set": {
                "hashed_password": get_password_hash(temp_password),
                "session_active": False,
                "last_logout": now,
            }
        },
    )

    email_subject = "Campus Guard AI - Temporary Admin Password"
    email_body = (
        f"Hello {admin.get('full_name') or 'Administrator'},\n\n"
        "A password reset was requested for your admin account.\n"
        f"Temporary password: {temp_password}\n\n"
        "Please login and change this password immediately.\n"
        "If you did not request this, contact system support right away.\n"
    )

    sent = await asyncio.to_thread(
        send_email,
        str(admin.get("email") or payload.email),
        email_subject,
        email_body,
    )

    if not sent:
        await admins.update_one(
            {"_id": admin["_id"]},
            {"$set": {"hashed_password": old_hash}},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to send temporary password email. Please try again.",
        )

    return {
        "message": "A temporary password has been sent to your registered email.",
    }


@router.post("/admin/verify-otp")
async def admin_verify_otp(payload: AdminVerifyOtpRequest):
    admins = get_system_admins_collection()
    email_normalized = normalize_email(payload.email)
    admin = await admins.find_one({"email_normalized": email_normalized, "role": "admin"})

    if not admin:
        raise HTTPException(status_code=404, detail="Administrator not found.")

    stored_otp = str(admin.get("otp") or "")
    otp_expires = admin.get("otp_expires")

    if not stored_otp or stored_otp != payload.otp:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP.")

    if not otp_expires or otp_expires < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired OTP.")

    now = datetime.utcnow()
    await admins.update_many(
        {
            "role": "admin",
            "session_active": True,
            "email_normalized": {"$ne": email_normalized},
        },
        {
            "$set": {
                "session_active": False,
                "last_logout": now,
            }
        },
    )

    await admins.update_one(
        {"_id": admin["_id"]},
        {
            "$set": {
                "is_verified": True,
                "last_login": now,
                "session_active": True,
            },
            "$unset": {"otp": "", "otp_expires": "", "last_logout": ""},
        },
    )

    access_token = create_access_token(
        {
            "sub": str(admin.get("_id")),
            "role": "admin",
            "email": admin.get("email"),
        },
        expires_delta=timedelta(minutes=60),
    )

    return Token(
        access_token=access_token,
        email=admin.get("email"),
        full_name=admin.get("full_name"),
        role="admin",
    )


@router.post("/admin/logout")
async def admin_logout(payload: AdminLogoutRequest):
    admins = get_system_admins_collection()
    email_normalized = normalize_email(payload.email)
    admin = await admins.find_one({"email_normalized": email_normalized, "role": "admin"})
    if not admin:
        raise HTTPException(status_code=404, detail="Administrator not found.")

    now = datetime.utcnow()
    await admins.update_one(
        {"_id": admin["_id"]},
        {
            "$set": {
                "session_active": False,
                "last_logout": now,
            }
        },
    )

    return {
        "message": "Admin signed out.",
        "email": admin.get("email"),
        "session_active": False,
        "last_logout": now,
    }


@router.post("/guard/login")
async def guard_login(payload: GuardLoginRequest):
    guards = get_guards_collection()
    admins = get_system_admins_collection()

    normalized_full_name = normalize_full_name(
        payload.first_name,
        payload.middle_name,
        payload.last_name,
    )
    normalized_phone = normalize_phone(payload.phone_number)

    if not normalized_full_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Full Name is required.",
        )

    if not normalized_phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone Number is required.",
        )

    verified_phone_user = await guards.find_one(
        {
            "phone_normalized": normalized_phone,
            "is_verified": True,
        }
    )
    if verified_phone_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=PHONE_ALREADY_REGISTERED_DETAIL,
        )

    existing_guard = await guards.find_one({"phone_normalized": normalized_phone, "role": "guard"})

    if existing_guard is None:
        await enforce_unique_identity_across_roles(
            system_admins_collection=admins,
            guards_collection=guards,
            full_name=normalized_full_name,
            first_name=payload.first_name,
            middle_name=payload.middle_name,
            last_name=payload.last_name,
            phone_number=normalized_phone,
        )

        display_name = " ".join(
            part.strip() for part in [payload.first_name, payload.middle_name, payload.last_name] if part.strip()
        )

        insert_doc = {
            "first_name": payload.first_name.strip(),
            "middle_name": payload.middle_name.strip(),
            "last_name": payload.last_name.strip(),
            "first_name_normalized": normalize_full_name(payload.first_name),
            "middle_name_normalized": normalize_full_name(payload.middle_name),
            "last_name_normalized": normalize_full_name(payload.last_name),
            "full_name": display_name,
            "normalized_full_name": normalized_full_name,
            "phone_number": payload.phone_number.strip(),
            "phone_normalized": normalized_phone,
            "email": None,
            "email_normalized": None,
            "role": "guard",
            "is_verified": False,
            "isOnDuty": False,
            "preferred_language": "en",
            "welcome_message_sent": False,
            "created_at": datetime.utcnow(),
        }
        try:
            result = await guards.insert_one(insert_doc)
        except DuplicateKeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_duplicate_identity_detail_from_error(exc),
            ) from exc
        existing_guard = await guards.find_one({"_id": result.inserted_id})
    else:
        display_name = " ".join(
            part.strip() for part in [payload.first_name, payload.middle_name, payload.last_name] if part.strip()
        )
        try:
            await guards.update_one(
                {"_id": existing_guard["_id"]},
                {
                    "$set": {
                        "first_name": payload.first_name.strip(),
                        "middle_name": payload.middle_name.strip(),
                        "last_name": payload.last_name.strip(),
                        "first_name_normalized": normalize_full_name(payload.first_name),
                        "middle_name_normalized": normalize_full_name(payload.middle_name),
                        "last_name_normalized": normalize_full_name(payload.last_name),
                        "full_name": display_name,
                        "normalized_full_name": normalized_full_name,
                        "phone_number": payload.phone_number.strip(),
                    }
                },
            )
        except DuplicateKeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_duplicate_identity_detail_from_error(exc),
            ) from exc

    otp = _generate_otp()
    otp_expires = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MINUTES)
    now = datetime.utcnow()
    await guards.update_one(
        {"_id": existing_guard["_id"]},
        {
            "$set": {
                "otp": otp,
                "otp_expires": otp_expires,
                "otp_attempts": 0,
                "otp_locked_until": None,
                "last_otp_sent_at": now,
                "whatsapp_enabled": bool(existing_guard.get("whatsapp_enabled", True)),
                "preferred_language": normalize_guard_language(existing_guard.get("preferred_language")),
            }
        },
    )

    guard_language = normalize_guard_language(
        existing_guard.get("preferred_language"))

    message_sent = await asyncio.to_thread(
        send_whatsapp,
        payload.phone_number,
        build_guard_otp_message(otp, guard_language, OTP_EXPIRY_MINUTES),
    )

    if not message_sent:
        if _should_expose_otp_preview():
            return {
                "message": "WhatsApp delivery unavailable. Use otp_preview only in non-production environments.",
                "phone_number": payload.phone_number,
                "otp_preview": otp,
            }
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to send OTP to WhatsApp. Check WAHA service/session connectivity, then try again.",
        )

    response = {
        "message": "OTP sent to WhatsApp number.",
        "phone_number": payload.phone_number,
    }

    if _should_expose_otp_preview():
        response["otp_preview"] = otp

    return response


@router.post("/guard/signin")
async def guard_signin(payload: GuardSignInRequest):
    guards = get_guards_collection()
    normalized_phone = normalize_phone(payload.phone_number)

    if not normalized_phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone Number is required.",
        )

    guard = await guards.find_one({"phone_normalized": normalized_phone, "role": "guard"})
    if not guard:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Guard profile not found. Please complete guard signup first.",
        )

    otp = _generate_otp()
    now = datetime.utcnow()
    otp_expires = now + timedelta(minutes=OTP_EXPIRY_MINUTES)

    await guards.update_one(
        {"_id": guard["_id"]},
        {
            "$set": {
                "otp": otp,
                "otp_expires": otp_expires,
                "otp_attempts": 0,
                "otp_locked_until": None,
                "last_otp_sent_at": now,
                "whatsapp_enabled": bool(guard.get("whatsapp_enabled", True)),
                "preferred_language": normalize_guard_language(guard.get("preferred_language")),
            }
        },
    )

    guard_language = normalize_guard_language(guard.get("preferred_language"))

    message_sent = await asyncio.to_thread(
        send_whatsapp,
        payload.phone_number,
        build_guard_otp_message(otp, guard_language, OTP_EXPIRY_MINUTES),
    )

    if not message_sent:
        if _should_expose_otp_preview():
            return {
                "message": "WhatsApp delivery unavailable. Use otp_preview only in non-production environments.",
                "phone_number": payload.phone_number,
                "otp_preview": otp,
            }
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to send OTP to WhatsApp. Check WAHA service/session connectivity, then try again.",
        )

    response = {
        "message": "Sign in OTP sent to WhatsApp number.",
        "phone_number": payload.phone_number,
    }
    if _should_expose_otp_preview():
        response["otp_preview"] = otp
    return response


@router.post("/guard/resend-otp")
async def guard_resend_otp(payload: GuardResendOtpRequest):
    guards = get_guards_collection()
    normalized_phone = normalize_phone(payload.phone_number)
    guard = await guards.find_one({"phone_normalized": normalized_phone, "role": "guard"})

    if not guard:
        raise HTTPException(status_code=404, detail="Guard not found.")

    now = datetime.utcnow()
    last_sent_at = guard.get("last_otp_sent_at")
    if last_sent_at and isinstance(last_sent_at, datetime):
        elapsed = (now - last_sent_at).total_seconds()
        if elapsed < OTP_RESEND_COOLDOWN_SECONDS:
            wait_seconds = int(OTP_RESEND_COOLDOWN_SECONDS - elapsed)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Please wait {wait_seconds}s before requesting a new OTP.",
            )

    otp = _generate_otp()
    otp_expires = now + timedelta(minutes=OTP_EXPIRY_MINUTES)

    await guards.update_one(
        {"_id": guard["_id"]},
        {
            "$set": {
                "otp": otp,
                "otp_expires": otp_expires,
                "otp_attempts": 0,
                "otp_locked_until": None,
                "last_otp_sent_at": now,
                "preferred_language": normalize_guard_language(guard.get("preferred_language")),
            }
        },
    )

    guard_language = normalize_guard_language(guard.get("preferred_language"))

    message_sent = await asyncio.to_thread(
        send_whatsapp,
        payload.phone_number,
        build_guard_otp_message(otp, guard_language, OTP_EXPIRY_MINUTES),
    )
    if not message_sent:
        if _should_expose_otp_preview():
            return {
                "message": "WhatsApp delivery unavailable. Use otp_preview only in non-production environments.",
                "phone_number": payload.phone_number,
                "otp_preview": otp,
            }
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to send OTP to WhatsApp. Check WAHA service/session connectivity, then try again.",
        )

    response = {
        "message": "OTP resent to WhatsApp number.",
        "phone_number": payload.phone_number,
    }
    if _should_expose_otp_preview():
        response["otp_preview"] = otp
    return response


@router.post("/guard/verify-otp")
async def guard_verify_otp(payload: GuardVerifyOtpRequest):
    guards = get_guards_collection()
    normalized_phone = normalize_phone(payload.phone_number)
    guard = await guards.find_one({"phone_normalized": normalized_phone, "role": "guard"})

    if not guard:
        raise HTTPException(status_code=404, detail="Guard not found.")

    now = datetime.utcnow()
    otp_locked_until = guard.get("otp_locked_until")
    if otp_locked_until and isinstance(otp_locked_until, datetime) and otp_locked_until > now:
        remaining = int((otp_locked_until - now).total_seconds() // 60) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many invalid attempts. Try again in {remaining} minutes.",
        )

    stored_otp = str(guard.get("otp") or "")
    otp_expires = guard.get("otp_expires")

    if not stored_otp or stored_otp != payload.otp:
        attempts = int(guard.get("otp_attempts") or 0) + 1
        update_doc: dict = {"otp_attempts": attempts}
        if attempts >= OTP_MAX_ATTEMPTS:
            update_doc["otp_locked_until"] = now + \
                timedelta(minutes=OTP_LOCK_MINUTES)
        await guards.update_one({"_id": guard["_id"]}, {"$set": update_doc})
        raise HTTPException(status_code=400, detail="Invalid or expired OTP.")

    if not otp_expires or otp_expires < now:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP.")

    guard_language = normalize_guard_language(guard.get("preferred_language"))
    was_verified_before = bool(guard.get("is_verified", False))
    welcome_message_sent = bool(guard.get("welcome_message_sent", False))
    has_welcome_flag = "welcome_message_sent" in guard

    await guards.update_one(
        {"_id": guard["_id"]},
        {
            "$set": {
                "is_verified": True,
                "last_login": now,
                "otp_attempts": 0,
                "otp_locked_until": None,
                "whatsapp_enabled": True,
                "preferred_language": guard_language,
            },
            "$unset": {"otp": "", "otp_expires": "", "last_otp_sent_at": ""},
        },
    )

    # For legacy verified guards that predate welcome tracking, avoid sending welcome again.
    if was_verified_before and not has_welcome_flag:
        await guards.update_one(
            {"_id": guard["_id"]},
            {"$set": {"welcome_message_sent": True}},
        )
    elif (not was_verified_before) and (not welcome_message_sent):
        try:
            onboarding_sent = await asyncio.to_thread(
                send_whatsapp,
                payload.phone_number,
                build_guard_onboarding_message(
                    guard.get("full_name"), guard_language),
            )
            if onboarding_sent:
                await guards.update_one(
                    {"_id": guard["_id"]},
                    {"$set": {"welcome_message_sent": True}},
                )
            else:
                print(
                    f"[ROLE_AUTH] Onboarding WhatsApp not delivered for guard {guard.get('_id')}"
                )
        except Exception as exc:
            print(
                f"[ROLE_AUTH] Failed to send onboarding WhatsApp for guard {guard.get('_id')}: {exc}"
            )

    access_token = create_access_token(
        {
            "sub": str(guard.get("_id")),
            "role": "guard",
            "phone": guard.get("phone_number"),
        },
        expires_delta=timedelta(minutes=60),
    )

    return Token(
        access_token=access_token,
        full_name=guard.get("full_name"),
        role="guard",
    )
