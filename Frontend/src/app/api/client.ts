const API_BASE = "http://127.0.0.1:8000";

export interface AuthStartResponse {
  message: string;
  email: string;
}

export interface VerifyOtpResponse {
  access_token: string;
  token_type: string;
  email?: string;
  full_name?: string;
  role?: "admin" | "guard";
}

export interface AdminLoginPayload {
  email: string;
  password: string;
}

export interface AdminSignupPayload {
  first_name: string;
  middle_name: string;
  last_name: string;
  email: string;
  phone_number: string;
  password: string;
}

export interface GuardLoginPayload {
  first_name: string;
  middle_name: string;
  last_name: string;
  phone_number: string;
}

export interface GuardSignInPayload {
  phone_number: string;
}

export interface GuardLoginStartResponse {
  message: string;
  phone_number: string;
  otp_preview?: string;
}

function mapAuthErrorMessage(rawMessage: string): string {
  const message = String(rawMessage || "").trim();
  const lowered = message.toLowerCase();

  if (lowered.includes("full name") && (lowered.includes("already") || lowered.includes("registered"))) {
    return "This full name is already registered. Please use a unique name.";
  }

  if (lowered.includes("phone") && lowered.includes("already")) {
    return "This phone number is already registered.";
  }

  if (lowered.includes("email") && lowered.includes("already")) {
    return "This email is already registered.";
  }

  if (lowered.includes("does not match") && lowered.includes("guard profile")) {
    return "Name does not match the registered guard profile for this phone number.";
  }

  return message;
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text();
    let message = text || `Request failed with status ${res.status}`;

    try {
      const parsed = JSON.parse(text);
      if (parsed?.detail) {
        message = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail);
      }
    } catch {
      // Keep the original text when the backend didn't return JSON.
    }

    throw new Error(mapAuthErrorMessage(message));
  }
  return res.json() as Promise<T>;
}

export interface UserSettingsDto {
  sms_enabled?: boolean;
  email_enabled?: boolean;
  whatsapp_enabled?: boolean;
  detection_threshold?: number | null;
  preferred_language?: "en" | "hi" | "mr" | string;
  retention_days?: number | null;
  auto_archive?: boolean | null;
}

export async function getUserSettingsByEmail(email: string): Promise<{ settings: UserSettingsDto }> {
  const res = await fetch(`${API_BASE}/auth/user-settings?email=${encodeURIComponent(email)}`);
  return handleResponse<{ settings: UserSettingsDto }>(res);
}

export async function updateMyLanguage(
  token: string,
  preferredLanguage: "en" | "hi" | "mr"
): Promise<{ ok: boolean; preferred_language: "en" | "hi" | "mr"; email?: string; user_id?: string; role?: "admin" | "guard" | string }> {
  const res = await fetch(`${API_BASE}/auth/users/settings/language`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ preferred_language: preferredLanguage }),
  });
  return handleResponse<{ ok: boolean; preferred_language: "en" | "hi" | "mr"; email?: string; user_id?: string; role?: "admin" | "guard" | string }>(res);
}

export async function getMyLanguage(
  token: string
): Promise<{ ok: boolean; preferred_language: "en" | "hi" | "mr"; email?: string; user_id?: string; role?: "admin" | "guard" | string }> {
  const res = await fetch(`${API_BASE}/auth/users/settings/language`, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
  return handleResponse<{ ok: boolean; preferred_language: "en" | "hi" | "mr"; email?: string; user_id?: string; role?: "admin" | "guard" | string }>(res);
}

export async function login(email: string, password: string): Promise<AuthStartResponse> {
  const body = new URLSearchParams();
  body.append("username", email);
  body.append("password", password);

  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body,
  });

  return handleResponse<AuthStartResponse>(res);
}

export interface SignupPayload {
  full_name: string;
  email: string;
  phone_number: string;
  password: string;
}

export async function signup(data: SignupPayload): Promise<{ message: string; email: string }> {
  const res = await fetch(`${API_BASE}/auth/signup`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
  });
  return handleResponse<{ message: string; email: string }>(res);
}

