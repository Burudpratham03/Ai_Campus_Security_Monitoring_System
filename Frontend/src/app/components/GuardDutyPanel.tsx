import { useState, useEffect } from "react";
import { Clock, LogIn, LogOut, AlertCircle } from "lucide-react";
import { APP_LANGUAGE_EVENT, getAppLanguage, normalizeLanguage, t } from "../utils/language";

interface GuardDutyInfo {
    status: "on_duty" | "off_duty";
    login_time?: string;
    duration_minutes?: number;
    duration_formatted?: string;
    alerts_handled?: number;
    message?: string;
}

interface GuardDutyStats {
    email: string;
    period_days: number;
    duty_stats: {
        total_shifts: number;
        total_hours: number;
        average_shift_hours: number;
    };
    alerts_in_period: {
        weapons: number;
        violence: number;
        fire: number;
        total: number;
    };
}

interface GuardDutyPanelProps {
    email?: string;
    onStatusChange?: (status: GuardDutyInfo) => void;
}

export function GuardDutyPanel({ email, onStatusChange }: GuardDutyPanelProps) {
    const [language, setLanguage] = useState(getAppLanguage());
    const [dutyStatus, setDutyStatus] = useState<GuardDutyInfo | null>(null);
    const [stats, setStats] = useState<GuardDutyStats | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (email) {
            loadDutyStatus();
            loadStatistics();
            const interval = setInterval(() => {
                loadDutyStatus();
            }, 30000); // Refresh every 30 seconds
            return () => clearInterval(interval);
        }
    }, [email]);

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

    const loadDutyStatus = async () => {
        if (!email) return;
        try {
            const res = await fetch(
                `http://127.0.0.1:8000/guard-duty/current-status/${email}`
            );
            const data = await res.json();
            setDutyStatus(data);
            onStatusChange?.(data);
        } catch (err) {
            console.error("Failed to load duty status:", err);
        }
    };

    const loadStatistics = async () => {
        if (!email) return;
        try {
            const res = await fetch(
                `http://127.0.0.1:8000/guard-duty/statistics/${email}?days=7`
            );
            const data = await res.json();
            setStats(data);
        } catch (err) {
            console.error("Failed to load statistics:", err);
        }
    };

    const handleLogin = async () => {
        if (!email) {
            setError(t(language, "emailRequired"));
            return;
        }
        setIsLoading(true);
        try {
            const res = await fetch("http://127.0.0.1:8000/guard-duty/login", {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body: `email=${encodeURIComponent(email)}`,
            });
            const data = await res.json();
            if (data.status === "logged_in" || data.status === "already_on_duty") {
                await loadDutyStatus();
                setError(null);
            }
        } catch (err) {
            setError(t(language, "loginFailed"));
            console.error(err);
        } finally {
            setIsLoading(false);
        }
    };

    const handleLogout = async () => {
        if (!email) return;
        setIsLoading(true);
        try {
            const res = await fetch("http://127.0.0.1:8000/guard-duty/logout", {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body: `email=${encodeURIComponent(email)}`,
            });
            const data = await res.json();
            if (data.status === "logged_out") {
                await loadDutyStatus();
                await loadStatistics();
                setError(null);
            }
        } catch (err) {
            setError(t(language, "logoutFailed"));
            console.error(err);
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="app-surface rounded-xl p-6">
            <div className="mb-6">
                <h3 className="mb-1 text-lg font-semibold text-foreground">{t(language, "adminGuardManagement")}</h3>
                <p className="mb-4 text-xs text-muted-foreground">{t(language, "adminGuardManagementHint")}</p>

                {/* Error Message */}
                {error && (
                    <div className="mb-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3">
                        <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
                        <span className="text-sm text-red-700">{error}</span>
                    </div>
                )}

                {/* Current Status */}
                {dutyStatus && (
                    <div
                        className={`mb-4 p-4 rounded-lg border-2 ${dutyStatus.status === "on_duty"
                            ? "bg-green-50 border-green-200"
                            : "bg-gray-50 border-gray-200"
                            }`}
                    >
                        <div className="flex items-center gap-2 mb-2">
                            <Clock className={`w-5 h-5 ${dutyStatus.status === "on_duty" ? "text-green-600" : "text-gray-600"
                                }`} />
                            <span className="font-semibold text-foreground">
                                {dutyStatus.status === "on_duty" ? t(language, "onDuty") : t(language, "offDuty")}
                            </span>
                        </div>
                        {dutyStatus.status === "on_duty" && (
                            <>
                                <p className="mb-1 text-sm text-slate-700">
                                    {t(language, "duration")}: <span className="font-semibold">{dutyStatus.duration_formatted}</span>
                                </p>
                                <p className="text-sm text-slate-700">
                                    {t(language, "threatsHandled")}: <span className="font-semibold">{dutyStatus.alerts_handled}</span>
                                </p>
                            </>
                        )}
                    </div>
                )}

                {/* Duty Controls: Toggle On/Off duty (primary) + View Live Alerts (secondary) */}
                <div className="flex gap-3 mb-6">
                    <button
                        onClick={async () => {
                            if (dutyStatus?.status === "on_duty") {
                                await handleLogout();
                            } else {
                                await handleLogin();
                            }
                        }}
                        disabled={isLoading}
                        className={`flex-1 flex items-center justify-center gap-2 py-2 px-4 rounded-lg font-medium transition ${dutyStatus?.status === "on_duty"
                            ? "app-btn-danger"
                            : "app-btn-primary"
                            }`}
                    >
                        {dutyStatus?.status === "on_duty" ? (
                            <LogOut className="w-4 h-4" />
                        ) : (
                            <LogIn className="w-4 h-4" />
                        )}
                        {dutyStatus?.status === "on_duty" ? t(language, "goOffDuty") : t(language, "goOnDuty")}
                    </button>

                    <button
                        onClick={() => document.getElementById("live-alerts")?.scrollIntoView({ behavior: "smooth" })}
                        className="app-btn-secondary flex-1 items-center justify-center gap-2 py-2 px-4"
                    >
                        <AlertCircle className="w-4 h-4" />
                        {t(language, "viewLiveAlerts")}
                    </button>
                </div>
            </div>

            {/* Statistics (hidden for now) */}
            {false && stats && (
                <div className="border-t border-gray-200 pt-6">
                    <h4 className="font-semibold text-gray-900 text-sm mb-4">
                        Last 7 Days Statistics
                    </h4>
                    <div className="grid grid-cols-2 gap-4 mb-4">
                        <div className="bg-blue-50 rounded-lg p-3">
                            <p className="text-xs text-gray-600 mb-1">Total Shifts</p>
                            <p className="text-2xl font-bold text-blue-600">
                                {stats.duty_stats.total_shifts}
                            </p>
                        </div>
                        <div className="bg-purple-50 rounded-lg p-3">
                            <p className="text-xs text-gray-600 mb-1">Total Hours</p>
                            <p className="text-2xl font-bold text-purple-600">
                                {stats.duty_stats.total_hours.toFixed(1)}h
                            </p>
                        </div>
                    </div>

                    {/* Threats Summary */}
                    <div className="space-y-2">
                        <p className="text-xs font-semibold text-gray-600 uppercase">Threats Detected</p>
                        <div className="flex gap-2">
                            {stats.alerts_in_period.weapons > 0 && (
                                <div className="bg-red-100 rounded px-2 py-1">
                                    <p className="text-xs text-red-700">
                                        <span className="font-bold">{stats.alerts_in_period.weapons}</span> Weapons
                                    </p>
                                </div>
                            )}
                            {stats.alerts_in_period.violence > 0 && (
                                <div className="bg-orange-100 rounded px-2 py-1">
                                    <p className="text-xs text-orange-700">
                                        <span className="font-bold">{stats.alerts_in_period.violence}</span> Violence
                                    </p>
                                </div>
                            )}
                            {stats.alerts_in_period.fire > 0 && (
                                <div className="bg-yellow-100 rounded px-2 py-1">
                                    <p className="text-xs text-yellow-700">
                                        <span className="font-bold">{stats.alerts_in_period.fire}</span> Fire
                                    </p>
                                </div>
                            )}
                            {stats.alerts_in_period.total === 0 && (
                                <p className="text-xs text-gray-600">{t(language, "noThreatsDetected")}</p>
                            )}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
