import asyncio
from datetime import datetime, timezone
from typing import Any
import os

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
import requests

try:
    from ..database import get_db, get_system_admins_collection
    from ..utils.security import decode_access_token
except ImportError:
    from database import get_db, get_system_admins_collection
    from utils.security import decode_access_token


router = APIRouter(prefix="", tags=["admin-notifications"])


LOCKDOWN_ALERT_TYPE = "SOS_LOCKDOWN"
LOCKDOWN_ACK_STATUSES = {
    "acknowledged",
    "responding",
    "resolved",
    "dismissed",
    "false_alarm",
}
WAHA_ALERT_RESPONDING_BUTTON_ID = "alert_responding"
LOCKDOWN_MAX_ATTEMPTS = 3

LOCKDOWN_MESSAGES = {
    "en": {
        1: "🚨 CRITICAL: CAMPUS LOCKDOWN. Reply RESPONDING or SAFE.",
        2: "URGENT REMINDER: Lockdown unacknowledged. Reply RESPONDING.",
        3: "FINAL WARNING: Escalating to Supervisor.",
    },
    "mr": {
        1: "🚨 अत्यंत महत्त्वाचे: कॅम्पस लॉकडाऊन. कृपया 'RESPONDING' किंवा 'SAFE' असे उत्तर द्या.",
        2: "तातडीची आठवण: लॉकडाऊनला प्रतिसाद मिळालेला नाही. कृपया 'RESPONDING' उत्तर द्या.",
        3: "अंतिम इशारा: पर्यवेक्षकाला (Supervisor) कळवत आहोत.",
    },
    "hi": {
        1: "🚨 अति आवश्यक: कैंपस लॉकडाउन। कृपया 'RESPONDING' या 'SAFE' लिखकर उत्तर दें।",
        2: "अति आवश्यक अनुस्मारक: लॉकडाउन का कोई उत्तर नहीं मिला। कृपया 'RESPONDING' उत्तर दें।",
        3: "अंतिम चेतावनी: सुपरवाइजर को सूचित किया जा रहा है।",
    },
}


class LockdownTriggerRequest(BaseModel):
    triggered_by: str = Field(min_length=1)


def _normalize_phone_digits(value: str | None) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _waha_base_url() -> str:
    return str(os.getenv("WAHA_API_URL", "http://localhost:3000")).strip().rstrip("/")


def _waha_session_name() -> str:
    return str(os.getenv("WAHA_SESSION", "default")).strip() or "default"


def _waha_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = str(os.getenv("WAHA_API_KEY", "")).strip()
    if api_key:
        headers["X-Api-Key"] = api_key
    return headers


def _waha_timeout_sec() -> float:
    raw = str(os.getenv("WAHA_TIMEOUT_SEC", "10")).strip()
    try:
        value = float(raw)
    except Exception:
        value = 10.0
    return max(2.0, min(30.0, value))


def _waha_send_text(chat_digits: str, text: str) -> tuple[bool, str | None]:
    chat_id = f"{_normalize_phone_digits(chat_digits)}@c.us"
    payload = {
        "chatId": chat_id,
        "text": text,
        "session": _waha_session_name(),
    }
    response = requests.post(
        f"{_waha_base_url()}/api/sendText",
        json=payload,
        headers=_waha_headers(),
        timeout=_waha_timeout_sec(),
    )
    if response.ok:
        return True, None
    return False, f"status={response.status_code} body={response.text[:250]}"


def _waha_send_lockdown_button(chat_digits: str, alert_id: str) -> tuple[bool, str | None]:
    chat_id = f"{_normalize_phone_digits(chat_digits)}@c.us"
    payload = {
        "chatId": chat_id,
        "session": _waha_session_name(),
        "title": "CAMPUS LOCKDOWN",
        "body": "Emergency lockdown active. Tap RESPONDING immediately.",
        "footer": "Campus Security Control Room",
        "buttons": [
            {
                "id": f"{WAHA_ALERT_RESPONDING_BUTTON_ID}:{alert_id}",
                "text": "RESPONDING",
            }
        ],
    }
    response = requests.post(
        f"{_waha_base_url()}/api/sendButtons",
        json=payload,
        headers=_waha_headers(),
        timeout=_waha_timeout_sec(),
    )
    if response.ok:
        return True, None
    return False, f"status={response.status_code} body={response.text[:250]}"


def _normalize_language_code(value: str | None) -> str:
    code = str(value or "").strip().lower()
    return code if code in LOCKDOWN_MESSAGES else "en"


def _lockdown_message_for_guard(guard: dict[str, Any], attempt: int) -> str:
    language_code = _normalize_language_code(
        guard.get("preferred_language")
        or guard.get("language")
        or (guard.get("settings") or {}).get("preferred_language")
    )
    return LOCKDOWN_MESSAGES.get(language_code, LOCKDOWN_MESSAGES["en"]).get(
        int(attempt), LOCKDOWN_MESSAGES["en"][1]
    )