export async function verifyOtp(email: string, otp: string): Promise<VerifyOtpResponse> {
  const params = new URLSearchParams();
  params.append("email", email);
  params.append("otp", otp);

  const res = await fetch(`${API_BASE}/auth/verify-otp?${params.toString()}`, {
    method: "POST",
  });

  return handleResponse<VerifyOtpResponse>(res);
}

export async function requestOtp(email: string): Promise<{ message: string }> {
  const params = new URLSearchParams();
  params.append("email", email);

  const res = await fetch(`${API_BASE}/auth/request-otp?${params.toString()}`, {
    method: "POST",
  });

  return handleResponse<{ message: string }>(res);
}

export async function adminLogin(data: AdminLoginPayload): Promise<VerifyOtpResponse> {
  const res = await fetch(`${API_BASE}/admin/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
  });
  return handleResponse<VerifyOtpResponse>(res);
}

export async function adminSignup(data: AdminSignupPayload): Promise<{ message: string; email: string }> {
  const res = await fetch(`${API_BASE}/admin/signup`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
  });
  return handleResponse<{ message: string; email: string }>(res);
}

export async function adminVerifyOtp(email: string, otp: string): Promise<VerifyOtpResponse> {
  const res = await fetch(`${API_BASE}/admin/verify-otp`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ email, otp }),
  });
  return handleResponse<VerifyOtpResponse>(res);
}

export async function adminForgotPassword(email: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/admin/forgot-password`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ email }),
  });
  return handleResponse<{ message: string }>(res);
}

