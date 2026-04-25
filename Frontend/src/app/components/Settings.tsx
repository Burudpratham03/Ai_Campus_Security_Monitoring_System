import {
  Bell,
  Bot,
  CheckCircle2,
  ChevronRight,
  Gauge,
  Globe,
  HardDrive,
  Languages,
  MessageSquare,
  Power,
  Save,
  ShieldAlert,
  Trash2,
  Workflow,
  XCircle,
} from "lucide-react";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";

import {
  adminLogout,
  clearOldFootage,
  fetchSystemRuntimeStats,
  getMyLanguage,
  updateMyLanguage,
  getMaintenanceSettings,
  getSettingsAudit,
  getSettingsHealth,
  getGuardPreferences,
  resetDefaults,
  updateGuardPreferences,
  updateMaintenanceSettings,
  type SettingsAuditEntryDto,
  type SettingsHealthDto,
  type SystemRuntimeStatsDto,
} from "../api/client";
import {
  LANGUAGE_OPTIONS,
  type AppLanguage,
  getAppLanguage,
  normalizeLanguage,
  t,
} from "../utils/language";
import { useLanguage } from "../context/LanguageContext";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";

type BannerTone = "success" | "error" | "info";
type SectionKey = "channels" | "policy" | "language" | "maintenance";

interface BannerState {
  tone: BannerTone;
  message: string;
}

interface SettingsForm {
  whatsappEnabled: boolean;
  detectionThreshold: number;
  cooldownSeconds: number;
  language: "en" | "hi" | "mr";
  retentionDays: number;
  autoArchive: boolean;
}

const DEFAULT_FORM: SettingsForm = {
  whatsappEnabled: true,
  detectionThreshold: 85,
  cooldownSeconds: 180,
  language: "en",
  retentionDays: 30,
  autoArchive: true,
};

const API_BASE = "http://127.0.0.1:8000";

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const decimals = unitIndex === 0 ? 0 : 2;
  return `${value.toFixed(decimals)} ${units[unitIndex]}`;
}