async def _send_lockdown_broadcast(alert_id: str, guards: list[dict[str, Any]], attempt: int) -> dict[str, int]:
    sent = 0
    failed = 0

    for guard in guards:
        phone_digits = _normalize_phone_digits(
            str(guard.get("phone_number") or guard.get("phone_normalized") or "")
        )
        if not phone_digits:
            continue

        localized_message = _lockdown_message_for_guard(guard, attempt)

        text_ok, _ = await asyncio.to_thread(
            _waha_send_text, phone_digits, localized_message)
        button_ok, _ = await asyncio.to_thread(_waha_send_lockdown_button, phone_digits, alert_id)
        if text_ok or button_ok:
            sent += 1
        else:
            failed += 1

    return {"sent": sent, "failed": failed}


async def _is_lockdown_acknowledged(alert_id: str) -> bool:
    db = get_db()
    alerts = db["alerts"]
    try:
        object_id = ObjectId(alert_id)
    except Exception:
        return False

    doc = await alerts.find_one({"_id": object_id}, {"status": 1})
    if not doc:
        return False

    status_value = str(doc.get("status") or "").strip().lower()
    return status_value in LOCKDOWN_ACK_STATUSES


async def _get_lockdown_status(alert_id: str) -> str | None:
    db = get_db()
    alerts = db["alerts"]
    try:
        object_id = ObjectId(alert_id)
    except Exception:
        return None

    doc = await alerts.find_one({"_id": object_id}, {"status": 1})
    if not doc:
        return None
    return str(doc.get("status") or "").strip().lower() or None


async def _execute_lockdown_escalation(alert_id: str, triggered_by: str) -> None:
    db = get_db()
    users = db["users"]
    alerts = db["alerts"]

    try:
        object_id = ObjectId(alert_id)
    except Exception:
        return

    try:
        cursor = users.find(
            {
                "role": "guard",
                "is_verified": True,
                "isOnDuty": True,
                "whatsapp_enabled": {"$ne": False},
            },
            {
                "phone_number": 1,
                "phone_normalized": 1,
                "preferred_language": 1,
                "language": 1,
                "settings.preferred_language": 1,
            },
        )
        guards = await cursor.to_list(length=300)

        for attempt in range(1, LOCKDOWN_MAX_ATTEMPTS + 1):
            if await _is_lockdown_acknowledged(alert_id):
                await alerts.update_one(
                    {"_id": object_id},
                    {
                        "$set": {
                            "escalation_state": "acknowledged",
                            "escalation_stopped_at": datetime.now(timezone.utc),
                        }
                    },
                )
                return

            wave_result = await _send_lockdown_broadcast(
                alert_id, guards, attempt=attempt)

            set_payload: dict[str, Any] = {
                "escalation_last_attempt_at": datetime.now(timezone.utc),
                "escalation_attempt": int(attempt),
                "escalation_state": f"attempt_{attempt}_sent",
            }
            if attempt == 1:
                set_payload["escalation_first_wave_sent"] = int(
                    wave_result.get("sent", 0))
                set_payload["escalation_first_wave_failed"] = int(
                    wave_result.get("failed", 0))
            elif attempt == 2:
                set_payload["escalation_second_wave_sent"] = int(
                    wave_result.get("sent", 0))
                set_payload["escalation_second_wave_failed"] = int(
                    wave_result.get("failed", 0))
            else:
                set_payload["escalation_third_wave_sent"] = int(
                    wave_result.get("sent", 0))
                set_payload["escalation_third_wave_failed"] = int(
                    wave_result.get("failed", 0))

            await alerts.update_one(
                {"_id": object_id},
                {"$set": set_payload},
            )

            if attempt < LOCKDOWN_MAX_ATTEMPTS:
                await asyncio.sleep(30)

        final_status = await _get_lockdown_status(alert_id)
        if final_status in LOCKDOWN_ACK_STATUSES:
            await alerts.update_one(
                {"_id": object_id},
                {
                    "$set": {
                        "escalation_state": "acknowledged",
                        "escalation_stopped_at": datetime.now(timezone.utc),
                    }
                },
            )
            return

        if final_status not in {"active", "pending"}:
            await alerts.update_one(
                {"_id": object_id},
                {
                    "$set": {
                        "escalation_state": "stopped_non_active",
                        "escalation_stopped_at": datetime.now(timezone.utc),
                        "escalation_stop_reason": f"status={final_status}",
                    }
                },
            )
            return

        # TODO: Twilio Voice/SMS fallback should be triggered here if third reminder still unacknowledged.
        await alerts.update_one(
            {"_id": object_id},
            {
                "$set": {
                    "escalation_state": "fallback_pending",
                    "fallback_channel": "twilio_stub",
                    "fallback_required_at": datetime.now(timezone.utc),
                }
            },
        )
    except Exception as exc:
        await alerts.update_one(
            {"_id": object_id},
            {
                "$set": {
                    "escalation_state": "error",
                    "escalation_error": str(exc),
                    "escalation_failed_at": datetime.now(timezone.utc),
                }
            },
        )


