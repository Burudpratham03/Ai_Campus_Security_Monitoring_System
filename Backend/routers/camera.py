import threading
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
import base64
from ultralytics import YOLO
from fastapi.responses import StreamingResponse
from fastapi import APIRouter, Request, File, UploadFile, HTTPException
import asyncio
import queue
from threading import Thread, Lock
import numpy as np
import cv2
import logging
import json
import mimetypes
import os
import requests
import shutil
import time
from typing import AsyncGenerator, Any
from pathlib import Path
from datetime import datetime, timedelta, timezone

try:
    import google.generativeai as genai
except Exception:
    genai = None

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

try:
    import torch
except Exception:
    torch = None


try:
    from ..database import get_alerts_collection
except ImportError:
    from database import get_alerts_collection


router = APIRouter(prefix="", tags=["camera"])

# Dedicated persistent event loop for async DB operations from the camera
# worker thread.  motor's AsyncIOMotorClient is bound to whichever loop it
# was first used on; running coroutines via asyncio.run() spins up a fresh
# loop each time, which silently breaks motor.  By keeping one background
# loop alive we ensure all DB calls share the same context.
_bg_loop = asyncio.new_event_loop()


def _start_bg_loop():
    asyncio.set_event_loop(_bg_loop)
    _bg_loop.run_forever()


threading.Thread(target=_start_bg_loop, daemon=True).start()


BASE_DIR = Path(__file__).resolve().parent.parent
ML_MODELS_DIR = BASE_DIR / "ml_models"
CAPTURES_DIR = BASE_DIR / "captures"  # Directory for storing frame captures

# Default camera/framerate configuration
# The system is tuned to a stable 30 FPS capture rate that matches the
# previous working behavior and keeps inference reliable on most hardware.
# (Environment-variable overrides were removed to ensure consistent behavior.)
DEFAULT_CAMERA_FPS = 30.0


def _read_int_env(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except Exception:
        return default


def _read_float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except Exception:
        value = default
    return min(maximum, max(minimum, value))


# Inference scheduling: avoid over-smoothing by processing at least every
# 3rd frame (or faster when possible). This keeps the models responsive.
DEFAULT_INFERENCE_FRAME_SKIP = int(
    os.environ.get("INFERENCE_FRAME_SKIP", "3"))

# Keep the capture resolution a bit below 720p so the full camera pipeline
# spends less time copying, annotating, and JPEG-encoding frames.
DEFAULT_CAMERA_FRAME_WIDTH = _read_int_env(
    "CAMERA_FRAME_WIDTH", 960, 320)
DEFAULT_CAMERA_FRAME_HEIGHT = _read_int_env(
    "CAMERA_FRAME_HEIGHT", 540, 240)

# Reduce model input size slightly so the four-model pipeline clears faster
# without materially changing detector behavior on typical camera feeds.
DEFAULT_INFERENCE_IMAGE_SIZE = _read_int_env(
    "INFERENCE_IMAGE_SIZE", 320, 320)

# Lower JPEG quality a bit to reduce encode overhead and stream latency.
DEFAULT_STREAM_JPEG_QUALITY = _read_int_env(
    "STREAM_JPEG_QUALITY", 72, 40)

# Motion gate sensitivity: lower values make detections trigger more easily.
# Instant detection mode: do not gate inference on motion percentage.
MIN_MOTION_PERCENT = 0.0

# Pick a safe inference device automatically.
USE_CUDA = bool(torch is not None and torch.cuda.is_available())
INFERENCE_DEVICE: int | str = 0 if USE_CUDA else "cpu"
INFERENCE_USE_HALF = USE_CUDA

ENABLE_AI_CUSTOM_GUARD_ALERTS = str(
    os.environ.get("ENABLE_AI_CUSTOM_GUARD_ALERTS", "true")
).strip().lower() not in {"0", "false", "no", "off"}
AI_GUARD_ALERT_TIMEOUT_SEC = _read_float_env(
    "AI_GUARD_ALERT_TIMEOUT_SEC", 8.0, 3.0, 20.0
)
AI_GUARD_ALERT_MAX_CHARS = _read_int_env(
    "AI_GUARD_ALERT_MAX_CHARS", 700, 300
)
AI_GUARD_ALERT_MODEL = str(
    os.environ.get("AI_GUARD_ALERT_MODEL", "models/gemini-1.5-flash-latest")
).strip() or "models/gemini-1.5-flash-latest"
ENABLE_AI_INCIDENT_NARRATIVE = str(
    os.environ.get("ENABLE_AI_INCIDENT_NARRATIVE", "true")
).strip().lower() not in {"0", "false", "no", "off"}
AI_INCIDENT_NARRATIVE_TIMEOUT_SEC = _read_float_env(
    "AI_INCIDENT_NARRATIVE_TIMEOUT_SEC", 12.0, 5.0, 30.0
)
AI_INCIDENT_NARRATIVE_MAX_CHARS = _read_int_env(
    "AI_INCIDENT_NARRATIVE_MAX_CHARS", 1200, 300
)
AI_INCIDENT_NARRATIVE_MODEL = str(
    os.environ.get("AI_INCIDENT_NARRATIVE_MODEL", AI_GUARD_ALERT_MODEL)
).strip() or AI_GUARD_ALERT_MODEL
WAHA_MAX_TEXT_CHARS = _read_int_env(
    "WAHA_MAX_TEXT_CHARS", 1700, 300
)

# allow camera source override (device index or URL) per camera.


def _parse_camera_source(value: str) -> int | str:
    try:
        return int(value)
    except Exception:
        return str(value)


CAMERA_SOURCE_0 = _parse_camera_source(
    str(os.environ.get("CAMERA_SOURCE_0", os.environ.get("CAMERA_SOURCE", "0"))))
CAMERA_SOURCE_1 = _parse_camera_source(
    str(os.environ.get("CAMERA_SOURCE_1", "1")))
CAMERA_SOURCES: dict[int, int | str] = {
    0: CAMERA_SOURCE_0,
    1: CAMERA_SOURCE_1,
}
CAMERA_LOCATIONS: dict[int, str] = {
    0: "Camera 1 Area",
    1: "Camera 2 Area",
}
# Dual-camera cross-verification window; match is instant once both cameras
# report same class inside this window.
MULTI_ANGLE_VERIFY_WINDOW_SEC = _read_float_env(
    "MULTI_ANGLE_VERIFY_WINDOW_SEC", 10.0, 1.0, 10.0
)

# Ensure captures directory exists
CAPTURES_DIR.mkdir(parents=True, exist_ok=True)


def _resolve_model_path(preferred: str, alternatives: list[str]) -> Path:
    """
    Try preferred filename first, then fall back to any alternatives that exist.
    This makes the backend robust to small naming differences in model filenames.
    """
    candidates = [preferred, *alternatives]
    for name in candidates:
        candidate_path = ML_MODELS_DIR / name
        if candidate_path.exists():
            return candidate_path
    # If nothing matched, raise a clear error listing what we looked for.
    tried = ", ".join(str(ML_MODELS_DIR / c) for c in candidates)
    raise FileNotFoundError(
        f"Could not find any YOLO model file. Tried: {tried}")


WEAPON_MODEL_PATH = _resolve_model_path(
    "weapon_new_2026.pt",
    [],
)
FIRE_MODEL_PATH = _resolve_model_path(
    "fire.pt",
    ["fire.pt"],
)

ANOMALY_MODEL_PATH = _resolve_model_path(
    "anomaly.pt",
    ["anomaly.pt"],
)
VIOLENCE_MODEL_PATH = _resolve_model_path(
    "voilence.pt",
    ["violence.pt", "violence_model.pt"],
)

# Attempt to load models but keep the server running if they fail.
weapon_model = None
fire_model = None
anomaly_model = None
violence_model = None
try:
    weapon_model = YOLO(str(WEAPON_MODEL_PATH))
except Exception as exc:
    print(f"[CAMERA] Failed to load weapon model {WEAPON_MODEL_PATH}: {exc}")

try:
    fire_model = YOLO(str(FIRE_MODEL_PATH))
except Exception as exc:
    print(f"[CAMERA] Failed to load fire model {FIRE_MODEL_PATH}: {exc}")

try:
    anomaly_model = YOLO(str(ANOMALY_MODEL_PATH))
except Exception as exc:
    print(f"[CAMERA] Failed to load anomaly model {ANOMALY_MODEL_PATH}: {exc}")

try:
    violence_model = YOLO(str(VIOLENCE_MODEL_PATH))
except Exception as exc:
    print(
        f"[CAMERA] Failed to load violence model {VIOLENCE_MODEL_PATH}: {exc}")


# Track detection times for fire.
detection_tracker = {
    "fire": {"start_time": None, "captured": False},
}

# Notification timestamps for alert types.
# keys are type-level values like "weapon" or "fire". Used to enforce cooldown.
_last_notification_time: dict[str, float] = {}

# Keep track of warnings that should only be logged once to prevent per-frame spam.
_logged_result_shape_warnings: set[str] = set()

# Model-specific timing settings (seconds)
# 5 minutes – immediate first alert, then block repeats
WEAPON_ALERT_COOLDOWN = 300.0
ANOMALY_ALERT_COOLDOWN = 30.0
FIRE_ALERT_COOLDOWN = 30.0
VIOLENCE_ALERT_COOLDOWN = 30.0

# System-level runtime settings (refreshed periodically)
_system_detection_threshold = 0.5  # default 50%
# seconds (default 3 minutes) - legacy fallback
_system_notification_cooldown = 180
_settings_refresh_counter = 0

# Global guard duty flag - when False, inference is paused.
_guard_on_duty = False


def _can_trigger_alert(alert_type: str, cooldown_seconds: float) -> bool:
    """Return True if enough time has passed since the last alert of this type."""
    global _last_notification_time
    key = alert_type.lower()
    now = time.time()
    last_ts = _last_notification_time.get(key)
    if last_ts is None or (now - last_ts) >= cooldown_seconds:
        _last_notification_time[key] = now
        return True
    return False


def _log_once_warning(key: str, message: str) -> None:
    """Print a warning once per process for recurring non-fatal issues."""
    if key in _logged_result_shape_warnings:
        return
    _logged_result_shape_warnings.add(key)
    print(message)


async def _refresh_guard_status():
    """Refresh the global `_guard_on_duty` flag by checking if any guard is
    currently marked on duty in the guard profile. This is intentionally
    lightweight and called periodically from the camera loop so inference can
    be paused when guards are not on duty.
    """
    global _guard_on_duty
    try:
        users_col = get_users_collection()
        active_guard = await users_col.find_one(
            {"role": "guard", "is_verified": True, "isOnDuty": True}
        )

        # Fallback: if a duty session is open, keep models active even when
        # profile flag sync is delayed/missing for that identity.
        active_duty = None
        if not active_guard:
            duty_col = get_db()["guard_duty"]
            active_duty = await duty_col.find_one({"logout_time": None})

        _guard_on_duty = bool(active_guard or active_duty)
    except Exception:
        # On error, conservatively default to False (no inference)
        _guard_on_duty = False

try:
    from ..database import get_users_collection, get_settings_collection, get_db, get_media_collection
    from ..Models.schemas import IncidentRecord, MediaRecord
    from .admin_notifications import notify_admins as _notify_admins
    from ..utils.guard_whatsapp_text import (
        build_guard_duty_quick_reply_hint,
        build_guard_confirmed_alert_message,
        normalize_guard_language,
    )
except ImportError:
    from database import get_users_collection, get_settings_collection, get_db, get_media_collection
    from Models.schemas import IncidentRecord, MediaRecord
    try:
        from admin_notifications import notify_admins as _notify_admins
    except Exception:
        _notify_admins = None
    from utils.guard_whatsapp_text import (
        build_guard_duty_quick_reply_hint,
        build_guard_confirmed_alert_message,
        normalize_guard_language,
    )


async def _notify_admins_detection(payload: dict[str, Any]) -> None:
    if _notify_admins is None:
        return
    try:
        await _notify_admins(payload)
    except Exception as exc:
        logging.warning(
            f"[CAMERA] Failed to publish websocket detection event: {exc}")


WAHA_CONFIRM_THREAT_TEMPLATES: dict[str, str] = {
    "en": (
        "🚨 *CAMPUS GUARD // CONFIRMED THREAT* 🚨\n"
        "*Threat:* {threat}\n"
        "*Zone:* {camera}\n"
        "*Time:* {time}\n\n"
        "*Immediate Actions*\n"
        "1) Reach the zone now\n"
        "2) Secure nearby exits\n"
        "3) Send acknowledgment to control room"
    ),
    "hi": (
        "🚨 *CAMPUS GUARD // पुष्टि किया गया खतरा* 🚨\n"
        "*खतरा:* {threat}\n"
        "*क्षेत्र:* {camera}\n"
        "*समय:* {time}\n\n"
        "*तुरंत कार्रवाई*\n"
        "1) तुरंत स्थान पर पहुंचें\n"
        "2) आसपास के निकास सुरक्षित करें\n"
        "3) कंट्रोल रूम को पुष्टि भेजें"
    ),
    "mr": (
        "🚨 *CAMPUS GUARD // पुष्टी झालेला धोका* 🚨\n"
        "*धोका:* {threat}\n"
        "*झोन:* {camera}\n"
        "*वेळ:* {time}\n\n"
        "*तात्काळ कृती*\n"
        "1) लगेच ठिकाणी पोहोचा\n"
        "2) जवळचे बाहेर पडण्याचे मार्ग सुरक्षित करा\n"
        "3) कंट्रोल रूमला पुष्टी पाठवा"
    ),
}

WAHA_DUTY_ON_ROW_ID = "duty:on"
WAHA_DUTY_OFF_ROW_ID = "duty:off"
WAHA_ALERT_RESPONDING_BUTTON_ID = "alert_responding"


def _sanitize_path_segment(value: str) -> str:
    """Convert free-form labels to safe folder/file path segments."""
    sanitized = "".join(
        c if c.isalnum() else "_" for c in str(value).strip().lower())
    sanitized = "_".join(part for part in sanitized.split("_") if part)
    return sanitized or "unknown"


def save_frame_to_disk(
    frame,
    detection_type: str,
    confidence: float,
    timestamp: str,
    subtype: str | None = None,
) -> str:
    """Save frame capture to disk grouped by detection class.

    Captures are stored as: captures/<type>/<subtype>/filename.jpg
    """
    safe_type = _sanitize_path_segment(detection_type)
    safe_subtype = _sanitize_path_segment(subtype or "general")
    frame_filename = f"{safe_type}_{safe_subtype}_{timestamp.replace(':', '-').replace(' ', '_')}_conf{confidence:.2f}.jpg"
    frame_path = CAPTURES_DIR / safe_type / safe_subtype / frame_filename
    frame_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(frame_path), frame)
    print(f"[CAMERA] Frame saved to {frame_path}")
    # Return relative path by extracting the part after 'captures/'
    relative_path = f"{safe_type}/{safe_subtype}/{frame_filename}"
    return relative_path