function formatAuditTime(value?: string): string {
  if (!value) return "Unknown time";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function filterAuditEntriesForDisplay(entries: SettingsAuditEntryDto[]): SettingsAuditEntryDto[] {
  return (entries || []).filter((item) => {
    const field = String(item.field || "").toLowerCase();
    return field !== "clear_old_footage" && field !== "reset_defaults";
  });
}

function toUsagePercent(bytes: number, maxBytes: number): number {
  if (!maxBytes || bytes <= 0) return 0;
  return Math.min(100, Math.round((bytes / maxBytes) * 100));
}

function usageWidthClass(percent: number): string {
  if (percent >= 100) return "w-full";
  if (percent >= 90) return "w-11/12";
  if (percent >= 80) return "w-10/12";
  if (percent >= 70) return "w-9/12";
  if (percent >= 60) return "w-8/12";
  if (percent >= 50) return "w-7/12";
  if (percent >= 40) return "w-6/12";
  if (percent >= 30) return "w-5/12";
  if (percent >= 20) return "w-4/12";
  if (percent >= 10) return "w-3/12";
  if (percent >= 5) return "w-2/12";
  return "w-1/12";
}

function deepEqual(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function ToggleRow({
  icon,
  title,
  description,
  checked,
  onChange,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between rounded-2xl border border-slate-200 bg-white/70 px-4 py-3">
      <div className="flex items-start gap-3">
        <div className="mt-1 text-slate-500">{icon}</div>
        <div>
          <p className="font-semibold text-slate-900">{title}</p>
          <p className="text-sm text-slate-500">{description}</p>
        </div>
      </div>
      <label className="relative inline-flex cursor-pointer items-center">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          className="peer sr-only"
          aria-label={title}
        />
        <span className="h-6 w-11 rounded-full bg-slate-200 transition-all duration-300 after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:bg-white after:transition-all after:duration-300 peer-checked:bg-blue-600 peer-checked:after:translate-x-full" />
      </label>
    </div>
  );
}

function SectionShell({
  id,
  language,
  icon,
  title,
  description,
  dirty,
  onSave,
  onReset,
  saving,
  children,
}: {
  id: string;
  language: AppLanguage;
  icon: ReactNode;
  title: string;
  description: string;
  dirty: boolean;
  onSave: () => void;
  onReset: () => void;
  saving: boolean;
  children: ReactNode;
}) {
  return (
    <section id={id} className="rounded-3xl border border-slate-200 bg-white/80 p-6 shadow-xl backdrop-blur-md md:p-7">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="rounded-2xl bg-slate-100 p-3 text-slate-700">{icon}</div>
          <div>
            <h3 className="text-xl font-semibold text-slate-900">{title}</h3>
            <p className="text-sm text-slate-500">{description}</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${dirty ? "bg-amber-50 text-amber-700 ring-1 ring-amber-200" : "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200"}`}>
            {dirty ? t(language, "unsaved") : t(language, "synced")}
          </span>
          <button
            type="button"
            onClick={onReset}
            disabled={!dirty || saving}
            className="rounded-xl border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 transition-all duration-300 hover:border-slate-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t(language, "reset")}
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={!dirty || saving}
            className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-3 py-2 text-sm font-semibold text-white transition-all duration-300 hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Save className="h-4 w-4" />
            {saving ? t(language, "saving") : t(language, "save")}
          </button>
        </div>
      </div>
      {children}
    </section>
  );
}

export function Settings() {
  const navigate = useNavigate();
  const { currentLanguage: language, changeLanguage } = useLanguage();
  const [form, setForm] = useState<SettingsForm>(DEFAULT_FORM);
  const [baseline, setBaseline] = useState<SettingsForm>(DEFAULT_FORM);
  const [banner, setBanner] = useState<BannerState | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingGlobal, setSavingGlobal] = useState(false);
  const [savingSection, setSavingSection] = useState<Record<SectionKey, boolean>>({
    channels: false,
    policy: false,
    language: false,
    maintenance: false,
  });
  const [simLoading, setSimLoading] = useState(false);
  const [confirmAction, setConfirmAction] = useState<null | "clear-footage" | "reset-all">(null);
  const [stats, setStats] = useState<SystemRuntimeStatsDto>({
    captured_frames: 0,
    captures_storage_bytes: 0,
    mongodb_storage_bytes: 0,
    mongodb_alerts_storage_bytes: 0,
  });
  const [health, setHealth] = useState<SettingsHealthDto>({
    waha_connected: false,
    gemini_connected: false,
    email_connected: false,
    last_checked_at: new Date().toISOString(),
  });
  const [auditEntries, setAuditEntries] = useState<SettingsAuditEntryDto[]>([]);

  const hasUnsaved = useMemo(() => !deepEqual(form, baseline), [form, baseline]);

  const dirtyMap = useMemo(() => ({
    channels: form.whatsappEnabled !== baseline.whatsappEnabled,
    policy:
      form.detectionThreshold !== baseline.detectionThreshold ||
      form.cooldownSeconds !== baseline.cooldownSeconds,
    language: form.language !== baseline.language,
    maintenance:
      form.retentionDays !== baseline.retentionDays ||
      form.autoArchive !== baseline.autoArchive,
  }), [form, baseline]);

  const setSectionSaving = (section: SectionKey, value: boolean) => {
    setSavingSection((prev) => ({ ...prev, [section]: value }));
  };

  const setNotice = (tone: BannerTone, message: string) => setBanner({ tone, message });

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const next: SettingsForm = { ...DEFAULT_FORM, language: getAppLanguage() };
        const email = localStorage.getItem("authEmail");
        const authToken = localStorage.getItem("authToken") || localStorage.getItem("token");
        const phone = localStorage.getItem("authPhone");
        const guardIdentifier = phone || email || "";

        const [sysRes, statsRes, maintenanceRes, healthRes, auditRes] = await Promise.allSettled([
          fetch(`${API_BASE}/auth/system-settings`),
          fetchSystemRuntimeStats(),
          getMaintenanceSettings(),
          getSettingsHealth(),
          getSettingsAudit(20),
        ]);

        if (sysRes.status === "fulfilled" && sysRes.value.ok) {
          const payload = await sysRes.value.json();
          const system = payload?.system_settings || {};
          if (typeof system.detection_threshold === "number") {
            next.detectionThreshold = system.detection_threshold;
          }
          if (typeof system.weapon_cooldown_seconds === "number") {
            next.cooldownSeconds = system.weapon_cooldown_seconds;
          }
        }

        if (statsRes.status === "fulfilled") {
          setStats(statsRes.value);
        }

        if (maintenanceRes.status === "fulfilled") {
          const maintenance = maintenanceRes.value.maintenance_settings;
          if (typeof maintenance.retention_days === "number") {
            next.retentionDays = maintenance.retention_days;
          }
          if (typeof maintenance.auto_archive === "boolean") {
            next.autoArchive = maintenance.auto_archive;
          }
        }

        if (healthRes.status === "fulfilled") {
          setHealth(healthRes.value);
        }

        if (auditRes.status === "fulfilled") {
          setAuditEntries(filterAuditEntriesForDisplay(auditRes.value.entries || []));
        }

        if (email) {
          const userRes = await fetch(`${API_BASE}/auth/user-settings?email=${encodeURIComponent(email)}`);
          if (userRes.ok) {
            const userPayload = await userRes.json();
            const userSettings = userPayload?.settings || {};
            if (typeof userSettings.detection_threshold === "number") {
              next.detectionThreshold = userSettings.detection_threshold;
            }
          }
        }

        if (authToken) {
          try {
            const langRes = await getMyLanguage(authToken);
            next.language = normalizeLanguage(langRes.preferred_language) as "en" | "hi" | "mr";
            if (langRes.user_id) {
              localStorage.setItem("user_id", langRes.user_id);
            }
          } catch (error) {
            console.error("Failed to load authenticated language", error);
          }
        }

        if (guardIdentifier) {
          try {
            const pref = await getGuardPreferences(guardIdentifier);
            if (typeof pref.whatsapp_enabled === "boolean") {
              next.whatsappEnabled = pref.whatsapp_enabled;
            }
          } catch (error) {
            console.error("Failed to load guard WhatsApp preferences", error);
          }
        }

        setForm(next);
        setBaseline(next);
        changeLanguage(next.language);
      } catch (error) {
        console.error(error);
        setNotice("error", "Failed to load settings. Please retry.");
      } finally {
        setLoading(false);
      }
    };

    void load();
  }, []);

  const persistUserSettings = async (data: SettingsForm) => {
    const email = localStorage.getItem("authEmail");
    if (!email) {
      return;
    }

    const res = await fetch(`${API_BASE}/auth/user-settings?email=${encodeURIComponent(email)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sms_enabled: true,
        email_enabled: true,
        whatsapp_enabled: data.whatsappEnabled,
        detection_threshold: data.detectionThreshold,
        retention_days: data.retentionDays,
        auto_archive: data.autoArchive,
      }),
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || "Unable to persist user settings");
    }
  };

  const persistSystemSettings = async (data: SettingsForm) => {
    const res = await fetch(`${API_BASE}/auth/system-settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        detection_threshold: data.detectionThreshold,
        weapon_cooldown_seconds: data.cooldownSeconds,
      }),
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || "Unable to persist system settings");
    }
  };

  const saveAll = async () => {
    setSavingGlobal(true);
    setBanner(null);
    try {
      const actorEmail = localStorage.getItem("authEmail") || undefined;
      const guardIdentifier = localStorage.getItem("authPhone") || localStorage.getItem("authEmail") || "";
      const tasks: Array<Promise<unknown>> = [
        persistSystemSettings(form),
        persistUserSettings(form),
        updateMaintenanceSettings({
          retention_days: form.retentionDays,
          auto_archive: form.autoArchive,
        }, actorEmail),
      ];
      if (guardIdentifier) {
        tasks.push(updateGuardPreferences(guardIdentifier, undefined, form.whatsappEnabled));
      }
      await Promise.all(tasks);
      changeLanguage(form.language);
      const authToken = localStorage.getItem("authToken") || localStorage.getItem("token");
      if (authToken) {
        await updateMyLanguage(authToken, form.language);
      }
      setBaseline(form);
      const [healthRes, auditRes] = await Promise.all([getSettingsHealth(), getSettingsAudit(20)]);
      setHealth(healthRes);
      setAuditEntries(filterAuditEntriesForDisplay(auditRes.entries || []));
      setNotice("success", "All settings saved and applied.");
    } catch (error) {
      console.error(error);
      setNotice("error", error instanceof Error ? error.message : "Failed to save settings.");
    } finally {
      setSavingGlobal(false);
    }
  };

  const saveSection = async (section: SectionKey) => {
    setSectionSaving(section, true);
    setBanner(null);
    try {
      const actorEmail = localStorage.getItem("authEmail") || undefined;
      const guardIdentifier = localStorage.getItem("authPhone") || localStorage.getItem("authEmail") || "";
      if (section === "channels") {
        if (!guardIdentifier) {
          throw new Error("Guard identifier not found for WhatsApp preferences.");
        }
        await updateGuardPreferences(guardIdentifier, undefined, form.whatsappEnabled);
      }
      if (section === "policy") {
        await Promise.all([persistSystemSettings(form), persistUserSettings(form)]);
      }
      if (section === "language") {
        // Persist immediately in this browser profile for the current admin/guard identity.
        const locallyApplied = changeLanguage(form.language);
        const authToken = localStorage.getItem("authToken") || localStorage.getItem("token");
        if (!authToken) {
          setBaseline((prev) => ({ ...prev, language: locallyApplied }));
          setNotice("info", "Language saved locally for this account. Sign in again to sync with server.");
          setSectionSaving(section, false);
          return;
        }
        try {
          const updated = await updateMyLanguage(authToken, form.language);
          if (updated?.user_id) {
            localStorage.setItem("user_id", updated.user_id);
          }
          if (updated?.email) {
            localStorage.setItem("authEmail", updated.email);
          }
          if (updated?.role) {
            localStorage.setItem("authRole", String(updated.role));
          }
          const normalizedSaved = normalizeLanguage(updated?.preferred_language || form.language);
          changeLanguage(normalizedSaved);
          setForm((prev) => ({ ...prev, language: normalizedSaved }));
        } catch (error) {
          console.error("Language backend sync failed; keeping local preference", error);
          setNotice("info", "Language saved locally for this account. Backend sync failed; will retry next save.");
        }
      }
      if (section === "maintenance") {
        await updateMaintenanceSettings({
          retention_days: form.retentionDays,
          auto_archive: form.autoArchive,
        }, actorEmail);
      }

      setBaseline((prev) => ({
        ...prev,
        ...(section === "channels" ? {
          whatsappEnabled: form.whatsappEnabled,
        } : {}),
        ...(section === "policy" ? {
          detectionThreshold: form.detectionThreshold,
          cooldownSeconds: form.cooldownSeconds,
        } : {}),
        ...(section === "language" ? { language: form.language } : {}),
        ...(section === "maintenance" ? {
          retentionDays: form.retentionDays,
          autoArchive: form.autoArchive,
        } : {}),
      }));

      const [healthRes, auditRes] = await Promise.all([getSettingsHealth(), getSettingsAudit(20)]);
      setHealth(healthRes);
      setAuditEntries(filterAuditEntriesForDisplay(auditRes.entries || []));

      setNotice("success", "Section saved successfully.");
    } catch (error) {
      console.error(error);
      setNotice("error", error instanceof Error ? error.message : "Failed to save section settings.");
    } finally {
      setSectionSaving(section, false);
    }
  };

  const resetSection = (section: SectionKey) => {
    setForm((prev) => ({
      ...prev,
      ...(section === "channels" ? {
        whatsappEnabled: baseline.whatsappEnabled,
      } : {}),
      ...(section === "policy" ? {
        detectionThreshold: baseline.detectionThreshold,
        cooldownSeconds: baseline.cooldownSeconds,
      } : {}),
      ...(section === "language" ? { language: baseline.language } : {}),
      ...(section === "maintenance" ? {
        retentionDays: baseline.retentionDays,
        autoArchive: baseline.autoArchive,
      } : {}),
    }));

    if (section === "language") {
      changeLanguage(baseline.language);
    }
  };

  const discardAll = () => {
    setForm(baseline);
    changeLanguage(baseline.language);
    setNotice("info", "Unsaved changes were discarded.");
  };

  const runTestAction = async (channel: "whatsapp") => {
    setSimLoading(true);
    setBanner(null);
    try {
      await new Promise((resolve) => setTimeout(resolve, 650));
      setNotice("info", `Test ${channel} dispatch simulated. TODO: wire to backend test endpoint.`);
    } finally {
      setSimLoading(false);
    }
  };

  const applyPreset = (preset: "conservative" | "balanced" | "aggressive") => {
    if (preset === "conservative") {
      setForm((prev) => ({ ...prev, detectionThreshold: 94, cooldownSeconds: 300 }));
      return;
    }
    if (preset === "balanced") {
      setForm((prev) => ({ ...prev, detectionThreshold: 85, cooldownSeconds: 180 }));
      return;
    }
    setForm((prev) => ({ ...prev, detectionThreshold: 72, cooldownSeconds: 90 }));
  };

  const signOutFromSettings = async () => {
    const role = localStorage.getItem("authRole");
    const email = localStorage.getItem("authEmail");

    if (role === "admin" && email) {
      try {
        await adminLogout(email);
      } catch (error) {
        console.warn("[SETTINGS] Failed to update admin logout status", error);
      }
    }

    localStorage.removeItem("authToken");
    localStorage.removeItem("authRole");
    localStorage.removeItem("authEmail");
    localStorage.removeItem("authPhone");
    localStorage.removeItem("authName");
    localStorage.removeItem("token");
    localStorage.removeItem("user_id");
    navigate("/");
  };

  if (loading) {
    return (
      <div className="app-page flex h-screen">
        <Sidebar />
        <div className="flex-1 flex flex-col overflow-visible">
          <Header />
          <main className="flex-1 overflow-auto bg-gradient-to-b from-slate-50 to-white p-6">
            <div className="mx-auto max-w-5xl animate-pulse space-y-4">
              <div className="h-10 w-72 rounded-xl bg-slate-200" />
              <div className="h-52 rounded-3xl bg-slate-200" />
              <div className="h-52 rounded-3xl bg-slate-200" />
            </div>
          </main>
        </div>
      </div>
    );
  }

  const capturesUsage = toUsagePercent(stats.captures_storage_bytes, 20 * 1024 * 1024 * 1024);
  const mongoUsage = toUsagePercent(stats.mongodb_storage_bytes, 8 * 1024 * 1024 * 1024);
  const alertsUsage = toUsagePercent(stats.mongodb_alerts_storage_bytes, 5 * 1024 * 1024 * 1024);

  return (
    <div className="app-page flex h-screen">
      <Sidebar />

      <div className="flex-1 flex flex-col overflow-visible">
        <Header />

        <main className="flex-1 overflow-auto bg-gradient-to-b from-slate-50 to-white p-6 pb-20 text-slate-800">
          <div className="mx-auto grid w-full max-w-7xl grid-cols-1 gap-6 xl:grid-cols-[260px_1fr]">
            <aside className="h-fit rounded-3xl border border-slate-200 bg-white/80 p-4 shadow-lg backdrop-blur-md xl:sticky xl:top-5">
              <p className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Control Sections</p>
              <nav className="space-y-2">
                {[
                  { href: "#channels", label: t(language, "whatsappGuardAlerts") },
                  { href: "#policy", label: t(language, "aiPolicy") },
                  { href: "#language", label: t(language, "languageAndLocalization") },
                  { href: "#maintenance", label: t(language, "dataAndMaintenance") },
                ].map((item) => (
                  <a
                    key={item.href}
                    href={item.href}
                    className="flex items-center justify-between rounded-xl border border-transparent bg-slate-50 px-3 py-2 text-sm font-medium text-slate-700 transition-all duration-300 hover:border-slate-200 hover:bg-white"
                  >
                    <span>{item.label}</span>
                    <ChevronRight className="h-4 w-4 text-slate-400" />
                  </a>
                ))}
              </nav>

              <div className="mt-5 rounded-2xl bg-slate-900 p-4 text-slate-100">
                <p className="text-xs uppercase tracking-[0.18em] text-slate-300">{t(language, "sessionControl")}</p>
                <p className="mt-2 text-sm text-slate-200">{t(language, "sessionControlHint")}</p>
                <button
                  type="button"
                  onClick={signOutFromSettings}
                  className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-white px-3 py-2 text-sm font-semibold text-slate-900 transition-all duration-300 hover:bg-slate-100"
                >
                  <Power className="h-4 w-4" />
                  {t(language, "signOut")}
                </button>
              </div>
            </aside>

            <div className="space-y-6">
              <section className="rounded-3xl border border-slate-200 bg-white/80 p-6 shadow-xl backdrop-blur-md md:p-7">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-blue-600">{t(language, "securityConsole")}</p>
                    <h2 className="mt-2 text-3xl font-bold tracking-tight text-slate-900">{t(language, "settingsTitle")}</h2>
                    <p className="mt-2 max-w-3xl text-sm text-slate-600 md:text-base">
                      {t(language, "settingsOverview")}
                    </p>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`rounded-full px-3 py-1 text-xs font-semibold ring-1 ${health.waha_connected ? "bg-green-50 text-green-700 ring-green-200" : "bg-rose-50 text-rose-700 ring-rose-200"}`}>
                      {health.waha_connected ? "WAHA Connected" : "WAHA Unavailable"}
                    </span>
                    <span className={`rounded-full px-3 py-1 text-xs font-semibold ring-1 ${health.gemini_connected ? "bg-blue-50 text-blue-700 ring-blue-200" : "bg-rose-50 text-rose-700 ring-rose-200"}`}>
                      {health.gemini_connected ? "Gemini Ready" : "Gemini Missing"}
                    </span>
                    <span className={`rounded-full px-3 py-1 text-xs font-semibold ring-1 ${health.email_connected ? "bg-amber-50 text-amber-700 ring-amber-200" : "bg-rose-50 text-rose-700 ring-rose-200"}`}>
                      {health.email_connected ? "Email Service Active" : "Email Service Missing"}
                    </span>
                  </div>
                </div>

                <div className="mt-6 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                  <div className="flex items-center gap-2 text-sm">
                    {hasUnsaved ? (
                      <>
                        <XCircle className="h-4 w-4 text-amber-600" />
                        <span className="font-semibold text-amber-700">{t(language, "unsavedChangesDetected")}</span>
                      </>
                    ) : (
                      <>
                        <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                        <span className="font-semibold text-emerald-700">{t(language, "allSettingsSynced")}</span>
                      </>
                    )}
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={discardAll}
                      disabled={!hasUnsaved || savingGlobal}
                      className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition-all duration-300 hover:border-slate-400 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {t(language, "discardChanges")}
                    </button>
                    <button
                      type="button"
                      onClick={saveAll}
                      disabled={!hasUnsaved || savingGlobal}
                      className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition-all duration-300 hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <Save className="h-4 w-4" />
                      {savingGlobal ? t(language, "saving") : t(language, "saveAll")}
                    </button>
                  </div>
                </div>

                {banner && (
                  <div className={`mt-4 rounded-xl px-4 py-3 text-sm ${banner.tone === "success" ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200" : banner.tone === "error" ? "bg-rose-50 text-rose-700 ring-1 ring-rose-200" : "bg-blue-50 text-blue-700 ring-1 ring-blue-200"}`}>
                    {banner.message}
                  </div>
                )}
              </section>

              <SectionShell
                id="channels"
                language={language}
                icon={<Bell className="h-5 w-5" />}
                title={t(language, "whatsappGuardAlerts")}
                description={t(language, "whatsappGuardAlertsDesc")}
                dirty={dirtyMap.channels}
                saving={savingSection.channels}
                onSave={() => void saveSection("channels")}
                onReset={() => resetSection("channels")}
              >
                <div className="space-y-3">
                  <ToggleRow
                    icon={<MessageSquare className="h-5 w-5" />}
                    title="WhatsApp Delivery"
                    description="Dispatch approved alerts directly to guard phones using WAHA."
                    checked={form.whatsappEnabled}
                    onChange={(next) => setForm((prev) => ({ ...prev, whatsappEnabled: next }))}
                  />
                </div>

                <div className="mt-3 inline-flex items-center rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700 ring-1 ring-emerald-200">
                  WhatsApp Delivery Active
                </div>

                <div className="mt-4 rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-4">
                  <p className="text-sm font-semibold text-slate-800">Test Alert Actions</p>
                  <p className="text-xs text-slate-500">Guard phone sound is controlled by WhatsApp and device notification settings.</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => void runTestAction("whatsapp")}
                      disabled={simLoading}
                      className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition-all duration-300 hover:border-slate-400 disabled:opacity-50"
                    >
                      <MessageSquare className="h-4 w-4" />
                      Send Test WhatsApp
                    </button>
                  </div>
                </div>
              </SectionShell>

              <SectionShell
                id="policy"
                language={language}
                icon={<Gauge className="h-5 w-5" />}
                title={t(language, "aiPolicy")}
                description={t(language, "aiPolicyDesc")}
                dirty={dirtyMap.policy}
                saving={savingSection.policy}
                onSave={() => void saveSection("policy")}
                onReset={() => resetSection("policy")}
              >
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.1fr_0.9fr]">
                  <div className="rounded-2xl border border-slate-200 bg-white/70 p-4">
                    <div className="mb-3 flex items-center justify-between">
                      <label htmlFor="detection-threshold" className="text-sm font-semibold text-slate-800">Detection Threshold</label>
                      <span className="text-xl font-bold text-blue-700">{form.detectionThreshold}%</span>
                    </div>
                    <input
                      id="detection-threshold"
                      type="range"
                      min={50}
                      max={99}
                      value={form.detectionThreshold}
                      onChange={(e) => setForm((prev) => ({ ...prev, detectionThreshold: Number(e.target.value) }))}
                      className="h-2 w-full cursor-pointer appearance-none rounded-lg bg-slate-200 accent-blue-600"
                    />
                    <div className="mt-2 flex justify-between text-xs text-slate-500">
                      <span>50% (high sensitivity)</span>
                      <span>75%</span>
                      <span>99% (strict filtering)</span>
                    </div>

                    <div className="mt-4">
                      <label htmlFor="cooldown-seconds" className="text-sm font-semibold text-slate-800">Notification Cooldown (seconds)</label>
                      <input
                        id="cooldown-seconds"
                        type="number"
                        min={30}
                        max={900}
                        value={form.cooldownSeconds}
                        onChange={(e) => setForm((prev) => ({ ...prev, cooldownSeconds: Number(e.target.value || 180) }))}
                        className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 outline-none transition-all duration-300 focus:border-blue-400"
                      />
                    </div>
                  </div>

                  <div className="space-y-4">
                    <div className="rounded-2xl border border-blue-200 bg-blue-50 p-4">
                      <p className="text-sm font-semibold text-blue-800">Recommended</p>
                      <p className="mt-1 text-sm text-blue-700">
                        Balanced mode is recommended for mixed campus zones to control false alarms without missing threats.
                      </p>
                    </div>
                    <div className="rounded-2xl border border-slate-200 bg-white/70 p-4">
                      <p className="text-sm font-semibold text-slate-800">Sensitivity Presets</p>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {[
                          { key: "conservative", label: "Conservative" },
                          { key: "balanced", label: "Balanced" },
                          { key: "aggressive", label: "Aggressive" },
                        ].map((preset) => (
                          <button
                            key={preset.key}
                            type="button"
                            onClick={() => applyPreset(preset.key as "conservative" | "balanced" | "aggressive")}
                            className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition-all duration-300 hover:border-blue-400 hover:text-blue-700"
                          >
                            {preset.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              </SectionShell>

              <SectionShell
                id="language"
                language={language}
                icon={<Languages className="h-5 w-5" />}
                title={t(language, "languageAndLocalization")}
                description={t(language, "languageAndLocalizationDesc")}
                dirty={dirtyMap.language}
                saving={savingSection.language}
                onSave={() => void saveSection("language")}
                onReset={() => resetSection("language")}
              >
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_1fr]">
                  <div className="rounded-2xl border border-slate-200 bg-white/70 p-4">
                    <label htmlFor="app-language" className="text-sm font-semibold text-slate-800">Preferred Language</label>
                    <select
                      id="app-language"
                      value={form.language}
                      onChange={(e) => {
                        const next = normalizeLanguage(e.target.value) as "en" | "hi" | "mr";
                        setForm((prev) => ({ ...prev, language: next }));
                        changeLanguage(next);
                      }}
                      className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 outline-none transition-all duration-300 focus:border-blue-400"
                    >
                      {LANGUAGE_OPTIONS.map((option) => (
                        <option key={option.code} value={option.code}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                    <p className="mt-2 text-xs text-slate-500">
                      Current support includes English, Hindi, and Marathi. Architecture is ready to add more languages.
                    </p>
                  </div>

                  <div className="rounded-2xl border border-slate-200 bg-white/70 p-4">
                    <p className="text-sm font-semibold text-slate-800">Language Impact Scope</p>
                    <ul className="mt-2 space-y-2 text-sm text-slate-600">
                      <li className="flex items-start gap-2"><Globe className="mt-0.5 h-4 w-4 text-blue-600" /> Dashboard labels and key workflows</li>
                      <li className="flex items-start gap-2"><Bot className="mt-0.5 h-4 w-4 text-indigo-600" /> Assistant chat replies and prompts</li>
                      <li className="flex items-start gap-2"><Workflow className="mt-0.5 h-4 w-4 text-emerald-600" /> WhatsApp guard notifications and instructions</li>
                    </ul>
                  </div>
                </div>
              </SectionShell>

              <SectionShell
                id="maintenance"
                language={language}
                icon={<HardDrive className="h-5 w-5" />}
                title={t(language, "dataMaintenanceAudit")}
                description={t(language, "dataMaintenanceAuditDesc")}
                dirty={dirtyMap.maintenance}
                saving={savingSection.maintenance}
                onSave={() => void saveSection("maintenance")}
                onReset={() => resetSection("maintenance")}
              >
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_1fr]">
                  <div className="space-y-4 rounded-2xl border border-slate-200 bg-white/70 p-4">
                    <p className="text-sm font-semibold text-slate-800">Storage Usage</p>

                    {[
                      {
                        label: "Capture Images",
                        value: formatBytes(stats.captures_storage_bytes),
                        pct: capturesUsage,
                      },
                      {
                        label: "MongoDB Total",
                        value: formatBytes(stats.mongodb_storage_bytes),
                        pct: mongoUsage,
                      },
                      {
                        label: "Alert Records",
                        value: formatBytes(stats.mongodb_alerts_storage_bytes),
                        pct: alertsUsage,
                      },
                    ].map((row) => (
                      <div key={row.label}>
                        <div className="mb-1 flex items-center justify-between text-xs text-slate-600">
                          <span>{row.label}</span>
                          <span>{row.value}</span>
                        </div>
                        <div className="h-2 overflow-hidden rounded-full bg-slate-200">
                          <div className={`h-full rounded-full bg-blue-600 transition-all duration-300 ${usageWidthClass(row.pct)}`} />
                        </div>
                      </div>
                    ))}

                    <div className="grid grid-cols-1 gap-3 pt-2 sm:grid-cols-2">
                      <label className="text-sm font-semibold text-slate-800">
                        Retention (days)
                        <input
                          type="number"
                          min={7}
                          max={365}
                          value={form.retentionDays}
                          onChange={(e) => setForm((prev) => ({ ...prev, retentionDays: Number(e.target.value || 30) }))}
                          className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 outline-none transition-all duration-300 focus:border-blue-400"
                        />
                      </label>
                      <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
                        <div className="mb-2 flex items-center justify-between">
                          <p className="text-sm font-semibold text-slate-800">Auto Archive</p>
                          <label className="relative inline-flex cursor-pointer items-center">
                            <input
                              type="checkbox"
                              checked={form.autoArchive}
                              onChange={(e) => setForm((prev) => ({ ...prev, autoArchive: e.target.checked }))}
                              className="peer sr-only"
                              aria-label="Auto archive"
                            />
                            <span className="h-6 w-11 rounded-full bg-slate-200 transition-all duration-300 after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:bg-white after:transition-all after:duration-300 peer-checked:bg-blue-600 peer-checked:after:translate-x-full" />
                          </label>
                        </div>
                        <p className="text-xs text-slate-500">Keep recent evidence hot, archive older captures for forensics.</p>
                      </div>
                    </div>
                  </div>

                  <div className="space-y-4">
                    <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4">
                      <div className="flex items-start gap-2">
                        <ShieldAlert className="mt-0.5 h-5 w-5 text-rose-600" />
                        <div>
                          <p className="text-sm font-semibold text-rose-800">Danger Zone</p>
                          <p className="text-xs text-rose-700">These actions are high impact. Confirm before executing.</p>
                        </div>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => setConfirmAction("clear-footage")}
                          className="inline-flex items-center gap-2 rounded-xl border border-rose-300 bg-white px-3 py-2 text-sm font-semibold text-rose-700 transition-all duration-300 hover:border-rose-400"
                        >
                          <Trash2 className="h-4 w-4" />
                          Clear Old Footage
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmAction("reset-all")}
                          className="inline-flex items-center gap-2 rounded-xl border border-rose-300 bg-white px-3 py-2 text-sm font-semibold text-rose-700 transition-all duration-300 hover:border-rose-400"
                        >
                          <XCircle className="h-4 w-4" />
                          Reset Defaults
                        </button>
                      </div>
                    </div>

                    <div className="rounded-2xl border border-slate-200 bg-white/70 p-4">
                      <p className="text-sm font-semibold text-slate-800">Audit & Safety Timeline</p>
                      <div className="mt-3 space-y-3">
                        {auditEntries.length === 0 && (
                          <div className="rounded-xl border border-slate-200 bg-white p-3 text-xs text-slate-500">
                            No audit entries yet.
                          </div>
                        )}
                        {auditEntries.map((item) => (
                          <div key={item.id} className="rounded-xl border border-slate-200 bg-white p-3">
                            <p className="text-sm font-semibold text-slate-900">{item.field}</p>
                            <p className="text-xs text-slate-600">{String(item.old_value ?? "-")} {"->"} {String(item.new_value ?? "-")}</p>
                            <p className="mt-1 text-xs text-slate-500">{item.actor} • {formatAuditTime(item.timestamp)}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              </SectionShell>
            </div>
          </div>
        </main>
      </div>

      {confirmAction && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl">
            <h4 className="text-lg font-semibold text-slate-900">Confirm Action</h4>
            <p className="mt-2 text-sm text-slate-600">
              {confirmAction === "clear-footage"
                ? "This will remove older captured media according to retention policy."
                : "This resets settings to recommended defaults. Continue?"}
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmAction(null)}
                className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition-all duration-300 hover:border-slate-400"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={async () => {
                  if (confirmAction === "clear-footage") {
                    try {
                      const actorEmail = localStorage.getItem("authEmail") || undefined;
                      const res = await clearOldFootage(form.retentionDays, actorEmail);
                      setNotice("success", `Cleared ${res.deleted_files} files and freed ${formatBytes(res.freed_bytes)}.`);
                      const auditRes = await getSettingsAudit(20);
                      setAuditEntries(filterAuditEntriesForDisplay(auditRes.entries || []));
                    } catch (error) {
                      setNotice("error", error instanceof Error ? error.message : "Failed to clear old footage.");
                    }
                  }
                  if (confirmAction === "reset-all") {
                    try {
                      const actorEmail = localStorage.getItem("authEmail") || undefined;
                      const res = await resetDefaults(actorEmail);
                      setForm((prev) => ({
                        ...prev,
                        detectionThreshold: Number(res.system_settings?.detection_threshold ?? DEFAULT_FORM.detectionThreshold),
                        cooldownSeconds: Number(res.system_settings?.weapon_cooldown_seconds ?? DEFAULT_FORM.cooldownSeconds),
                        retentionDays: Number(res.maintenance_settings?.retention_days ?? DEFAULT_FORM.retentionDays),
                        autoArchive: Boolean(res.maintenance_settings?.auto_archive ?? DEFAULT_FORM.autoArchive),
                      }));
                      setBaseline((prev) => ({
                        ...prev,
                        detectionThreshold: Number(res.system_settings?.detection_threshold ?? DEFAULT_FORM.detectionThreshold),
                        cooldownSeconds: Number(res.system_settings?.weapon_cooldown_seconds ?? DEFAULT_FORM.cooldownSeconds),
                        retentionDays: Number(res.maintenance_settings?.retention_days ?? DEFAULT_FORM.retentionDays),
                        autoArchive: Boolean(res.maintenance_settings?.auto_archive ?? DEFAULT_FORM.autoArchive),
                      }));
                      setNotice("success", `Defaults restored. Deleted ${res.deleted_files} files and freed ${formatBytes(res.freed_bytes)}.`);
                      const auditRes = await getSettingsAudit(20);
                      setAuditEntries(filterAuditEntriesForDisplay(auditRes.entries || []));
                    } catch (error) {
                      setNotice("error", error instanceof Error ? error.message : "Failed to reset defaults.");
                    }
                  }
                  setConfirmAction(null);
                }}
                className="rounded-xl bg-rose-600 px-4 py-2 text-sm font-semibold text-white transition-all duration-300 hover:bg-rose-700"
              >
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
