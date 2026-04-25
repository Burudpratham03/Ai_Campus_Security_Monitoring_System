import { BellRing, Clock3, MapPin, ShieldCheck, RefreshCw, Languages } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { playAlertSound } from "../../utils/soundNotification";

import {
    fetchVerifiedAlerts,
    getGuardPreferences,
    getGuardStatusByPhone,
    goOffDutyByPhone,
    goOnDutyByPhone,
    type AlertDto,
    updateMyLanguage,
    updateGuardPreferences,
} from "../api/client";
import {
    APP_LANGUAGE_EVENT,
    LANGUAGE_OPTIONS,
    getAppLanguage,
    normalizeLanguage,
    setAppLanguage,
    statusLabel,
    t,
    tf,
    typeLabel,
} from "../utils/language";

function formatTime(value: string): string {
    return new Date(value).toLocaleString();
}

export function GuardStatus() {
    const navigate = useNavigate();
    const guardName = localStorage.getItem("authName") || "Security Personnel";
    const guardPhone = localStorage.getItem("authPhone") || "";
    const [alerts, setAlerts] = useState<AlertDto[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [lastUpdated, setLastUpdated] = useState<string | null>(null);
    const [dutyStatus, setDutyStatus] = useState<"on_duty" | "off_duty">("off_duty");
    const [dutyLoading, setDutyLoading] = useState(false);
    const [language, setLanguage] = useState(getAppLanguage());
    const [languageSaving, setLanguageSaving] = useState(false);
    const [languageNotice, setLanguageNotice] = useState<string | null>(null);
    const knownAlertIdsRef = useRef<Set<string>>(new Set());
    const hasAlertBaselineRef = useRef(false);

    const confirmedAlerts = useMemo(
        () => alerts.filter((alert) => alert.status === "confirmed"),
        [alerts],
    );

    useEffect(() => {
        const token = localStorage.getItem("authToken");
        const role = localStorage.getItem("authRole");

        if (!token) {
            navigate("/", { replace: true });
            return;
        }
        if (role !== "guard") {
            navigate(role === "admin" ? "/dashboard" : "/", { replace: true });
        }
    }, [navigate]);

    const isOnDuty = dutyStatus === "on_duty";

    useEffect(() => {
        let cancelled = false;

        const syncDutyStatus = async () => {
            if (!guardPhone) {
                return;
            }

            try {
                const current = await getGuardStatusByPhone(guardPhone);
                if (cancelled) {
                    return;
                }

                const nextStatus: "on_duty" | "off_duty" = current?.status === "on_duty" ? "on_duty" : "off_duty";
                setDutyStatus(nextStatus);

                if (nextStatus === "off_duty") {
                    setAlerts([]);
                    setLastUpdated(null);
                    knownAlertIdsRef.current.clear();
                    hasAlertBaselineRef.current = false;
                }
            } catch {
                if (!cancelled) {
                    setDutyStatus("off_duty");
                }
            }
        };

        void syncDutyStatus();
        return () => {
            cancelled = true;
        };
    }, [guardPhone]);

    const loadConfirmedAlerts = async () => {
        if (!isOnDuty) {
            return;
        }
        setLoading(true);
        setError(null);
        try {
            const data = await fetchVerifiedAlerts(100, guardPhone || undefined);
            const confirmed = data.filter((alert) => alert.status === "confirmed");
            const newConfirmed = confirmed.filter((alert) => !knownAlertIdsRef.current.has(alert.id));

            if (hasAlertBaselineRef.current && newConfirmed.length > 0) {
                const firstNewType = newConfirmed[0].subtype || newConfirmed[0].type || "alert";
                playAlertSound(firstNewType);
            }

            knownAlertIdsRef.current = new Set(confirmed.map((alert) => alert.id));
            if (!hasAlertBaselineRef.current) {
                hasAlertBaselineRef.current = true;
            }

            setAlerts(data);
            setLastUpdated(new Date().toLocaleTimeString());
        } catch (err) {
            setError(err instanceof Error ? err.message : t(language, "fetchNotificationsFailed"));
        } finally {
            setLoading(false);
        }
    };

    const goOnDuty = async () => {
        if (!guardPhone) {
            setError(t(language, "missingGuardPhone"));
            return;
        }
        setDutyLoading(true);
        setError(null);
        try {
            const response = await goOnDutyByPhone(guardPhone);
            if (response?.status === "logged_in" || response?.status === "already_on_duty") {
                setDutyStatus("on_duty");
            }
        } catch (err) {
            setError(err instanceof Error ? err.message : t(language, "switchOnDutyGuardFailed"));
        } finally {
            setDutyLoading(false);
        }
    };

    const goOffDuty = async () => {
        if (!guardPhone) {
            setError(t(language, "missingGuardPhone"));
            return;
        }
        setDutyLoading(true);
        setError(null);
        try {
            const response = await goOffDutyByPhone(guardPhone);
            if (response?.status === "logged_out" || response?.status === "not_on_duty") {
                setDutyStatus("off_duty");
                setAlerts([]);
                setLastUpdated(null);
                knownAlertIdsRef.current.clear();
                hasAlertBaselineRef.current = false;
            }
        } catch (err) {
            setError(err instanceof Error ? err.message : t(language, "switchOffDutyGuardFailed"));
        } finally {
            setDutyLoading(false);
        }
    };

    useEffect(() => {
        if (!isOnDuty) {
            return;
        }

        let cancelled = false;
        const pollAlerts = async () => {
            if (!cancelled) {
                await loadConfirmedAlerts();
            }
        };

        void pollAlerts();
        const interval = setInterval(pollAlerts, 8000);
        return () => {
            cancelled = true;
            clearInterval(interval);
        };
    }, [isOnDuty, guardPhone]);

    useEffect(() => {
        let cancelled = false;

        const loadGuardPreferences = async () => {
            if (!guardPhone) {
                return;
            }
            try {
                const data = await getGuardPreferences(guardPhone);
                if (cancelled) {
                    return;
                }
                const nextLanguage = normalizeLanguage(data?.preferred_language);
                setLanguage(nextLanguage);
                setAppLanguage(nextLanguage);
            } catch (err) {
                if (!cancelled) {
                    setLanguage(getAppLanguage());
                }
            }
        };

        void loadGuardPreferences();

        return () => {
            cancelled = true;
        };
    }, [guardPhone]);

    useEffect(() => {
        const onLanguageChanged = (event: Event) => {
            const custom = event as CustomEvent<{ language?: string }>;
            if (custom.detail?.language) {
                setLanguage(normalizeLanguage(custom.detail.language));
                return;
            }
            setLanguage(getAppLanguage());
        };
        window.addEventListener(APP_LANGUAGE_EVENT, onLanguageChanged as EventListener);
        return () => window.removeEventListener(APP_LANGUAGE_EVENT, onLanguageChanged as EventListener);
    }, []);

    const saveLanguage = async () => {
        const authToken = localStorage.getItem("authToken") || localStorage.getItem("token");
        if (!authToken) {
            setLanguageNotice("Missing auth token. Please sign in again.");
            return;
        }

        const normalized = normalizeLanguage(language);
        setLanguageSaving(true);
        setLanguageNotice(null);
        try {
            const response = await updateMyLanguage(authToken, normalized);
            if (response.user_id) {
                localStorage.setItem("user_id", response.user_id);
            }
            if (response.email) {
                localStorage.setItem("authEmail", response.email);
            }
            const savedLanguage = normalizeLanguage(response.preferred_language);
            setLanguage(savedLanguage);
            setAppLanguage(savedLanguage);
            setLanguageNotice(t(language, "languageSavedGuard"));
        } catch (err) {
            setLanguageNotice(
                err instanceof Error
                    ? err.message
                    : t(language, "settingsSaveFailed")
            );
        } finally {
            setLanguageSaving(false);
        }
    };

    return (
        <div className="app-page px-4 py-8 text-foreground sm:px-6">
            <div className="mx-auto w-full max-w-4xl app-auth-card p-6 sm:p-8">
                <div className="flex flex-wrap items-center justify-between gap-4">
                    <div>
                        <div className="inline-flex items-center gap-2 rounded-full border border-emerald-400/30 bg-emerald-500/10 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-emerald-700">
                            <BellRing className="h-3.5 w-3.5" />
                            {t(language, "guardNotifications")}
                        </div>
                        <h1 className="mt-3 text-2xl font-bold text-foreground sm:text-3xl">{t(language, "confirmedThreatFeed")}</h1>
                        <p className="mt-2 text-sm text-muted-foreground sm:text-base">
                            {tf(language, "guardIntro", { name: guardName })}
                        </p>
                        {lastUpdated && (
                            <p className="mt-2 text-xs text-muted-foreground">{tf(language, "lastUpdated", { time: lastUpdated })}</p>
                        )}
                    </div>

                    <button
                        type="button"
                        onClick={loadConfirmedAlerts}
                        disabled={loading || !isOnDuty}
                        className="app-btn-secondary inline-flex items-center gap-2 px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
                        {t(language, "refresh")}
                    </button>
                </div>

                <div className="mt-4 flex flex-wrap items-center gap-3">
                    <span className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide ${dutyStatus === "on_duty"
                        ? "border border-emerald-400/40 bg-emerald-500/10 text-emerald-700"
                        : "border border-border bg-muted text-muted-foreground"
                        }`}>
                        {dutyStatus === "on_duty" ? t(language, "onDuty") : t(language, "offDuty")}
                    </span>

                    <button
                        type="button"
                        onClick={goOnDuty}
                        disabled={dutyLoading || dutyStatus === "on_duty"}
                        className="app-btn-primary rounded-xl px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {dutyLoading && dutyStatus !== "on_duty" ? t(language, "switching") : t(language, "onDuty")}
                    </button>

                    <button
                        type="button"
                        onClick={goOffDuty}
                        disabled={dutyLoading || dutyStatus === "off_duty"}
                        className="app-btn-secondary rounded-xl px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {dutyLoading && dutyStatus !== "off_duty" ? t(language, "switching") : t(language, "offDuty")}
                    </button>
                </div>

                <div className="mt-5 rounded-2xl border border-border bg-card/70 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                            <p className="inline-flex items-center gap-2 text-sm font-semibold text-foreground">
                                <Languages className="h-4 w-4 text-emerald-600" />
                                {t(language, "whatsappLanguage")}
                            </p>
                            <p className="mt-1 text-xs text-muted-foreground">
                                {t(language, "whatsappLanguageHint")}
                            </p>
                        </div>

                        <div className="flex items-center gap-2">
                            <select
                                value={language}
                                onChange={(e) => setLanguage(normalizeLanguage(e.target.value))}
                                className="app-input min-w-[150px] px-3 py-2 text-sm"
                                aria-label={t(language, "whatsappLanguage")}
                            >
                                {LANGUAGE_OPTIONS.map((option) => (
                                    <option key={option.code} value={option.code}>
                                        {option.label}
                                    </option>
                                ))}
                            </select>
                            <button
                                type="button"
                                onClick={saveLanguage}
                                disabled={languageSaving}
                                className="app-btn-primary rounded-xl px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                            >
                                {languageSaving ? t(language, "saving") : t(language, "save")}
                            </button>
                        </div>
                    </div>

                    {languageNotice && (
                        <p className="mt-3 text-xs text-muted-foreground">{languageNotice}</p>
                    )}
                </div>

                {error && (
                    <div className="mt-5 rounded-xl border border-red-400/40 bg-red-500/10 px-4 py-3 text-sm text-red-700">
                        {error}
                    </div>
                )}

                <div className="mt-6 space-y-3">
                    {confirmedAlerts.length === 0 && !loading && (
                        <div className="app-panel px-5 py-6 text-center text-muted-foreground">
                            <ShieldCheck className="mx-auto mb-3 h-8 w-8 text-emerald-600" />
                            {t(language, "noConfirmedThreats")}
                        </div>
                    )}

                    {confirmedAlerts.map((alert) => (
                        <div key={alert.id} className="rounded-2xl border border-emerald-400/30 bg-card/90 px-5 py-4 shadow-sm">
                            <div className="flex flex-wrap items-start justify-between gap-2">
                                <p className="text-base font-semibold text-foreground">
                                    {typeLabel(language, alert.subtype || alert.type)} {t(language, "confirmed").toLowerCase()}
                                </p>
                                <span className="rounded-full border border-emerald-400/40 bg-emerald-500/10 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-emerald-700">
                                    {statusLabel(language, "confirmed")}
                                </span>
                            </div>

                            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-sm text-muted-foreground">
                                <span className="inline-flex items-center gap-2">
                                    <MapPin className="h-4 w-4 text-emerald-600" />
                                    {alert.location || t(language, "dashboardFeed")}
                                </span>
                                <span className="inline-flex items-center gap-2">
                                    <Clock3 className="h-4 w-4 text-emerald-600" />
                                    {formatTime(alert.timestamp)}
                                </span>
                            </div>
                        </div>
                    ))}
                </div>

                <div className="mt-8 flex flex-wrap gap-3">
                    <button
                        type="button"
                        onClick={() => navigate("/")}
                        className="app-btn-secondary rounded-xl px-4 py-2 text-sm font-semibold"
                    >
                        {t(language, "backToHome")}
                    </button>
                </div>
            </div>
        </div>
    );
}