export async function guardLoginStart(data: GuardLoginPayload): Promise<GuardLoginStartResponse> {
  const res = await fetch(`${API_BASE}/guard/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
  });
  return handleResponse<GuardLoginStartResponse>(res);
}

export async function guardSignInStart(data: GuardSignInPayload): Promise<GuardLoginStartResponse> {
  const res = await fetch(`${API_BASE}/guard/signin`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
  });
  return handleResponse<GuardLoginStartResponse>(res);
}

export async function guardVerifyOtp(phone_number: string, otp: string): Promise<VerifyOtpResponse> {
  const res = await fetch(`${API_BASE}/guard/verify-otp`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ phone_number, otp }),
  });
  return handleResponse<VerifyOtpResponse>(res);
}

export async function guardResendOtp(phone_number: string): Promise<GuardLoginStartResponse> {
  const res = await fetch(`${API_BASE}/guard/resend-otp`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ phone_number }),
  });
  return handleResponse<GuardLoginStartResponse>(res);
}

export interface AlertDto {
  id: string;
  type: string;
  subtype?: string | null;
  confidence: number;
  timestamp: string;
  location?: string;
  frame_id?: number;
  frame_path?: string;
  source_camera_id?: number | null;
  primary_camera_id?: number | null;
  multi_angle_verified?: boolean;
  evidence_urls?: string[];
  verified: boolean;
  status: "pending" | "confirmed" | "dismissed" | "resolved";
  ai_summary_en?: string | null;
  ai_summary_hi?: string | null;
  ai_summary_mr?: string | null;
  ai_narrative_en?: string | null;
  ai_narrative_hi?: string | null;
  ai_narrative_mr?: string | null;
  movement_direction?: string | null;
  movement_confidence?: number | null;
  narrative_generation_mode?: string | null;
  action_history?: Array<{
    action: string;
    by?: string | null;
    timestamp?: string;
  }>;
}

export interface ConfirmAlertResponse {
  modified_count: number;
  frame_path_used?: string | null;
  location?: string | null;
  primary_camera_id?: number | null;
  narrative?: {
    ai_summary_en?: string | null;
    ai_summary_hi?: string | null;
    ai_summary_mr?: string | null;
    ai_narrative_en?: string | null;
    ai_narrative_hi?: string | null;
    ai_narrative_mr?: string | null;
    movement_direction?: string | null;
    movement_confidence?: number | null;
    narrative_generation_mode?: string | null;
  };
}

export async function fetchAlerts(limit = 50): Promise<AlertDto[]> {
  const res = await fetch(`${API_BASE}/reports/alerts?limit=${limit}`);
  return handleResponse<AlertDto[]>(res);
}

export async function fetchVerifiedAlerts(limit = 50, phoneNumber?: string, createdAfter?: string): Promise<AlertDto[]> {
  const params = new URLSearchParams();
  params.append("limit", String(limit));
  if (phoneNumber) params.append("phone_number", phoneNumber);
  if (createdAfter) params.append("created_after", createdAfter);
  const res = await fetch(`${API_BASE}/reports/verified?${params.toString()}`);
  return handleResponse<AlertDto[]>(res);
}

export async function markAsVerified(alertId: string, email?: string): Promise<{ modified_count: number }> {
  const params = new URLSearchParams();
  if (email) params.append("email", email);

  const query = params.toString() ? `?${params.toString()}` : "";
  const res = await fetch(`${API_BASE}/reports/alerts/${encodeURIComponent(alertId)}/verify${query}`, {
    method: "PATCH",
  });
  return handleResponse<{ modified_count: number }>(res);
}

export async function confirmAlert(
  alertId: string,
  email?: string,
  confirmedFramePath?: string,
  primaryCameraId?: number,
): Promise<ConfirmAlertResponse> {
  const params = new URLSearchParams();
  if (email) params.append("email", email);
  if (confirmedFramePath) params.append("confirmed_frame_path", confirmedFramePath);
  if (typeof primaryCameraId === "number") params.append("primary_camera_id", String(primaryCameraId));

  const query = params.toString() ? `?${params.toString()}` : "";
  const res = await fetch(`${API_BASE}/reports/alerts/${encodeURIComponent(alertId)}/confirm${query}`, {
    method: "PATCH",
  });
  return handleResponse<ConfirmAlertResponse>(res);
}

export async function markAsFalseAlarm(alertId: string, email?: string): Promise<{ modified_count: number }> {
  const params = new URLSearchParams();
  if (email) params.append("email", email);

  const query = params.toString() ? `?${params.toString()}` : "";
  const res = await fetch(`${API_BASE}/reports/alerts/${encodeURIComponent(alertId)}/false-alarm${query}`, {
    method: "PATCH",
  });
  return handleResponse<{ modified_count: number }>(res);
}
export interface SummaryDto {
  total_alerts: number;
  verified_alerts?: number;
  false_alarms?: number;
  weapon_alerts: number;
  violence_alerts: number;
  fire_alerts: number;
}

export interface SystemRuntimeStatsDto {
  captured_frames: number;
  captures_storage_bytes: number;
  mongodb_storage_bytes: number;
  mongodb_alerts_storage_bytes: number;
}

export interface AnalyticsSummaryDto {
  period: {
    from?: string | null;
    to?: string | null;
  };
  overall: {
    total_alerts: number;
    verified_count: number;
    confirmed_count: number;
    two_angle_verified_count: number;
    false_alarm_count: number;
    pending_count: number;
    verified_rate: number;
    false_alarm_rate: number;
    avg_confidence: number;
  };
  response_metrics: {
    avg_response_seconds: number;
    p95_response_seconds: number;
    samples: number;
  };
  by_type: Record<string, {
    total: number;
    verified: number;
    confirmed: number;
    false_alarm: number;
    pending: number;
  }>;
  top_verifiers: Array<{
    email: string;
    handled: number;
    avg_response_seconds: number;
  }>;
}

export interface FalseAlarmAnalyticsDto {
  total: number;
  by_type: Record<string, number>;
  by_confidence_range: {
    low_lt_0_50: number;
    medium_0_50_to_0_80: number;
    high_gt_0_80: number;
  };
  by_guard: Array<{
    email: string;
    count: number;
  }>;
  recent: AlertDto[];
}

export interface TrendPointDto {
  bucket: string;
  total: number;
  verified: number;
  false_alarm: number;
  pending: number;
}

export interface AlertTrendDto {
  granularity: "hourly" | "daily" | "weekly";
  period: {
    from?: string | null;
    to?: string | null;
  };
  data: TrendPointDto[];
}

export interface GuardPerformanceDto {
  period: {
    from?: string | null;
    to?: string | null;
  };
  on_duty_count?: number;
  off_duty_count?: number;
  guards: Array<{
    guard_id: string;
    guard_name: string;
    phone_number?: string | null;
    email: string;
    duty_status: "on_duty" | "off_duty";
    shifts: number;
    total_minutes: number;
    alerts_handled: number;
    verified_or_confirmed: number;
    false_alarms: number;
    avg_response_seconds: number;
    alerts_per_hour: number;
    false_alarm_rate: number;
  }>;
}

export interface AdminActivityDto {
  total_admins: number;
  verified_admins: number;
  active_admins: number;
  admins: Array<{
    id: string;
    full_name: string;
    email?: string | null;
    phone_number?: string | null;
    is_verified: boolean;
    status: "active" | "offline";
    created_at?: string | null;
    last_login?: string | null;
    last_logout?: string | null;
  }>;
}

export async function adminLogout(email: string): Promise<{ message: string; email?: string; session_active: boolean; last_logout?: string | null }> {
  const res = await fetch(`${API_BASE}/admin/logout`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ email }),
  });
  return handleResponse<{ message: string; email?: string; session_active: boolean; last_logout?: string | null }>(res);
}

export interface DutyLogDto {
  id: string;
  guardId: string;
  guardName?: string | null;
  phone_number?: string | null;
  checkInTime: string;
  checkOutTime?: string | null;
  totalAlertsReceived: number;
}

export async function fetchFalseAlarms(limit = 50): Promise<AlertDto[]> {
  const res = await fetch(`${API_BASE}/reports/alerts/false-alarms?limit=${limit}`);
  return handleResponse<AlertDto[]>(res);
}

export async function fetchSummary(): Promise<SummaryDto> {
  const res = await fetch(`${API_BASE}/reports/summary`);
  return handleResponse<SummaryDto>(res);
}

export async function fetchSystemRuntimeStats(): Promise<SystemRuntimeStatsDto> {
  const res = await fetch(`${API_BASE}/reports/system-runtime-stats`);
  return handleResponse<SystemRuntimeStatsDto>(res);
}

export async function fetchAnalyticsSummary(dateFrom?: string, dateTo?: string): Promise<AnalyticsSummaryDto> {
  const params = new URLSearchParams();
  if (dateFrom) params.append("date_from", dateFrom);
  if (dateTo) params.append("date_to", dateTo);
  const query = params.toString() ? `?${params.toString()}` : "";
  const res = await fetch(`${API_BASE}/reports/analytics/summary${query}`);
  return handleResponse<AnalyticsSummaryDto>(res);
}

export async function fetchFalseAlarmAnalytics(limit = 50, dateFrom?: string, dateTo?: string): Promise<FalseAlarmAnalyticsDto> {
  const params = new URLSearchParams();
  params.append("limit", String(limit));
  if (dateFrom) params.append("date_from", dateFrom);
  if (dateTo) params.append("date_to", dateTo);
  const res = await fetch(`${API_BASE}/reports/analytics/false-alarms?${params.toString()}`);
  return handleResponse<FalseAlarmAnalyticsDto>(res);
}

export async function fetchAlertTrends(granularity: "hourly" | "daily" | "weekly", dateFrom?: string, dateTo?: string): Promise<AlertTrendDto> {
  const params = new URLSearchParams();
  params.append("granularity", granularity);
  if (dateFrom) params.append("date_from", dateFrom);
  if (dateTo) params.append("date_to", dateTo);
  const res = await fetch(`${API_BASE}/reports/analytics/trend?${params.toString()}`);
  return handleResponse<AlertTrendDto>(res);
}

export async function fetchGuardPerformance(dateFrom?: string, dateTo?: string): Promise<GuardPerformanceDto> {
  const params = new URLSearchParams();
  if (dateFrom) params.append("date_from", dateFrom);
  if (dateTo) params.append("date_to", dateTo);
  const query = params.toString() ? `?${params.toString()}` : "";
  const res = await fetch(`${API_BASE}/reports/analytics/guard-performance${query}`);
  return handleResponse<GuardPerformanceDto>(res);
}

export async function fetchAdminActivity(limit = 200): Promise<AdminActivityDto> {
  const params = new URLSearchParams();
  params.append("limit", String(limit));
  const res = await fetch(`${API_BASE}/reports/analytics/admin-activity?${params.toString()}`);
  return handleResponse<AdminActivityDto>(res);
}

export async function fetchDutyLogs(limit = 200): Promise<DutyLogDto[]> {
  const params = new URLSearchParams();
  params.append("limit", String(limit));
  const res = await fetch(`${API_BASE}/reports/analytics/duty-logs?${params.toString()}`);
  return handleResponse<DutyLogDto[]>(res);
}

export function buildGuardActivityExcelExportUrl(days: 3 | 7 = 7): string {
  const params = new URLSearchParams();
  params.append("days", String(days));
  params.append("include_guard", "true");
  params.append("include_admin", "false");
  return `${API_BASE}/reports/analytics/duty-logs/export?${params.toString()}`;
}

export interface ChatResponse {
  intent: string;
  response: string;
  source?: "gemini" | "fallback";
  context_mode?: "summary" | "full";
  suggestions?: string[];
}

export async function askChat(query: string, email?: string, imageFile?: File | null, language?: string): Promise<ChatResponse> {
  const form = new FormData();
  form.append("query", query);
  if (email) {
    form.append("email", email);
  }
  if (language) {
    form.append("language", language);
  }
  if (imageFile) {
    form.append("image", imageFile, imageFile.name || "chat-image.jpg");
  }

  const res = await fetch(`${API_BASE}/chat/ask`, {
    method: "POST",
    body: form,
  });
  return handleResponse<ChatResponse>(res);
}

export const CAMERA_STREAM_URL = `${API_BASE}/camera/stream`;
export const cameraStreamUrlById = (cameraId: number) => `${API_BASE}/video_feed/${cameraId}`;

/** Ask the backend to grab the current camera frame and persist it. */
export async function captureCurrentFrame(cameraId?: number): Promise<{ frame_path: string; camera_id?: number; camera_location?: string }> {
  const query = typeof cameraId === "number" ? `?camera_id=${encodeURIComponent(String(cameraId))}` : "";
  const res = await fetch(`${API_BASE}/camera/capture-frame${query}`, { method: "POST" });
  return handleResponse<{ frame_path: string; camera_id?: number; camera_location?: string }>(res);
}

/** Upload a canvas-captured JPEG blob to the backend for storage. */
export async function uploadConfirmFrame(blob: Blob): Promise<{ frame_path: string }> {
  const form = new FormData();
  form.append("file", blob, "confirm_capture.jpg");
  const res = await fetch(`${API_BASE}/camera/upload-confirm-frame`, {
    method: "POST",
    body: form,
  });
  return handleResponse<{ frame_path: string }>(res);
}

// Guard duty helpers
export async function goOnDuty(email: string): Promise<any> {
  const body = new URLSearchParams();
  body.append("email", email);

  const res = await fetch(`${API_BASE}/guard-duty/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  return handleResponse<any>(res);
}

export async function goOffDuty(email: string): Promise<any> {
  const body = new URLSearchParams();
  body.append("email", email);

  const res = await fetch(`${API_BASE}/guard-duty/logout`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  return handleResponse<any>(res);
}

export async function getGuardStatus(email: string): Promise<any> {
  const res = await fetch(`${API_BASE}/guard-duty/current-status/${encodeURIComponent(email)}`);
  return handleResponse<any>(res);
}

export async function goOnDutyByPhone(phoneNumber: string): Promise<any> {
  const body = new URLSearchParams();
  body.append("phone_number", phoneNumber);

  const res = await fetch(`${API_BASE}/guard-duty/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  return handleResponse<any>(res);
}

export async function goOffDutyByPhone(phoneNumber: string): Promise<any> {
  const body = new URLSearchParams();
  body.append("phone_number", phoneNumber);

  const res = await fetch(`${API_BASE}/guard-duty/logout`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  return handleResponse<any>(res);
}

export async function getGuardStatusByPhone(phoneNumber: string): Promise<any> {
  const res = await fetch(`${API_BASE}/guard-duty/current-status/${encodeURIComponent(phoneNumber)}`);
  return handleResponse<any>(res);
}

export interface GuardPreferencesResponse {
  preferred_language: "en" | "hi" | "mr";
  phone_number?: string;
  whatsapp_enabled?: boolean;
}

export async function getGuardPreferences(identifier: string): Promise<GuardPreferencesResponse> {
  const res = await fetch(`${API_BASE}/guard-duty/preferences/${encodeURIComponent(identifier)}`);
  return handleResponse<GuardPreferencesResponse>(res);
}

export async function updateGuardPreferences(
  identifier: string,
  preferredLanguage?: string,
  whatsappEnabled?: boolean
): Promise<{ ok: boolean; preferred_language: "en" | "hi" | "mr"; phone_number?: string; whatsapp_enabled?: boolean }> {
  const payload: Record<string, unknown> = {
    identifier,
    phone_number: identifier,
  };
  if (typeof preferredLanguage === "string" && preferredLanguage.trim()) {
    payload.preferred_language = preferredLanguage;
  }
  if (typeof whatsappEnabled === "boolean") {
    payload.whatsapp_enabled = whatsappEnabled;
  }

  const res = await fetch(`${API_BASE}/guard-duty/preferences`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  return handleResponse<{ ok: boolean; preferred_language: "en" | "hi" | "mr"; phone_number?: string; whatsapp_enabled?: boolean }>(res);
}

export interface SettingsHealthDto {
  waha_connected: boolean;
  gemini_connected: boolean;
  email_connected: boolean;
  last_checked_at: string;
}

export interface MaintenanceSettingsDto {
  retention_days: number;
  auto_archive: boolean;
}

export interface SettingsAuditEntryDto {
  id: string;
  actor: string;
  category: string;
  field: string;
  old_value?: string | null;
  new_value?: string | null;
  timestamp?: string;
}

export async function getSettingsHealth(): Promise<SettingsHealthDto> {
  const res = await fetch(`${API_BASE}/auth/settings-health`);
  return handleResponse<SettingsHealthDto>(res);
}

export async function getMaintenanceSettings(): Promise<{ maintenance_settings: MaintenanceSettingsDto }> {
  const res = await fetch(`${API_BASE}/auth/maintenance-settings`);
  return handleResponse<{ maintenance_settings: MaintenanceSettingsDto }>(res);
}

export async function updateMaintenanceSettings(
  maintenance: MaintenanceSettingsDto,
  actorEmail?: string
): Promise<{ ok: boolean; maintenance_settings: MaintenanceSettingsDto }> {
  const params = new URLSearchParams();
  if (actorEmail) {
    params.append("actor_email", actorEmail);
  }
  const query = params.toString() ? `?${params.toString()}` : "";
  const res = await fetch(`${API_BASE}/auth/maintenance-settings${query}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(maintenance),
  });
  return handleResponse<{ ok: boolean; maintenance_settings: MaintenanceSettingsDto }>(res);
}

export async function clearOldFootage(
  retentionDays: number,
  actorEmail?: string
): Promise<{ ok: boolean; retention_days: number; deleted_files: number; scanned_files: number; freed_bytes: number }> {
  const params = new URLSearchParams();
  params.append("retention_days", String(retentionDays));
  if (actorEmail) {
    params.append("actor_email", actorEmail);
  }
  const res = await fetch(`${API_BASE}/auth/maintenance/clear-old-footage?${params.toString()}`, {
    method: "POST",
  });
  return handleResponse<{ ok: boolean; retention_days: number; deleted_files: number; scanned_files: number; freed_bytes: number }>(res);
}

export async function resetDefaults(
  actorEmail?: string
): Promise<{
  ok: boolean;
  message: string;
  deleted_files: number;
  scanned_files: number;
  freed_bytes: number;
  system_settings: { detection_threshold: number; weapon_cooldown_seconds: number };
  maintenance_settings: { retention_days: number; auto_archive: boolean };
}> {
  const params = new URLSearchParams();
  params.append("confirm", "true");
  if (actorEmail) {
    params.append("actor_email", actorEmail);
  }
  const res = await fetch(`${API_BASE}/auth/maintenance/reset-defaults?${params.toString()}`, {
    method: "POST",
  });
  return handleResponse<{
    ok: boolean;
    message: string;
    deleted_files: number;
    scanned_files: number;
    freed_bytes: number;
    system_settings: { detection_threshold: number; weapon_cooldown_seconds: number };
    maintenance_settings: { retention_days: number; auto_archive: boolean };
  }>(res);
}

export async function getSettingsAudit(limit = 20): Promise<{ entries: SettingsAuditEntryDto[] }> {
  const res = await fetch(`${API_BASE}/auth/settings-audit?limit=${limit}`);
  return handleResponse<{ entries: SettingsAuditEntryDto[] }>(res);
}