def _capture_synchronized_evidence_frames(alert_type: str, subtype: str | None = None) -> list[str]:
    """Capture both camera frames with one timestamp for verified multi-angle incidents."""
    timestamp_token = datetime.now(
        timezone.utc).strftime("%Y-%m-%d_%H-%M-%S-%f")
    safe_type = _sanitize_path_segment(alert_type)
    safe_subtype = _sanitize_path_segment(subtype or "general")
    base_dir = CAPTURES_DIR / "evidence" / safe_type / safe_subtype
    base_dir.mkdir(parents=True, exist_ok=True)

    captured: dict[int, np.ndarray] = {}
    for cam_id in (0, 1):
        with _ai_frame_locks[cam_id]:
            latest = _latest_ai_frames.get(cam_id)
            if latest is not None:
                captured[cam_id] = latest.copy()

    # Require both camera frames to preserve strict two-angle evidence.
    if len(captured) < 2:
        return []

    evidence_urls: list[str] = []
    for cam_id in (0, 1):
        frame = captured.get(cam_id)
        if frame is None:
            return []
        filename = f"verified_{safe_type}_{safe_subtype}_cam{cam_id + 1}_{timestamp_token}.jpg"
        output_path = base_dir / filename
        if not cv2.imwrite(str(output_path), frame):
            return []
        evidence_urls.append(f"evidence/{safe_type}/{safe_subtype}/{filename}")

    return evidence_urls


# Build a set of known weapon labels so other models can filter them out
_weapon_label_set: set[str] = set()
if weapon_model is not None:
    _weapon_label_set = {str(n).lower() for n in weapon_model.names.values()}

# Fire models may include non-alert classes (e.g., smoke/other); ignore them.
_FIRE_IGNORE_LABELS: set[str] = {
    "other",
    "others",
    "smoke",
    "smokes",
}

_VIOLENCE_IGNORE_LABELS: set[str] = {
    "nonviolence",
    "non violence",
    "non-violence",
}

# Suppress grenade detections entirely (no overlay, no alert logging, no notify).
_WEAPON_IGNORE_LABELS: set[str] = {
    "grenade",
    "grenades",
    "hand grenade",
    "hand_grenade",
}


def _normalize_label(label: str) -> str:
    """Normalize label text for consistent ignore matching."""
    if not label:
        return ""

    normalized = str(label).lower().strip()
    # Normalize separators (underscores/hyphens) to spaces to match ignore set entries.
    normalized = normalized.replace("_", " ").replace("-", " ")
    # Collapse multiple spaces
    normalized = " ".join(normalized.split())
    return normalized


def _should_ignore_label(label: str, ignore_labels: set[str] | None = None) -> bool:
    """Return True if this label should be ignored for a given model/detection pass."""
    normalized = _normalize_label(label)
    if not normalized:
        return True

    if normalized == "background":
        return True

    if ignore_labels and normalized in ignore_labels:
        return True

    return False


# Anomaly model should ignore any weapon labels (to avoid duplicate weapon alerts)
_ANOMALY_IGNORE_LABELS = _weapon_label_set.union({"weapon"})


def _resolve_allowed_classes(
    model: YOLO | None,
    *,
    allowed_labels: set[str] | None = None,
    blocked_labels: set[str] | None = None,
) -> list[int] | None:
    """Return model class ids to keep during prediction.

    Filtering at prediction time trims NMS/postprocessing work for models that
    include background or non-alert classes.
    """
    if model is None or not getattr(model, "names", None):
        return None

    normalized_allowed = None
    if allowed_labels is not None:
        normalized_allowed = {_normalize_label(
            label) for label in allowed_labels}

    normalized_blocked = set()
    if blocked_labels is not None:
        normalized_blocked = {_normalize_label(
            label) for label in blocked_labels}

    allowed_class_ids: list[int] = []
    for cls_id, label in model.names.items():
        normalized_label = _normalize_label(str(label))
        if not normalized_label or normalized_label == "background":
            continue
        if normalized_allowed is not None and normalized_label not in normalized_allowed:
            continue
        if normalized_label in normalized_blocked:
            continue
        allowed_class_ids.append(int(cls_id))

    return allowed_class_ids or None


_WEAPON_ALLOWED_CLASSES = _resolve_allowed_classes(
    weapon_model,
    blocked_labels=_WEAPON_IGNORE_LABELS,
)
_ANOMALY_ALLOWED_CLASSES = _resolve_allowed_classes(
    anomaly_model,
    allowed_labels={"suspicious"},
    blocked_labels=_ANOMALY_IGNORE_LABELS,
)
_FIRE_ALLOWED_CLASSES = _resolve_allowed_classes(
    fire_model,
    blocked_labels=_FIRE_IGNORE_LABELS,
)
_VIOLENCE_ALLOWED_CLASSES = _resolve_allowed_classes(
    violence_model,
    allowed_labels={"violence"},
    blocked_labels=_VIOLENCE_IGNORE_LABELS,
)


# Add thread-safe global variable for live box syncing per camera.
_latest_detections_by_camera: dict[int, dict[str, Any]] = {
    0: {"timestamp": 0, "boxes": []},
    1: {"timestamp": 0, "boxes": []},
}
_detections_lock = Lock()

# Cross-camera verification tracker: if the same threat class is seen on both
# cameras within a short window, mark alert as multi-angle verified.
_recent_detections_by_type: dict[str, dict[int, float]] = {}
_multi_angle_lock = Lock()


