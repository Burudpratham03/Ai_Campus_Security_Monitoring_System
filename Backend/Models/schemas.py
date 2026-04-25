from datetime import datetime
from typing import Optional, List, Literal

from pydantic import BaseModel, EmailStr, Field


IncidentStatus = Literal["pending", "confirmed", "dismissed", "resolved"]


class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    preferred_language: str = "en"


class UserCreate(UserBase):
    password: str = Field(min_length=6)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserInDB(UserBase):
    id: str
    hashed_password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    role: Optional[str] = None


class OTPRequest(BaseModel):
    email: EmailStr


class CameraAlert(BaseModel):
    type: str  # "weapon" or "violence"
    confidence: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    frame_id: Optional[int] = None
    details: Optional[dict] = None


class AlertInDB(CameraAlert):
    id: str


class Report(BaseModel):
    title: str
    description: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    related_alert_ids: Optional[List[str]] = None


class ReportInDB(Report):
    id: str


class UserSettings(BaseModel):
    sms_enabled: bool = True
    email_enabled: bool = True
    whatsapp_enabled: bool = True
    # Per-user detection threshold (0-100 percent). If absent, system setting is used.
    detection_threshold: Optional[int] = None
    # Preferred UI/chat language code (persisted in DB and used by frontend).
    preferred_language: str = "en"
    # Optional maintenance preferences kept for future per-user overrides.
    retention_days: Optional[int] = None
    auto_archive: Optional[bool] = None


class UserLanguageUpdateRequest(BaseModel):
    preferred_language: str = "en"


class SystemSettings(BaseModel):
    # Global detection threshold (percent). Applies when user doesn't override.
    detection_threshold: int = 85
    # For weapon alerts: cooldown in seconds between notifications (default 3 minutes)
    weapon_cooldown_seconds: int = 180


class MaintenanceSettings(BaseModel):
    retention_days: int = 30
    auto_archive: bool = True


class SettingsHealthResponse(BaseModel):
    waha_connected: bool
    gemini_connected: bool
    email_connected: bool
    last_checked_at: datetime = Field(default_factory=datetime.utcnow)


class SettingsAuditEntry(BaseModel):
    actor: str
    category: str
    field: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str


class AdminSignupRequest(BaseModel):
    first_name: str = Field(min_length=1)
    middle_name: str = Field(default="")
    last_name: str = Field(min_length=1)
    email: EmailStr
    phone_number: str = Field(min_length=6)
    password: str = Field(min_length=6)


class AdminVerifyOtpRequest(BaseModel):
    email: EmailStr
    otp: str = Field(min_length=4, max_length=6)


class GuardLoginRequest(BaseModel):
    first_name: str = Field(min_length=1)
    middle_name: str = Field(default="")
    last_name: str = Field(min_length=1)
    phone_number: str = Field(min_length=6)


class GuardSignInRequest(BaseModel):
    phone_number: str = Field(min_length=6)


class GuardVerifyOtpRequest(BaseModel):
    phone_number: str = Field(min_length=6)
    otp: str = Field(min_length=4, max_length=6)


class IncidentRecord(BaseModel):
    type: str
    subtype: Optional[str] = None
    confidence: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    frame_id: Optional[int] = None
    frame_path: Optional[str] = None
    verified: bool = False
    status: IncidentStatus = "pending"
    dispatched_at: Optional[datetime] = None
    action_history: List[dict] = Field(default_factory=list)
    location: Optional[str] = None
    source_camera_id: Optional[int] = None
    primary_camera_id: Optional[int] = None
    multi_angle_verified: bool = False
    evidence_urls: List[str] = Field(default_factory=list)
    ai_summary_en: Optional[str] = None
    ai_summary_hi: Optional[str] = None
    ai_summary_mr: Optional[str] = None
    ai_narrative_en: Optional[str] = None
    ai_narrative_hi: Optional[str] = None
    ai_narrative_mr: Optional[str] = None
    movement_direction: Optional[str] = None
    movement_confidence: Optional[float] = None
    narrative_generation_mode: Optional[str] = None

    class Config:
        extra = "forbid"


class MediaRecord(BaseModel):
    incident_id: str
    media_type: str = "image"
    frame_path: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        extra = "forbid"


class LogbookEntry(BaseModel):
    guard_id: Optional[str] = None
    guard_name: str
    phone_number: Optional[str] = None
    phone_normalized: Optional[str] = None
    email: Optional[str] = None
    email_normalized: Optional[str] = None
    login_time: datetime
    logout_time: Optional[datetime] = None
    alerts_handled: List[str] = Field(default_factory=list)
    duration_minutes: float = 0.0

    class Config:
        extra = "forbid"


class DutyLogEntry(BaseModel):
    guardId: str
    checkInTime: datetime
    checkOutTime: Optional[datetime] = None
    totalAlertsReceived: int = 0

    class Config:
        extra = "forbid"