@router.post("/api/lockdown")
async def trigger_lockdown(payload: LockdownTriggerRequest, background_tasks: BackgroundTasks, request: Request):
    db = get_db()
    alerts = db["alerts"]

    auth_header = str(request.headers.get("Authorization") or "").strip()
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = auth_header.split(" ", 1)[1].strip()
    token_payload = decode_access_token(token)
    if not token_payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    token_role = str(token_payload.get("role") or "").strip().lower()
    if token_role != "admin":
        raise HTTPException(
            status_code=403, detail="Only admins can trigger lockdown")

    token_sub = str(token_payload.get("sub") or "").strip()
    token_email = str(token_payload.get("email") or "").strip().lower()
    triggered_by = token_sub or token_email or str(
        payload.triggered_by or "system").strip() or "system"
    now = datetime.now(timezone.utc)

    lockdown_doc = {
        "type": LOCKDOWN_ALERT_TYPE,
        "status": "active",
        "severity": "critical",
        "triggered_by": triggered_by,
        "triggered_by_claim": str(payload.triggered_by or "").strip() or None,
        "timestamp": now,
        "message": "Campus lockdown escalation initiated",
        "escalation_state": "queued",
        "action_history": [
            {
                "action": "lockdown_triggered",
                "by": triggered_by,
                "source": "admin_ui",
                "timestamp": now,
            }
        ],
    }

    try:
        result = await alerts.insert_one(lockdown_doc)
        alert_id = str(result.inserted_id)
        background_tasks.add_task(
            _execute_lockdown_escalation, alert_id, triggered_by)

        await notify_admins(
            {
                "type": "SOS_LOCKDOWN_TRIGGERED",
                "status": "active",
                "alert_id": alert_id,
                "triggered_by": triggered_by,
            }
        )

        return {
            "ok": True,
            "alert_id": alert_id,
            "status": "active",
            "message": "Lockdown activated. Escalation started in background.",
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "message": f"Failed to activate lockdown: {exc}",
        }


class AdminConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        async with self._lock:
            sockets = list(self._connections)

        if not sockets:
            return

        dead: list[WebSocket] = []
        for socket in sockets:
            try:
                await socket.send_json(message)
            except (WebSocketDisconnect, RuntimeError):
                dead.append(socket)
            except Exception:
                dead.append(socket)

        if dead:
            async with self._lock:
                for socket in dead:
                    self._connections.discard(socket)


manager = AdminConnectionManager()


async def notify_admins(message: dict[str, Any]) -> None:
    payload = dict(message or {})
    payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    await manager.broadcast(payload)


async def _reject_websocket(websocket: WebSocket, reason: str) -> None:
    # Accept first so failures are returned as WebSocket close codes instead of
    # HTTP handshake 403 rejections.
    await websocket.accept()
    await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=reason)


async def _authenticate_admin_websocket(
    websocket: WebSocket,
    token: str | None = Query(default=None),
) -> dict[str, Any] | None:
    # Prefer FastAPI query parsing; fallback to raw query params for compatibility.
    ws_token = str(token or websocket.query_params.get("token") or "").strip()
    if not ws_token:
        await _reject_websocket(websocket, "missing_token")
        return None

    # decode_access_token uses SECRET_KEY and ALGORITHM from Backend utils config/.env.
    payload = decode_access_token(ws_token)
    if not payload:
        await _reject_websocket(websocket, "invalid_token")
        return None

    if str(payload.get("role") or "").strip().lower() != "admin":
        await _reject_websocket(websocket, "forbidden_role")
        return None

    admin_id = str(payload.get("sub") or "").strip()
    if not admin_id:
        await _reject_websocket(websocket, "invalid_subject")
        return None

    admins = get_system_admins_collection()
    admin_doc = None
    try:
        admin_doc = await admins.find_one(
            {"_id": ObjectId(admin_id), "role": "admin"}
        )
    except Exception:
        admin_doc = await admins.find_one({"_id": admin_id, "role": "admin"})

    if not admin_doc:
        await _reject_websocket(websocket, "admin_not_found")
        return None

    return admin_doc


@router.websocket("/ws/admin-notifications")
async def admin_notifications_websocket(
    websocket: WebSocket,
    admin_doc: dict[str, Any] | None = Depends(_authenticate_admin_websocket),
) -> None:
    if admin_doc is None:
        return

    await manager.connect(websocket)

    await websocket.send_json(
        {
            "type": "CONNECTED",
            "message": "Admin notifications channel connected",
            "admin_email": admin_doc.get("email"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )

    try:
        while True:
            message = await websocket.receive_text()
            if str(message or "").strip().lower() == "ping":
                continue
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await manager.disconnect(websocket)