def _register_detection_and_check_multi_angle(alert_type: str, camera_id: int) -> bool:
    now = time.time()
    normalized_type = str(alert_type or "").strip().lower()
    if normalized_type not in {"weapon", "violence", "fire", "anomaly"}:
        return False

    with _multi_angle_lock:
        per_type = _recent_detections_by_type.setdefault(normalized_type, {})

        # Record this camera timestamp first.
        per_type[camera_id] = now

        # Immediate reverse-check against the opposite camera for the same class.
        other_camera_id = 1 if int(camera_id) == 0 else 0
        other_ts = per_type.get(other_camera_id)
        if other_ts is not None and (now - float(other_ts)) <= MULTI_ANGLE_VERIFY_WINDOW_SEC:
            return True

        # Keep only recent entries inside strict 2-second window.
        stale_keys = [
            cam_id
            for cam_id, ts in per_type.items()
            if (now - float(ts)) > MULTI_ANGLE_VERIFY_WINDOW_SEC
        ]
        for stale in stale_keys:
            per_type.pop(stale, None)

        # Secondary symmetric check for completeness after cleanup.
        this_ts = per_type.get(camera_id)
        if this_ts is None:
            return False
        for other_id, other_ts in per_type.items():
            if other_id == camera_id:
                continue
            if abs(float(this_ts) - float(other_ts)) <= MULTI_ANGLE_VERIFY_WINDOW_SEC:
                return True
    return False


def _process_model_results(
    results,
    frame: np.ndarray,
    color: tuple[int, int, int],
    alert_type: str,
    threshold: float,
    allowed_labels: set[str] | None = None,
    ignore_labels: set[str] | None = None,
    cooldown_seconds: float | None = None,
    sustained_seconds: float | None = None,
    enable_alerts: bool = True,
    camera_id: int = 0,
    camera_location: str | None = None,
) -> None:
    """Process model results and update live detections."""
    local_boxes = []

    normalized_allowed_labels: set[str] | None = None
    if allowed_labels is not None:
        normalized_allowed_labels = {
            _normalize_label(v) for v in allowed_labels}

    try:
        if results is None:
            return

        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is not None:
                for box in boxes:
                    conf = float(box.conf[0])
                    cls_id = int(box.cls[0])
                    label = result.names.get(cls_id, alert_type)

                    if normalized_allowed_labels is not None:
                        normalized_label = _normalize_label(str(label))
                        if normalized_label not in normalized_allowed_labels:
                            continue

                    if _should_ignore_label(label, ignore_labels=ignore_labels):
                        continue

                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    local_boxes.append((x1, y1, x2, y2, color, label, conf))

                    # Save and log every qualifying detection
                    if conf >= threshold and enable_alerts:
                        multi_angle_verified = _register_detection_and_check_multi_angle(
                            alert_type,
                            camera_id,
                        )
                        evidence_urls: list[str] = []
                        if multi_angle_verified:
                            evidence_urls = _capture_synchronized_evidence_frames(
                                alert_type,
                                subtype=str(label),
                            )

                        alert_key = alert_type.lower()
                        can_trigger = True
                        if cooldown_seconds is not None:
                            can_trigger = _can_trigger_alert(
                                alert_key, cooldown_seconds)
                        if not can_trigger:
                            if not multi_angle_verified:
                                continue
                            # Allow one update per verify-window to stamp
                            # cross-camera verification without per-frame writes.
                            multi_key = f"{alert_key}_multi_verify"
                            if not _can_trigger_alert(multi_key, MULTI_ANGLE_VERIFY_WINDOW_SEC):
                                continue

                        frame_path = save_frame_to_disk(
                            frame,
                            alert_type,
                            conf,
                            datetime.now(timezone.utc).strftime(
                                "%Y-%m-%d %H:%M:%S.%f"),
                            subtype=str(label),
                        )
                        try:
                            _submit_async_fire_and_forget(
                                log_alert_with_frame(
                                    alert_type, conf, frame_path, None, subtype=str(label),
                                    dedupe_window_seconds=cooldown_seconds or 30.0,
                                    location=camera_location or CAMERA_LOCATIONS.get(
                                        camera_id, "AI Camera"
                                    ),
                                    source_camera_id=camera_id,
                                    multi_angle_verified=multi_angle_verified,
                                    evidence_urls=evidence_urls,
                                ),
                                task_name=f"log_alert:{alert_type}:camera_{camera_id}",
                            )
                        except Exception as e:
                            logging.error(f"[CAMERA] Error logging alert: {e}")

    except Exception as exc:
        _log_once_warning(
            f"result_processing_error:{alert_type}:{type(exc).__name__}",
            f"[CAMERA] Error processing {alert_type} results: {exc}",
        )

    # Update global detections for live display.
    with _detections_lock:
        _latest_detections_by_camera[camera_id] = {
            "timestamp": time.time(),
            "boxes": local_boxes,
        }


async def log_alert_with_frame(
    alert_type: str,
    confidence: float,
    frame_path: str | None = None,
    frame_id: int | None = None,
    subtype: str | None = None,
    dedupe_window_seconds: float = 30.0,
    location: str | None = None,
    source_camera_id: int | None = None,
    multi_angle_verified: bool = False,
    evidence_urls: list[str] | None = None,
) -> None:
    """Log alert to database grouped by type.

    Within the dedupe window only ONE pending alert per type exists.
    - If a pending alert of the same type exists, update it in place.
        - If a confirmed/resolved alert exists within the window, skip entirely
      (spam stops after guard confirms the threat).
    - Otherwise insert a fresh pending alert.
    """
    alerts = get_alerts_collection()
    dedupe_cutoff = datetime.now(timezone.utc) - \
        timedelta(seconds=dedupe_window_seconds)
    # Search by type only so all subtypes share one alert slot.
    now_utc = datetime.now(timezone.utc)
    cleaned_evidence_urls = [
        str(path).strip().lstrip("/").replace("\\", "/")
        for path in (evidence_urls or [])
        if str(path or "").strip()
    ]

    existing = await alerts.find_one(
        {
            "type": alert_type,
            "timestamp": {"$gte": dedupe_cutoff},
            "status": "pending",
        }
    )
    if existing is not None:
        # Update the existing pending alert with latest evidence.
        stored_evidence_urls = existing.get("evidence_urls") or []
        next_evidence_urls = cleaned_evidence_urls or stored_evidence_urls
        await alerts.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "confidence": max(existing.get("confidence", 0), confidence),
                    "timestamp": now_utc,
                    "frame_path": frame_path,
                    "subtype": subtype,
                    "frame_id": frame_id,
                    "location": location or existing.get("location") or "AI Camera",
                    "source_camera_id": source_camera_id if source_camera_id is not None else existing.get("source_camera_id"),
                    "multi_angle_verified": bool(existing.get("multi_angle_verified") or multi_angle_verified),
                    "evidence_urls": next_evidence_urls,
                }
            },
        )

        effective_camera_id = (
            source_camera_id
            if source_camera_id is not None
            else existing.get("source_camera_id")
        )
        await _notify_admins_detection(
            {
                "type": alert_type,
                "event": "ALERT_DETECTION",
                "id": str(existing.get("_id")),
                "alert_id": str(existing.get("_id")),
                "subtype": subtype,
                "confidence": confidence,
                "timestamp": now_utc.isoformat(),
                "location": location or existing.get("location") or "AI Camera",
                "camera_id": effective_camera_id,
                "source_camera_id": effective_camera_id,
                "primary_camera_id": existing.get("primary_camera_id") or effective_camera_id,
                "multi_angle_verified": bool(existing.get("multi_angle_verified") or multi_angle_verified),
                "evidence_urls": next_evidence_urls,
                "status": "pending",
            }
        )
        return

    doc = {
        "type": alert_type,
        "subtype": subtype,
        "confidence": confidence,
        "timestamp": now_utc,
        "frame_id": frame_id,
        "frame_path": frame_path,
        "location": location or "AI Camera",
        "source_camera_id": source_camera_id,
        "primary_camera_id": source_camera_id,
        "multi_angle_verified": bool(multi_angle_verified),
        "evidence_urls": cleaned_evidence_urls,
        "verified": False,
        "status": "pending",
        "action_history": [],
    }
    incident = IncidentRecord(**doc)
    result = await alerts.insert_one(incident.dict())
    inserted_id = str(result.inserted_id)

    await _notify_admins_detection(
        {
            "type": alert_type,
            "event": "ALERT_DETECTION",
            "id": inserted_id,
            "alert_id": inserted_id,
            "subtype": subtype,
            "confidence": confidence,
            "timestamp": now_utc.isoformat(),
            "location": doc.get("location") or "AI Camera",
            "camera_id": source_camera_id,
            "source_camera_id": source_camera_id,
            "primary_camera_id": source_camera_id,
            "multi_angle_verified": bool(multi_angle_verified),
            "evidence_urls": cleaned_evidence_urls,
            "status": "pending",
        }
    )

    if frame_path:
        media_col = get_media_collection()
        media = MediaRecord(
            incident_id=inserted_id,
            media_type="image",
            frame_path=frame_path,
        )
        await media_col.insert_one(media.dict())


async def _refresh_system_settings_every_n_calls(n: int = 50):
    """Refresh global system settings from DB periodically to pick up changes without restarting."""
    global _system_detection_threshold, _system_notification_cooldown
    settings_col = get_settings_collection()
    doc = await settings_col.find_one({})
    if not doc:
        return
    det = doc.get("detection_threshold")
    if det is not None:
        try:
            _system_detection_threshold = float(det) / 100.0
        except Exception:
            pass
    wc = doc.get("notification_cooldown_seconds") or doc.get(
        "weapon_cooldown_seconds")
    # keep backwards compatibility with old weapon_cooldown_seconds setting
    if wc is not None:
        try:
            _system_notification_cooldown = int(wc)
        except Exception:
            pass


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
    return _read_float_env("WAHA_TIMEOUT_SEC", 10.0, 2.0, 30.0)


def _public_backend_base_url() -> str:
    """Public backend URL used to build externally reachable frame links."""
    return (
        str(os.getenv("PUBLIC_BACKEND_URL") or "").strip().rstrip("/")
        or str(os.getenv("BACKEND_PUBLIC_URL") or "").strip().rstrip("/")
        or "http://127.0.0.1:8000"
    )


def _build_public_frame_url(frame_path: str | None) -> str | None:
    if not frame_path:
        return None
    normalized = str(frame_path).strip().lstrip("/").replace("\\", "/")
    if not normalized:
        return None
    encoded = requests.utils.quote(normalized, safe="/")
    return f"{_public_backend_base_url()}/file/{encoded}"


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
    reason = f"status={response.status_code} body={response.text[:300]}"
    logging.warning(
        "[CAMERA][WAHA] sendText failed status=%s body=%s",
        response.status_code,
        response.text[:300],
    )
    return False, reason


