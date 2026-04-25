from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status


DUPLICATE_FULL_NAME_DETAIL = "This full name is already registered. Use a unique full name."
DUPLICATE_EMAIL_DETAIL = "This email is already registered."
DUPLICATE_PHONE_DETAIL = "This phone number is already registered."


def normalize_full_name(*parts: Optional[str]) -> str:
    merged = " ".join((part or "").strip() for part in parts)
    return " ".join(merged.split()).lower()


def normalize_name_part(value: Optional[str]) -> str:
    return " ".join((value or "").strip().split()).lower()


def normalize_email(email: Optional[str]) -> str:
    return (email or "").strip().lower()


def normalize_phone(phone: Optional[str]) -> str:
    # Keep only digits for exact identity checks.
    return "".join(ch for ch in (phone or "") if ch.isdigit())


async def _find_conflict(collection, field: str, value: str):
    if not value:
        return None
    return await collection.find_one({field: value})


async def enforce_unique_identity_across_roles(
    *,
    system_admins_collection,
    guards_collection,
    full_name: Optional[str] = None,
    first_name: Optional[str] = None,
    middle_name: Optional[str] = None,
    last_name: Optional[str] = None,
    email: Optional[str] = None,
    phone_number: Optional[str] = None,
) -> None:
    norm_first_name = normalize_name_part(first_name)
    norm_middle_name = normalize_name_part(middle_name)
    norm_last_name = normalize_name_part(last_name)
    norm_full_name = normalize_full_name(full_name) or normalize_full_name(
        norm_first_name,
        norm_middle_name,
        norm_last_name,
    )
    norm_email = normalize_email(email)
    norm_phone = normalize_phone(phone_number)

    if norm_first_name and norm_last_name:
        triplet_query = {
            "first_name_normalized": norm_first_name,
            "middle_name_normalized": norm_middle_name,
            "last_name_normalized": norm_last_name,
        }
        if await system_admins_collection.find_one(triplet_query):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=DUPLICATE_FULL_NAME_DETAIL,
            )
        # Skip duplicate lookup when both role collections are same physical collection.
        if guards_collection is not system_admins_collection and await guards_collection.find_one(triplet_query):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=DUPLICATE_FULL_NAME_DETAIL,
            )

    if norm_full_name:
        if await _find_conflict(system_admins_collection, "normalized_full_name", norm_full_name):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=DUPLICATE_FULL_NAME_DETAIL,
            )
        if await _find_conflict(guards_collection, "normalized_full_name", norm_full_name):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=DUPLICATE_FULL_NAME_DETAIL,
            )

    if norm_email:
        if await _find_conflict(system_admins_collection, "email_normalized", norm_email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=DUPLICATE_EMAIL_DETAIL,
            )
        if await _find_conflict(guards_collection, "email_normalized", norm_email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=DUPLICATE_EMAIL_DETAIL,
            )

    if norm_phone:
        if await _find_conflict(system_admins_collection, "phone_normalized", norm_phone):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=DUPLICATE_PHONE_DETAIL,
            )
        if await _find_conflict(guards_collection, "phone_normalized", norm_phone):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=DUPLICATE_PHONE_DETAIL,
            )