def _waha_send_buttons(chat_digits: str, language: str) -> tuple[bool, str | None]:
    chat_id = f"{_normalize_phone_digits(chat_digits)}@c.us"
    code = normalize_guard_language(language)

    if code == "hi":
        title = "ड्यूटी स्थिति अपडेट"
        body = "ड्यूटी कंट्रोल: ON या OFF चुनें"
        footer = "Campus Guard AI"
        on_label = "ON"
        off_label = "OFF"
    elif code == "mr":
        title = "ड्युटी स्थिती अपडेट"
        body = "ड्युटी कंट्रोल: ON किंवा OFF निवडा"
        footer = "Campus Guard AI"
        on_label = "ON"
        off_label = "OFF"
    else:
        title = "Duty Control"
        body = "Tap ON to go ON DUTY or OFF to go OFF DUTY"
        footer = "Campus Guard AI"
        on_label = "ON"
        off_label = "OFF"

    payload = {
        "chatId": chat_id,
        "session": _waha_session_name(),
        "title": title,
        "body": body,
        "footer": footer,
        "buttons": [
            {
                "id": WAHA_DUTY_ON_ROW_ID,
                "text": on_label,
            },
            {
                "id": WAHA_DUTY_OFF_ROW_ID,
                "text": off_label,
            },
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
    reason = f"status={response.status_code} body={response.text[:300]}"
    logging.warning(
        "[CAMERA][WAHA] sendButtons failed status=%s body=%s",
        response.status_code,
        response.text[:300],
    )
    return False, reason


def _waha_send_alert_response_button(chat_digits: str, language: str, alert_id: str | None) -> tuple[bool, str | None]:
    chat_id = f"{_normalize_phone_digits(chat_digits)}@c.us"
    code = normalize_guard_language(language)

    if code == "hi":
        title = "घटना प्रतिक्रिया"
        body = "अगर आप इस घटना पर जा रहे हैं तो नीचे क्लिक करें"
        button_text = "RESPONDING"
    elif code == "mr":
        title = "घटना प्रतिसाद"
        body = "तुम्ही या घटनेला प्रतिसाद देत असाल तर खाली क्लिक करा"
        button_text = "RESPONDING"
    else:
        title = "Incident Response"
        body = "Click if you are responding to this incident"
        button_text = "RESPONDING"

    button_id = WAHA_ALERT_RESPONDING_BUTTON_ID
    if str(alert_id or "").strip():
        button_id = f"{WAHA_ALERT_RESPONDING_BUTTON_ID}:{str(alert_id).strip()}"

    payload = {
        "chatId": chat_id,
        "session": _waha_session_name(),
        "title": title,
        "body": body,
        "footer": "Campus Guard AI",
        "buttons": [
            {
                "id": button_id,
                "text": button_text,
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
    reason = f"status={response.status_code} body={response.text[:300]}"
    logging.warning(
        "[CAMERA][WAHA] incident sendButtons failed status=%s body=%s",
        response.status_code,
        response.text[:300],
    )
    return False, reason


def _waha_send_list(chat_digits: str, language: str) -> tuple[bool, str | None]:
    chat_id = f"{_normalize_phone_digits(chat_digits)}@c.us"
    code = normalize_guard_language(language)

    if code == "hi":
        message = {
            "title": "ड्यूटी स्थिति अपडेट",
            "description": "अपनी ड्यूटी स्थिति चुनें",
            "footer": "Campus Guard AI",
            "button": "विकल्प चुनें",
            "sections": [
                {
                    "title": "ड्यूटी विकल्प",
                    "rows": [
                        {
                            "title": "ON DUTY",
                            "rowId": WAHA_DUTY_ON_ROW_ID,
                            "description": "मैं अभी ड्यूटी पर उपलब्ध हूं",
                        },
                        {
                            "title": "OFF DUTY",
                            "rowId": WAHA_DUTY_OFF_ROW_ID,
                            "description": "मैं अभी ड्यूटी से बाहर हूं",
                        },
                    ],
                }
            ],
        }
    elif code == "mr":
        message = {
            "title": "ड्युटी स्थिती अपडेट",
            "description": "तुमची ड्युटी स्थिती निवडा",
            "footer": "Campus Guard AI",
            "button": "पर्याय निवडा",
            "sections": [
                {
                    "title": "ड्युटी पर्याय",
                    "rows": [
                        {
                            "title": "ON DUTY",
                            "rowId": WAHA_DUTY_ON_ROW_ID,
                            "description": "मी सध्या ड्युटीवर उपलब्ध आहे",
                        },
                        {
                            "title": "OFF DUTY",
                            "rowId": WAHA_DUTY_OFF_ROW_ID,
                            "description": "मी सध्या ड्युटीबाहेर आहे",
                        },
                    ],
                }
            ],
        }
    else:
        message = {
            "title": "Duty Status Update",
            "description": "Choose your current duty status",
            "footer": "Campus Guard AI",
            "button": "Select Option",
            "sections": [
                {
                    "title": "Duty Options",
                    "rows": [
                        {
                            "title": "ON DUTY",
                            "rowId": WAHA_DUTY_ON_ROW_ID,
                            "description": "I am currently available on duty",
                        },
                        {
                            "title": "OFF DUTY",
                            "rowId": WAHA_DUTY_OFF_ROW_ID,
                            "description": "I am currently unavailable/off duty",
                        },
                    ],
                }
            ],
        }

    payload = {
        "chatId": chat_id,
        "session": _waha_session_name(),
        "message": message,
    }
    response = requests.post(
        f"{_waha_base_url()}/api/sendList",
        json=payload,
        headers=_waha_headers(),
        timeout=_waha_timeout_sec(),
    )
    if response.ok:
        return True, None
    reason = f"status={response.status_code} body={response.text[:300]}"
    logging.warning(
        "[CAMERA][WAHA] sendList failed status=%s body=%s",
        response.status_code,
        response.text[:300],
    )
    return False, reason


def _waha_send_poll(chat_digits: str, language: str) -> tuple[bool, str | None]:
    chat_id = f"{_normalize_phone_digits(chat_digits)}@c.us"
    code = normalize_guard_language(language)

    poll_name = {
        "en": "Update your duty status",
        "hi": "अपनी ड्यूटी स्थिति अपडेट करें",
        "mr": "तुमची ड्युटी स्थिती अपडेट करा",
    }.get(code, "Update your duty status")

    payload = {
        "chatId": chat_id,
        "session": _waha_session_name(),
        "poll": {
            "name": poll_name,
            "options": ["ON DUTY", "OFF DUTY"],
            "multipleAnswers": False,
        },
    }
    response = requests.post(
        f"{_waha_base_url()}/api/sendPoll",
        json=payload,
        headers=_waha_headers(),
        timeout=_waha_timeout_sec(),
    )
    if response.ok:
        return True, None
    reason = f"status={response.status_code} body={response.text[:300]}"
    logging.warning(
        "[CAMERA][WAHA] sendPoll failed status=%s body=%s",
        response.status_code,
        response.text[:300],
    )
    return False, reason


def _waha_send_duty_options(chat_digits: str, language: str) -> tuple[bool, str | None]:
    buttons_sent, buttons_reason = _waha_send_buttons(chat_digits, language)
    if buttons_sent:
        return True, None
    return False, buttons_reason or "send_buttons_failed"


def _waha_send_image(chat_digits: str, caption: str, image_path: str) -> tuple[bool, str | None]:
    image_file = Path(image_path)
    if not image_file.is_file():
        return False, f"image_not_found:{image_path}"

    try:
        raw = image_file.read_bytes()
    except Exception as exc:
        logging.warning(
            "[CAMERA][WAHA] Unable to read image %s: %s", image_path, exc)
        return False, f"image_read_failed:{exc}"

    mime_type = mimetypes.guess_type(str(image_file))[0] or "image/jpeg"
    encoded = base64.b64encode(raw).decode("ascii")
    chat_id = f"{_normalize_phone_digits(chat_digits)}@c.us"

    payload = {
        "chatId": chat_id,
        "caption": caption,
        "file": f"data:{mime_type};base64,{encoded}",
        "session": _waha_session_name(),
    }
    response = requests.post(
        f"{_waha_base_url()}/api/sendImage",
        json=payload,
        headers=_waha_headers(),
        timeout=max(8.0, _waha_timeout_sec()),
    )
    if response.ok:
        return True, None
    reason = f"status={response.status_code} body={response.text[:300]}"
    logging.warning(
        "[CAMERA][WAHA] sendImage failed status=%s body=%s",
        response.status_code,
        response.text[:300],
    )
    return False, reason


def _sanitize_ai_message(text: str, max_chars: int) -> str:
    cleaned = str(text or "").replace("\r\n", "\n").strip()
    cleaned = cleaned.replace("```", "").strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rstrip()
    return cleaned


def _normalize_movement_direction(value: str | None) -> str:
    raw = str(value or "unknown").strip().lower().replace("-", "_")
    aliases = {
        "left_to_right": "right",
        "right_to_left": "left",
        "toward_camera": "towards_camera",
        "towards": "towards_camera",
        "away": "away_from_camera",
        "forward": "straight",
        "none": "unknown",
    }
    normalized = aliases.get(raw, raw)
    allowed = {
        "left",
        "right",
        "straight",
        "towards_camera",
        "away_from_camera",
        "unknown",
    }
    return normalized if normalized in allowed else "unknown"


def _parse_json_object_from_text(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None

    cleaned = raw.replace("```json", "").replace("```", "").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None

    candidate = cleaned[start:end + 1]
    try:
        parsed = json.loads(candidate)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _fallback_confirmed_threat_narrative(
    *,
    alert_type: str,
    subtype: str | None,
    confidence: float,
    camera_location: str,
    incident_time: str,
    reason: str | None = None,
) -> dict[str, Any]:
    threat_label = str(subtype or alert_type or "threat").replace(
        "_", " ").strip()
    confidence_pct = round(float(confidence or 0.0) * 100.0, 1)
    fallback_reason = str(reason or "template_fallback").strip()

    summary_en = (
        f"Confirmed {threat_label} detected near {camera_location} at {incident_time}. "
        f"Model confidence was {confidence_pct}% and immediate guard verification is required."
    )
    summary_hi = (
        f"{incident_time} पर {camera_location} के पास {threat_label} की पुष्टि हुई। "
        f"मॉडल विश्वास स्तर {confidence_pct}% था, कृपया तुरंत जांच करें।"
    )
    summary_mr = (
        f"{incident_time} ला {camera_location} जवळ {threat_label} ची पुष्टी झाली। "
        f"मॉडेल विश्वास पातळी {confidence_pct}% होती, कृपया तात्काळ पडताळणी करा।"
    )

    detail_en = (
        "System detected a potential subject carrying or interacting with a suspicious object. "
        "Treat this as an active verified incident, secure nearby exits, and track movement using adjacent cameras."
    )
    detail_hi = (
        "सिस्टम ने संदिग्ध वस्तु के साथ संभावित व्यक्ति का संकेत दिया है। "
        "इसे सक्रिय पुष्टि-घटना मानें, आसपास के निकास सुरक्षित करें और पास के कैमरों से मूवमेंट ट्रैक करें।"
    )
    detail_mr = (
        "सिस्टमने संशयास्पद वस्तूसह संभाव्य व्यक्तीची नोंद केली आहे। "
        "ही सक्रिय पुष्टी-घटना मानून जवळचे बाहेरचे मार्ग सुरक्षित करा आणि शेजारच्या कॅमेर्‍यांतून हालचाल ट्रॅक करा।"
    )

    return {
        "ai_summary_en": _sanitize_ai_message(summary_en, 320),
        "ai_summary_hi": _sanitize_ai_message(summary_hi, 320),
        "ai_summary_mr": _sanitize_ai_message(summary_mr, 320),
        "ai_narrative_en": _sanitize_ai_message(detail_en, AI_INCIDENT_NARRATIVE_MAX_CHARS),
        "ai_narrative_hi": _sanitize_ai_message(detail_hi, AI_INCIDENT_NARRATIVE_MAX_CHARS),
        "ai_narrative_mr": _sanitize_ai_message(detail_mr, AI_INCIDENT_NARRATIVE_MAX_CHARS),
        "movement_direction": "unknown",
        "movement_confidence": 0.0,
        "narrative_generation_mode": f"fallback:{fallback_reason}",
    }


async def _generate_confirmed_threat_narrative(
    *,
    alert_type: str,
    subtype: str | None,
    confidence: float,
    frame_path: str | None,
    camera_location: str,
    incident_time: str,
) -> dict[str, Any]:
    """Generate multilingual, investigation-focused narrative from a confirmed frame."""
    fallback = _fallback_confirmed_threat_narrative(
        alert_type=alert_type,
        subtype=subtype,
        confidence=confidence,
        camera_location=camera_location,
        incident_time=incident_time,
        reason="ai_unavailable",
    )

    if not ENABLE_AI_INCIDENT_NARRATIVE:
        fallback["narrative_generation_mode"] = "fallback:disabled"
        return fallback

    if genai is None:
        fallback["narrative_generation_mode"] = "fallback:gemini_not_installed"
        return fallback

    api_key = str(os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key or api_key.lower().startswith("your_") or "changeme" in api_key.lower():
        fallback["narrative_generation_mode"] = "fallback:missing_api_key"
        return fallback

    resolved_image: Path | None = None
    if frame_path:
        candidate = CAPTURES_DIR / str(frame_path)
        if candidate.is_file():
            resolved_image = candidate
    if resolved_image is None:
        fallback["narrative_generation_mode"] = "fallback:frame_missing"
        return fallback

    try:
        genai.configure(api_key=api_key)
        image_bytes = await asyncio.to_thread(resolved_image.read_bytes)
        mime_type = mimetypes.guess_type(str(resolved_image))[
            0] or "image/jpeg"
        if not str(mime_type).startswith("image/"):
            mime_type = "image/jpeg"

        prompt = (
            "You are a CCTV incident analyst for campus security. Analyze the attached frame and return STRICT JSON only.\n"
            "Do not use markdown. Do not add extra keys.\n"
            "Required JSON schema:\n"
            "{\n"
            '  "ai_summary_en": "...",\n'
            '  "ai_summary_hi": "...",\n'
            '  "ai_summary_mr": "...",\n'
            '  "ai_narrative_en": "...",\n'
            '  "ai_narrative_hi": "...",\n'
            '  "ai_narrative_mr": "...",\n'
            '  "movement_direction": "left|right|straight|towards_camera|away_from_camera|unknown",\n'
            '  "movement_confidence": 0.0\n'
            "}\n"
            "Rules:\n"
            "- Keep language simple and investigation-ready.\n"
            "- If movement is uncertain, use unknown and low confidence.\n"
            "- Hindi and Marathi MUST be Devanagari script only.\n"
            "- Do not hallucinate identity; describe visible clothing/object cues only.\n"
            f"Incident type: {alert_type}\n"
            f"Subtype: {subtype or 'general'}\n"
            f"Confidence: {round(float(confidence or 0.0) * 100.0, 2)}%\n"
            f"Camera location: {camera_location}\n"
            f"Incident time: {incident_time}\n"
        )

        candidate_models: list[str] = []
        for name in [
            AI_INCIDENT_NARRATIVE_MODEL,
            AI_GUARD_ALERT_MODEL,
            "models/gemini-2.5-flash",
            "models/gemini-1.5-flash-latest",
        ]:
            cleaned = str(name or "").strip()
            if cleaned and cleaned not in candidate_models:
                candidate_models.append(cleaned)

        response = None
        last_model_error: Exception | None = None
        for model_name in candidate_models:
            try:
                model = genai.GenerativeModel(model_name)
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        model.generate_content,
                        [prompt, {"mime_type": mime_type, "data": image_bytes}],
                        generation_config={
                            "temperature": 0.1,
                            "top_p": 0.9,
                            "max_output_tokens": 900,
                        },
                        request_options={
                            "timeout": AI_INCIDENT_NARRATIVE_TIMEOUT_SEC},
                    ),
                    timeout=AI_INCIDENT_NARRATIVE_TIMEOUT_SEC + 1.0,
                )
                break
            except Exception as model_exc:
                last_model_error = model_exc
                continue

        if response is None:
            raise RuntimeError(
                f"Narrative model attempts failed: {type(last_model_error).__name__ if last_model_error else 'unknown'}"
            )

        raw_text = ""
        if hasattr(response, "text"):
            raw_text = str(response.text or "").strip()

        parsed = _parse_json_object_from_text(raw_text)
        if not parsed:
            fallback["narrative_generation_mode"] = "fallback:json_parse_failed"
            return fallback

        result = {
            "ai_summary_en": _sanitize_ai_message(str(parsed.get("ai_summary_en") or ""), 320),
            "ai_summary_hi": _sanitize_ai_message(str(parsed.get("ai_summary_hi") or ""), 320),
            "ai_summary_mr": _sanitize_ai_message(str(parsed.get("ai_summary_mr") or ""), 320),
            "ai_narrative_en": _sanitize_ai_message(str(parsed.get("ai_narrative_en") or ""), AI_INCIDENT_NARRATIVE_MAX_CHARS),
            "ai_narrative_hi": _sanitize_ai_message(str(parsed.get("ai_narrative_hi") or ""), AI_INCIDENT_NARRATIVE_MAX_CHARS),
            "ai_narrative_mr": _sanitize_ai_message(str(parsed.get("ai_narrative_mr") or ""), AI_INCIDENT_NARRATIVE_MAX_CHARS),
            "movement_direction": _normalize_movement_direction(str(parsed.get("movement_direction") or "unknown")),
            "movement_confidence": float(parsed.get("movement_confidence") or 0.0),
            "narrative_generation_mode": "ai",
        }

        if not result["ai_summary_en"]:
            fallback["narrative_generation_mode"] = "fallback:empty_summary"
            return fallback

        try:
            result["movement_confidence"] = max(
                0.0,
                min(1.0, float(result["movement_confidence"])),
            )
        except Exception:
            result["movement_confidence"] = 0.0

        return result
    except asyncio.TimeoutError:
        fallback["narrative_generation_mode"] = "fallback:timeout"
        return fallback
    except Exception as exc:
        fallback["narrative_generation_mode"] = f"fallback:error:{type(exc).__name__}"
        return fallback


def _movement_direction_label(direction: str | None, language: str) -> str:
    code = normalize_guard_language(language)
    normalized = _normalize_movement_direction(direction)
    labels = {
        "en": {
            "left": "likely moved left",
            "right": "likely moved right",
            "straight": "likely moved straight",
            "towards_camera": "likely moved toward camera",
            "away_from_camera": "likely moved away from camera",
            "unknown": "movement unclear",
        },
        "hi": {
            "left": "संभावित रूप से बाईं ओर गया",
            "right": "संभावित रूप से दाईं ओर गया",
            "straight": "संभावित रूप से सीधे गया",
            "towards_camera": "संभावित रूप से कैमरे की ओर आया",
            "away_from_camera": "संभावित रूप से कैमरे से दूर गया",
            "unknown": "मूवमेंट स्पष्ट नहीं है",
        },
        "mr": {
            "left": "बहुधा डावीकडे गेला",
            "right": "बहुधा उजवीकडे गेला",
            "straight": "बहुधा सरळ गेला",
            "towards_camera": "बहुधा कॅमेराकडे आला",
            "away_from_camera": "बहुधा कॅमेरापासून दूर गेला",
            "unknown": "हालचाल स्पष्ट नाही",
        },
    }
    return labels.get(code, labels["en"]).get(normalized, labels["en"]["unknown"])


def _build_guard_narrative_appendix(
    *,
    language: str,
    summary: str | None,
    narrative: str | None,
    movement_direction: str | None,
    movement_confidence: float | None,
) -> str:
    code = normalize_guard_language(language)
    heading = {
        "en": "Field Intelligence",
        "hi": "फील्ड इंटेलिजेंस",
        "mr": "फील्ड इंटेलिजन्स",
    }.get(code, "Field Intelligence")
    movement_heading = {
        "en": "Movement",
        "hi": "मूवमेंट",
        "mr": "हालचाल",
    }.get(code, "Movement")

    lines: list[str] = [f"*{heading}:*"]
    if summary:
        lines.append(f"- {_sanitize_ai_message(summary, 350)}")
    if narrative:
        lines.append(f"- {_sanitize_ai_message(narrative, 650)}")

    direction_line = _movement_direction_label(movement_direction, code)
    confidence_pct = round(
        max(0.0, min(1.0, float(movement_confidence or 0.0))) * 100.0, 1)
    lines.append(f"*{movement_heading}:* {direction_line} ({confidence_pct}%)")
    return "\n".join(line for line in lines if line)


def _truncate_whatsapp_text(text: str, max_chars: int = WAHA_MAX_TEXT_CHARS) -> str:
    cleaned = str(text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 20].rstrip() + "\n...(truncated)"


async def _build_custom_guard_alert_message(
    *,
    alert_type: str,
    subtype: str | None,
    confidence: float,
    camera_location: str,
    ist_time: str,
    language: str,
    variation_seed: str,
) -> str | None:
    """Generate a custom WhatsApp threat message using Gemini when available."""
    if not ENABLE_AI_CUSTOM_GUARD_ALERTS:
        return None
    if genai is None:
        return None

    api_key = str(os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return None

    if api_key.lower().startswith("your_") or "changeme" in api_key.lower():
        return None

    try:
        genai.configure(api_key=api_key)

        model = genai.GenerativeModel(AI_GUARD_ALERT_MODEL)
        confidence_pct = round(float(confidence or 0.0) * 100.0, 2)
        lang = normalize_guard_language(language)

        prompt = (
            "Compose one WhatsApp emergency message for campus guards.\n"
            "This is for a confirmed threat approved by admin.\n"
            f"Language code: {lang}\n"
            "If language is hi or mr, use only native Devanagari script.\n"
            "Do not use Romanized transliteration.\n"
            "Keep it concise, professional, and operational.\n"
            "Include exactly these facts and do not invent anything:\n"
            f"- Threat type: {alert_type}\n"
            f"- Subtype: {subtype or 'general'}\n"
            f"- Confidence: {confidence_pct}%\n"
            f"- Camera location: {camera_location}\n"
            f"- IST time: {ist_time}\n"
            "Add a clear immediate action line for guards.\n"
            "Use varied wording compared to generic template style.\n"
            f"Variation seed: {variation_seed}\n"
            "Return plain WhatsApp-ready text only. No markdown code fences."
        )

        response = await asyncio.wait_for(
            asyncio.to_thread(
                model.generate_content,
                prompt,
                generation_config={
                    "temperature": 0.75,
                    "top_p": 0.9,
                    "max_output_tokens": 280,
                },
                request_options={"timeout": AI_GUARD_ALERT_TIMEOUT_SEC},
            ),
            timeout=AI_GUARD_ALERT_TIMEOUT_SEC + 1.0,
        )

        text = ""
        if hasattr(response, "text"):
            text = str(response.text or "").strip()

        cleaned = _sanitize_ai_message(text, AI_GUARD_ALERT_MAX_CHARS)
        return cleaned or None
    except Exception as exc:
        logging.warning(
            "[CAMERA][AI_ALERT_MESSAGE] Falling back to template message: %s",
            exc,
        )
        return None


async def _notify_guard_contacts(
    alert_type: str,
    confidence: float,
    frame_path: str | None,
    subtype: str | None = None,
    timestamp: str | None = None,
    location: str | None = None,
    on_duty_only: bool = False,
    alert_id: str | None = None,
    recipients: list[dict[str, Any]] | None = None,
    respect_cooldown: bool = True,
    ai_summary_en: str | None = None,
    ai_summary_hi: str | None = None,
    ai_summary_mr: str | None = None,
    ai_narrative_en: str | None = None,
    ai_narrative_hi: str | None = None,
    ai_narrative_mr: str | None = None,
    movement_direction: str | None = None,
    movement_confidence: float | None = None,
    multi_angle_verified: bool = False,
) -> list[dict[str, Any]]:
    """Query users with notification enabled and send WhatsApp via WAHA.

    `subtype` is the model class label for weapons (e.g., 'pistol').
    """
    global _system_notification_cooldown, _last_notification_time
    db = get_db()
    guards_col = get_users_collection()

    on_duty_guard_ids: set[str] = set()
    on_duty_phones: set[str] = set()
    on_duty_emails: set[str] = set()
    if on_duty_only:
        active_cursor = guards_col.find(
            {
                "role": "guard",
                "is_verified": True,
                "$or": [
                    {"isOnDuty": True},
                    {"is_on_duty": True},
                ],
            },
            {"_id": 1, "phone_number": 1, "phone_normalized": 1, "email": 1},
        )
        async for active_guard in active_cursor:
            guard_id = str(active_guard.get("_id") or "").strip()
            if guard_id:
                on_duty_guard_ids.add(guard_id)
            normalized_phone = _normalize_phone_digits(
                str(active_guard.get("phone_number")
                    or active_guard.get("phone_normalized") or "")
            )
            if normalized_phone:
                on_duty_phones.add(normalized_phone)
            email = str(active_guard.get("email") or "").strip().lower()
            if email:
                on_duty_emails.add(email)

    if recipients is None:
        # Read-only recipient selection: no duty mutation in broadcast path.
        guard_query: dict[str, Any] = {
            "role": "guard",
            "is_verified": True,
            "whatsapp_enabled": True,
        }
        if on_duty_only:
            guard_query["$or"] = [{"isOnDuty": True}, {"is_on_duty": True}]

        # Find verified guards with WhatsApp enabled (and optionally on-duty only).
        cursor = guards_col.find(guard_query)
        recipients = []
        async for guard in cursor:
            email = guard.get("email")
            if not guard.get("phone_number"):
                continue

            recipients.append({
                "guard_id": str(guard.get("_id")),
                "full_name": guard.get("full_name"),
                "email": email,
                "phone": guard.get("phone_number"),
                "whatsapp_enabled": True,
                "preferred_language": normalize_guard_language(
                    guard.get("preferred_language")
                ),
            })

    if on_duty_only and recipients:
        filtered_recipients: list[dict[str, Any]] = []
        for recipient in recipients:
            guard_id = str(recipient.get("guard_id") or "").strip()
            phone_digits = _normalize_phone_digits(
                str(recipient.get("phone") or recipient.get("phone_number") or "")
            )
            email = str(recipient.get("email") or "").strip().lower()
            if (
                (guard_id and guard_id in on_duty_guard_ids)
                or (phone_digits and phone_digits in on_duty_phones)
                or (email and email in on_duty_emails)
            ):
                filtered_recipients.append(recipient)
        recipients = filtered_recipients

    if not recipients:
        if on_duty_only:
            print("[CAMERA] No on-duty guards available for notification")
        else:
            print("[CAMERA] No eligible guard contacts found for notification")
        return []

    # Throttle by cooldown per alert type (we intentionally group weapon subtypes together)
    if respect_cooldown:
        now = time.time()
        key = alert_type.lower()
        last_ts = _last_notification_time.get(key)
        if last_ts and (now - last_ts) < _system_notification_cooldown:
            print(f"[CAMERA] Notification for '{key}' suppressed by cooldown")
            return []
        _last_notification_time[key] = now

    # Build user-facing WhatsApp message with incident details and IST timestamp.
    ist_time = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime(
        "%d-%m-%Y %I:%M:%S %p IST")
    camera_location = location or "AI Camera"

    snapshot_path: str | None = None
    if frame_path:
        resolved = CAPTURES_DIR / str(frame_path)
        if resolved.is_file():
            snapshot_path = str(resolved)

    # Send notifications through WAHA (blocking calls executed in threads).
    notifications_col = db["guard_notifications"]
    results: list[dict[str, Any]] = []
    threat_value = str(alert_type or "unknown")
    camera_value = str(camera_location)
    time_value = str(timestamp or ist_time)

    for r in recipients:
        phone_digits = _normalize_phone_digits(
            str(r.get("phone") or r.get("phone_number") or "")
        )
        if not phone_digits or not r.get("whatsapp_enabled", True):
            continue

        guard_language = normalize_guard_language(r.get("preferred_language"))
        if guard_language not in WAHA_CONFIRM_THREAT_TEMPLATES:
            guard_language = "en"

        variation_seed = "|".join(
            [
                str(alert_id or ""),
                str(r.get("guard_id") or ""),
                str(time_value),
                str(threat_value),
                str(camera_value),
            ]
        )
        base_whatsapp_text = build_guard_confirmed_alert_message(
            alert_type=threat_value,
            subtype=subtype,
            confidence=confidence,
            camera_location=camera_value,
            ist_time=time_value,
            language=guard_language,
            variation_seed=variation_seed,
        )

        if not base_whatsapp_text:
            whatsapp_template = WAHA_CONFIRM_THREAT_TEMPLATES[guard_language]
            base_whatsapp_text = whatsapp_template.format(
                threat=threat_value,
                camera=camera_value,
                time=time_value,
            )
        localized_summary = {
            "en": ai_summary_en,
            "hi": ai_summary_hi,
            "mr": ai_summary_mr,
        }.get(guard_language) or ai_summary_en
        localized_narrative = {
            "en": ai_narrative_en,
            "hi": ai_narrative_hi,
            "mr": ai_narrative_mr,
        }.get(guard_language) or ai_narrative_en
        whatsapp_text = base_whatsapp_text
        movement_heading = {
            "en": "Movement",
            "hi": "मूवमेंट",
            "mr": "हालचाल",
        }.get(guard_language, "Movement")
        movement_line = _movement_direction_label(
            movement_direction, guard_language)
        movement_pct = round(
            max(0.0, min(1.0, float(movement_confidence or 0.0))) * 100.0,
            1,
        )
        whatsapp_text = f"{whatsapp_text}\n*{movement_heading}:* {movement_line} ({movement_pct}%)"
        if multi_angle_verified:
            verification_note = {
                "en": "✅ Two-camera verification completed.",
                "hi": "✅ दो-कैमरा सत्यापन पूर्ण हुआ।",
                "mr": "✅ दोन-कॅमेरा पडताळणी पूर्ण झाली।",
            }.get(guard_language, "✅ Two-camera verification completed.")
            whatsapp_text = f"{whatsapp_text}\n{verification_note}"

        delivered = False
        failure_reason: str | None = None
        try:
            image_delivered = False
            text_delivered = False
            interactive_delivered = False
            image_failure_reason: str | None = None
            text_failure_reason: str | None = None
            interactive_failure_reason: str | None = None
            send_timeout = max(6.0, _waha_timeout_sec() + 2.0)
            text_payload = whatsapp_text

            if snapshot_path:
                try:
                    image_delivered, image_failure_reason = await asyncio.wait_for(
                        asyncio.to_thread(
                            _waha_send_image,
                            phone_digits,
                            base_whatsapp_text,
                            snapshot_path,
                        ),
                        timeout=send_timeout,
                    )
                except asyncio.TimeoutError:
                    image_failure_reason = f"WAHA sendImage timeout after {send_timeout:.0f}s"

            text_payload = _truncate_whatsapp_text(text_payload)

            # Always send localized text through /api/sendText after image attempt.
            try:
                text_delivered, text_failure_reason = await asyncio.wait_for(
                    asyncio.to_thread(
                        _waha_send_text,
                        phone_digits,
                        text_payload,
                    ),
                    timeout=send_timeout,
                )
            except asyncio.TimeoutError:
                text_failure_reason = f"WAHA sendText timeout after {send_timeout:.0f}s"

            if text_delivered:
                try:
                    incident_button_delivered = False
                    incident_button_failure_reason: str | None = None

                    if alert_id:
                        incident_button_delivered, incident_button_failure_reason = await asyncio.wait_for(
                            asyncio.to_thread(
                                _waha_send_alert_response_button,
                                phone_digits,
                                guard_language,
                                alert_id,
                            ),
                            timeout=send_timeout,
                        )

                    duty_button_delivered, duty_button_failure_reason = await asyncio.wait_for(
                        asyncio.to_thread(
                            _waha_send_duty_options,
                            phone_digits,
                            guard_language,
                        ),
                        timeout=send_timeout,
                    )

                    interactive_delivered = bool(
                        incident_button_delivered or duty_button_delivered
                    )

                    failure_parts: list[str] = []
                    if alert_id and (not incident_button_delivered) and incident_button_failure_reason:
                        failure_parts.append(
                            f"incident_button:{incident_button_failure_reason}")
                    if (not duty_button_delivered) and duty_button_failure_reason:
                        failure_parts.append(
                            f"duty_button:{duty_button_failure_reason}")
                    interactive_failure_reason = "; ".join(
                        failure_parts) if failure_parts else None
                except asyncio.TimeoutError:
                    interactive_failure_reason = f"WAHA interactive timeout after {send_timeout:.0f}s"

            delivered = bool(image_delivered or text_delivered)
            reason_parts: list[str] = []
            if (not image_delivered) and image_failure_reason:
                reason_parts.append(f"image:{image_failure_reason}")
            if (not text_delivered) and text_failure_reason:
                reason_parts.append(f"text:{text_failure_reason}")
            if text_delivered and (not interactive_delivered) and interactive_failure_reason:
                reason_parts.append(
                    f"interactive:{interactive_failure_reason}")
            if not delivered and not reason_parts:
                reason_parts.append("WAHA sendImage/sendText both failed")
            failure_reason = "; ".join(reason_parts) if reason_parts else None
        except Exception as exc:
            failure_reason = str(exc)
            print(
                f"[CAMERA] Failed to notify {r.get('email') or phone_digits}: {exc}")

        notification_doc = {
            "guard_id": r.get("guard_id"),
            "guard_name": r.get("full_name"),
            "email": r.get("email"),
            "phone_number": phone_digits,
            "alert_id": alert_id,
            "alert_type": alert_type,
            "subtype": subtype,
            "confidence": confidence,
            "frame_path": frame_path,
            "location": location or "AI Camera",
            "message": text_payload,
            "language": guard_language,
            "delivery_status": "sent" if delivered else "failed",
            "image_delivery_status": "sent" if image_delivered else "failed",
            "text_delivery_status": "sent" if text_delivered else "failed",
            "interactive_delivery_status": "sent" if interactive_delivered else "failed",
            "failure_reason": failure_reason,
            "ack_status": "pending",
            "created_at": datetime.now(timezone.utc),
        }
        await notifications_col.insert_one(notification_doc)
        results.append({
            "guard_id": r.get("guard_id"),
            "phone_number": phone_digits,
            "delivery_status": notification_doc["delivery_status"],
            "image_delivery_status": notification_doc["image_delivery_status"],
            "text_delivery_status": notification_doc["text_delivery_status"],
            "interactive_delivery_status": notification_doc["interactive_delivery_status"],
            "failure_reason": failure_reason,
        })

    return results


# Camera streaming is handled by a dedicated worker thread so that the FastAPI
# event loop is never blocked by OpenCV operations. The worker thread pushes
# MJPEG frame chunks into a small queue, and the HTTP endpoint streams those
# chunks to connected clients.

_camera_queues: dict[int, "queue.Queue[bytes]"] = {
    0: queue.Queue(maxsize=2),
    1: queue.Queue(maxsize=2),
}
_camera_worker_threads: dict[int, Thread | None] = {0: None, 1: None}
_ai_worker_threads: dict[int, Thread | None] = {0: None, 1: None}
_camera_thread_lock = Lock()
_ai_thread_lock = Lock()
_ai_frame_locks: dict[int, Lock] = {0: Lock(), 1: Lock()}
_latest_ai_frames: dict[int, np.ndarray | None] = {0: None, 1: None}
_latest_capture_camera_id = 0
_app_loop: asyncio.AbstractEventLoop | None = None
_app_loop_lock = Lock()


def _set_app_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _app_loop
    with _app_loop_lock:
        _app_loop = loop


def _resolve_submission_loop() -> asyncio.AbstractEventLoop:
    with _app_loop_lock:
        active_loop = _app_loop

    if active_loop is not None and not active_loop.is_closed() and active_loop.is_running():
        return active_loop

    if _bg_loop.is_closed() or not _bg_loop.is_running():
        raise RuntimeError(
            "No running asyncio loop available for camera async submission")
    return _bg_loop


def _submit_async(coro):
    """Submit coroutine from worker thread to the active asyncio loop."""
    target_loop = _resolve_submission_loop()
    return asyncio.run_coroutine_threadsafe(coro, target_loop)


def _submit_async_fire_and_forget(coro, task_name: str) -> None:
    """Schedule async work without blocking the camera/inference hot path."""
    try:
        future = _submit_async(coro)

        def _consume_result(done_future):
            try:
                done_future.result()
            except Exception as exc:
                logging.warning(
                    f"[CAMERA] Async task '{task_name}' failed: {exc}")

        future.add_done_callback(_consume_result)
    except Exception as exc:
        logging.warning(
            f"[CAMERA] Failed to submit async task '{task_name}': {exc}")


def _run_weapon_inference(frame: np.ndarray):
    if weapon_model is None:
        return None
    return weapon_model(
        frame,
        imgsz=DEFAULT_INFERENCE_IMAGE_SIZE,
        classes=_WEAPON_ALLOWED_CLASSES,
        verbose=False,
        half=INFERENCE_USE_HALF,
        device=INFERENCE_DEVICE,
    )


def _run_anomaly_inference(frame: np.ndarray):
    if anomaly_model is None:
        return None
    return anomaly_model(
        frame,
        imgsz=DEFAULT_INFERENCE_IMAGE_SIZE,
        classes=_ANOMALY_ALLOWED_CLASSES,
        verbose=False,
        half=INFERENCE_USE_HALF,
        device=INFERENCE_DEVICE,
    )


def _run_fire_inference(frame: np.ndarray):
    if fire_model is None:
        return None
    return fire_model(
        frame,
        imgsz=DEFAULT_INFERENCE_IMAGE_SIZE,
        classes=_FIRE_ALLOWED_CLASSES,
        verbose=False,
        half=INFERENCE_USE_HALF,
        device=INFERENCE_DEVICE,
    )


def _run_violence_inference(frame: np.ndarray):
    if violence_model is None:
        return None
    return violence_model(
        frame,
        imgsz=DEFAULT_INFERENCE_IMAGE_SIZE,
        classes=_VIOLENCE_ALLOWED_CLASSES,
        verbose=False,
        half=INFERENCE_USE_HALF,
        device=INFERENCE_DEVICE,
    )


def _open_camera_blocking(camera_id: int, camera_source: int | str) -> cv2.VideoCapture | None:
    """Try opening the camera using a few different backends.

    This is intended to run on a worker thread because some backends can block
    for several seconds if the camera is not available.
    """
    logging.info(
        "[CAMERA] Attempting to open camera_id=%s with source=%s",
        camera_id,
        camera_source,
    )

    backends = []
    if hasattr(cv2, "CAP_DSHOW"):
        backends.append(cv2.CAP_DSHOW)
    if hasattr(cv2, "CAP_MSMF"):
        backends.append(cv2.CAP_MSMF)
    backends.append(None)

    for backend in backends:
        try:
            cap = cv2.VideoCapture(
                camera_source, backend) if backend is not None else cv2.VideoCapture(camera_source)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, DEFAULT_CAMERA_FRAME_WIDTH)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, DEFAULT_CAMERA_FRAME_HEIGHT)
                cap.set(cv2.CAP_PROP_FPS, DEFAULT_CAMERA_FPS)
                logging.info(
                    "[CAMERA] Opened camera_id=%s using backend=%s",
                    camera_id,
                    backend or "default",
                )
                return cap
            cap.release()
        except Exception as exc:
            logging.warning(
                "[CAMERA] Failed to open camera_id=%s backend=%s: %s",
                camera_id,
                backend,
                exc,
            )
            continue

    logging.error(
        "[CAMERA] Unable to open camera_id=%s. Please check source and camera availability.",
        camera_id,
    )
    return None


def _make_mjpeg_frame(frame: np.ndarray) -> bytes:
    ret_enc, buffer = cv2.imencode(
        '.jpg',
        frame,
        [int(cv2.IMWRITE_JPEG_QUALITY), DEFAULT_STREAM_JPEG_QUALITY],
    )
    if not ret_enc:
        return b''
    return (b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')


def _make_placeholder_frame(message: str = "Camera unavailable") -> bytes:
    placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(placeholder, message, (10, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
    return _make_mjpeg_frame(placeholder)


def _put_frame(camera_id: int, frame_bytes: bytes) -> None:
    target_queue = _camera_queues[camera_id]
    try:
        target_queue.put_nowait(frame_bytes)
    except queue.Full:
        try:
            target_queue.get_nowait()
        except Exception:
            pass
        try:
            target_queue.put_nowait(frame_bytes)
        except Exception:
            pass


def _camera_location_label(camera_id: int) -> str:
    return CAMERA_LOCATIONS.get(camera_id, f"Camera {camera_id + 1} Area")


def _camera_worker(camera_id: int) -> None:
    """Streaming worker: read camera frames and push MJPEG chunks at 30 FPS."""

    global _latest_capture_camera_id
    camera_source = CAMERA_SOURCES.get(camera_id, camera_id)
    frame_interval = 1.0 / max(DEFAULT_CAMERA_FPS, 1.0)

    while True:
        cap = _open_camera_blocking(camera_id, camera_source)
        if not cap:
            _put_frame(
                camera_id,
                _make_placeholder_frame(
                    f"Camera {camera_id + 1} unavailable"
                ),
            )
            time.sleep(2.0)
            continue

        while True:
            loop_started = time.perf_counter()
            ret, frame = cap.read()
            if not ret:
                break

            # Share frame with AI worker for this camera.
            with _ai_frame_locks[camera_id]:
                _latest_ai_frames[camera_id] = frame.copy()
                _latest_capture_camera_id = camera_id

            with _detections_lock:
                latest = _latest_detections_by_camera.get(
                    camera_id, {"timestamp": 0, "boxes": []})
                if time.time() - float(latest.get("timestamp") or 0) < 1.0:
                    for (x1, y1, x2, y2, color, label, conf) in latest.get("boxes") or []:
                        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                        overlay_text = f"{label} {conf:.2f}"
                        cv2.putText(
                            frame,
                            overlay_text,
                            (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5,
                            color,
                            2,
                        )

            _put_frame(camera_id, _make_mjpeg_frame(frame))

            sleep_for = frame_interval - (time.perf_counter() - loop_started)
            if sleep_for > 0:
                time.sleep(sleep_for)

        cap.release()
        time.sleep(0.5)


def _ai_inference_worker(camera_id: int) -> None:
    """AI worker: run all models concurrently on latest snapshot without blocking stream."""
    previous_gray_frame = None
    executor = ThreadPoolExecutor(max_workers=4)

    while True:
        frame_to_process = None
        with _ai_frame_locks[camera_id]:
            latest_frame = _latest_ai_frames.get(camera_id)
            if latest_frame is not None:
                frame_to_process = latest_frame.copy()

        if frame_to_process is None:
            time.sleep(0.01)
            continue

        gray = cv2.cvtColor(frame_to_process, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if previous_gray_frame is None:
            previous_gray_frame = gray
            continue

        frame_delta = cv2.absdiff(previous_gray_frame, gray)
        thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
        moving_pixels = cv2.countNonZero(thresh)
        total_pixels = thresh.size
        motion_percentage = (moving_pixels / total_pixels) * 100

        previous_gray_frame = gray

        # Run all models concurrently
        try:
            futures = {
                "weapon": executor.submit(_run_weapon_inference, frame_to_process),
                "fire": executor.submit(_run_fire_inference, frame_to_process),
                "anomaly": executor.submit(_run_anomaly_inference, frame_to_process),
                "violence": executor.submit(_run_violence_inference, frame_to_process),
            }

            # Process results as they complete
            weapon_results = futures["weapon"].result(timeout=5)
            if weapon_results:
                _process_model_results(
                    weapon_results,
                    frame_to_process,
                    color=(0, 255, 0),
                    alert_type="weapon",
                    threshold=_system_detection_threshold,
                    ignore_labels=_WEAPON_IGNORE_LABELS,
                    cooldown_seconds=WEAPON_ALERT_COOLDOWN,
                    camera_id=camera_id,
                    camera_location=_camera_location_label(camera_id),
                )

            fire_results = futures["fire"].result(timeout=5)
            if fire_results:
                _process_model_results(
                    fire_results,
                    frame_to_process,
                    color=(0, 0, 255),
                    alert_type="fire",
                    threshold=_system_detection_threshold,
                    cooldown_seconds=FIRE_ALERT_COOLDOWN,
                    camera_id=camera_id,
                    camera_location=_camera_location_label(camera_id),
                )

            anomaly_results = futures["anomaly"].result(timeout=5)
            if anomaly_results:
                _process_model_results(
                    anomaly_results,
                    frame_to_process,
                    color=(255, 0, 0),
                    alert_type="anomaly",
                    threshold=_system_detection_threshold,
                    cooldown_seconds=ANOMALY_ALERT_COOLDOWN,
                    camera_id=camera_id,
                    camera_location=_camera_location_label(camera_id),
                )

            violence_results = futures["violence"].result(timeout=5)
            if violence_results:
                _process_model_results(
                    violence_results,
                    frame_to_process,
                    color=(0, 165, 255),
                    alert_type="violence",
                    threshold=_system_detection_threshold,
                    cooldown_seconds=VIOLENCE_ALERT_COOLDOWN,
                    camera_id=camera_id,
                    camera_location=_camera_location_label(camera_id),
                )
        except Exception as exc:
            logging.error(
                "[CAMERA] AI inference error camera_id=%s: %s",
                camera_id,
                exc,
            )

        # Yield thread without introducing an artificial throughput bottleneck.
        time.sleep(0.01)


def _start_camera_worker() -> None:
    with _camera_thread_lock:
        for camera_id in CAMERA_SOURCES.keys():
            worker = _camera_worker_threads.get(camera_id)
            if worker is None or not worker.is_alive():
                _camera_worker_threads[camera_id] = Thread(
                    target=_camera_worker,
                    args=(camera_id,),
                    daemon=True,
                )
                _camera_worker_threads[camera_id].start()
    with _ai_thread_lock:
        for camera_id in CAMERA_SOURCES.keys():
            worker = _ai_worker_threads.get(camera_id)
            if worker is None or not worker.is_alive():
                _ai_worker_threads[camera_id] = Thread(
                    target=_ai_inference_worker,
                    args=(camera_id,),
                    daemon=True,
                )
                _ai_worker_threads[camera_id].start()


async def camera_stream(camera_id: int = 0):
    """Async generator that streams MJPEG frames via FastAPI without blocking the event loop."""
    if camera_id not in CAMERA_SOURCES:
        raise RuntimeError(f"Unsupported camera_id={camera_id}")

    _set_app_loop(asyncio.get_running_loop())
    _start_camera_worker()
    while True:
        try:
            chunk = await asyncio.to_thread(
                _camera_queues[camera_id].get,
                True,
                1.0,
            )
        except queue.Empty:
            chunk = _make_placeholder_frame(f"Camera {camera_id + 1} waiting")
        yield chunk


@router.get("/camera/stream")
def stream_camera(request: Request, camera_id: int = 0):
    """
    MJPEG camera stream with AI detection overlays. Kept available at /camera/stream
    for backward compatibility. The backend now delivers frames at a strict 30 FPS.

    If the camera cannot be opened, a 500 HTTP error with a descriptive
    message will be returned instead of a blank response.
    """
    try:
        return StreamingResponse(
            camera_stream(camera_id=camera_id),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )
    except RuntimeError as exc:
        print(f"[CAMERA] stream error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/video_feed")
def video_feed(request: Request):
    """
    Root-level path expected by frontend `<img src="/video_feed" />`
    Streams at a strict 30 FPS for smooth viewing.

    This endpoint mirrors `/camera/stream` behavior including graceful
    error handling when the camera cannot be accessed.
    """
    try:
        return StreamingResponse(
            camera_stream(camera_id=0),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )
    except RuntimeError as exc:
        print(f"[CAMERA] video_feed error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/video_feed/{camera_id}")
def video_feed_by_camera(camera_id: int, request: Request):
    """Per-camera MJPEG feed for UI angle switching."""
    if camera_id not in CAMERA_SOURCES:
        raise HTTPException(status_code=404, detail="Invalid camera_id")
    try:
        return StreamingResponse(
            camera_stream(camera_id=camera_id),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )
    except RuntimeError as exc:
        print(f"[CAMERA] video_feed/{camera_id} error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/camera/capture-frame")
async def capture_current_frame(camera_id: int | None = None):
    """Grab the latest camera frame and save it as an evidence capture.

    Used by the frontend when a guard confirms a threat so the
    *current* live frame is preserved alongside the original detection frame.
    """
    target_camera_id = _latest_capture_camera_id if camera_id is None else int(
        camera_id)
    if target_camera_id not in CAMERA_SOURCES:
        raise HTTPException(status_code=404, detail="Invalid camera_id")

    with _ai_frame_locks[target_camera_id]:
        latest = _latest_ai_frames.get(target_camera_id)
        if latest is None:
            raise HTTPException(
                status_code=503, detail="No frame available yet")

        # Create a deep copy of the latest AI frame
        frame = latest.copy()

    # Save the frame to the "confirmed" directory
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"confirm_capture_{ts}.jpg"
    save_dir = CAPTURES_DIR / "confirmed"
    save_dir.mkdir(parents=True, exist_ok=True)
    filepath = save_dir / filename
    cv2.imwrite(str(filepath), frame)

    relative = f"confirmed/{filename}"
    return {
        "frame_path": relative,
        "camera_id": target_camera_id,
        "camera_location": _camera_location_label(target_camera_id),
    }


@router.post("/camera/upload-confirm-frame")
async def upload_confirm_frame(file: UploadFile = File(...)):
    """Accept a JPEG frame captured by the frontend (canvas snapshot) and save
    it into the confirmed captures directory."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    nparr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="Could not decode image")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"confirm_capture_{ts}.jpg"
    save_dir = CAPTURES_DIR / "confirmed"
    save_dir.mkdir(parents=True, exist_ok=True)
    filepath = save_dir / filename
    cv2.imwrite(str(filepath), img)
    relative = f"confirmed/{filename}"
    return {"frame_path": relative}


@router.post("/camera/test-weapon")
async def test_weapon(file: UploadFile = File(...)):
    """Test endpoint: run the weapon model on an uploaded image and return detections.

    Useful for debugging model behavior without streaming the camera.
    """
    if weapon_model is None:
        raise HTTPException(
            status_code=500, detail="Weapon model not loaded on server")

    data = await file.read()
    nparr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="Could not decode image")

    detections = []
    try:
        results = weapon_model(img, imgsz=256, verbose=False)
        for result in results:
            for box in result.boxes:
                conf = float(box.conf[0])
                cls_id = int(box.cls[0])
                label = result.names.get(cls_id, "weapon")
                if str(label).lower() == "background":
                    continue
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                detections.append({
                    "label": label,
                    "conf": conf,
                    "xy": [x1, y1, x2, y2],
                })
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Model inference error: {exc}")

    return {"detections": detections}


def reset_defaults():
    """Clear old footage and reset default settings."""
    base_path = os.path.join(os.path.dirname(__file__), "..", "captures")
    subdirectories = ["confirmed", "violence", "weapon"]

    for subdir in subdirectories:
        dir_path = os.path.join(base_path, subdir)
        if os.path.exists(dir_path):
            for root, dirs, files in os.walk(dir_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    os.remove(file_path)
                for dir in dirs:
                    shutil.rmtree(os.path.join(root, dir))

    logging.info("All old footage cleared and defaults reset.")
