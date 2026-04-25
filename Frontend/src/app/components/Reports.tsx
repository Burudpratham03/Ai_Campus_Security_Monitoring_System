import { Sidebar } from "./Sidebar";
import { Header } from "./Header";
import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Clock3,
  FolderCheck,
  FolderX,
  Shield,
  TrendingUp,
  Users,
} from "lucide-react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  AdminActivityDto,
  AlertDto,
  buildGuardActivityExcelExportUrl,
  fetchAdminActivity,
  fetchAlertTrends,
  fetchAnalyticsSummary,
  fetchDutyLogs,
  fetchFalseAlarmAnalytics,
  fetchFalseAlarms,
  fetchVerifiedAlerts,
  type AlertTrendDto,
  type AnalyticsSummaryDto,
  type DutyLogDto,
  type FalseAlarmAnalyticsDto,
} from "../api/client";
import { t, typeLabel } from "../utils/language";
import { useLanguage } from "../context/LanguageContext";

const API_BASE = "http://127.0.0.1:8000";

type RangeKey = "7d" | "30d" | "90d";
type ModelKey = "weapon" | "violence" | "fire" | "anomaly";

const MODEL_ORDER: ModelKey[] = ["weapon", "violence", "fire", "anomaly"];

const MODEL_COLORS: Record<ModelKey, string> = {
  weapon: "#ef4444",
  violence: "#0ea5e9",
  fire: "#f97316",
  anomaly: "#a855f7",
};

const MODEL_DOT_CLASS: Record<ModelKey, string> = {
  weapon: "bg-red-500",
  violence: "bg-sky-500",
  fire: "bg-orange-500",
  anomaly: "bg-violet-500",
};

function toIsoDate(daysAgo: number): string {
  const d = new Date();
  d.setDate(d.getDate() - daysAgo);
  return d.toISOString();
}

function formatPct(value: number): string {
  return `${value.toFixed(1)}%`;
}

function formatSeconds(value: number): string {
  if (value < 60) return `${value.toFixed(0)}s`;
  return `${(value / 60).toFixed(1)}m`;
}

function buildFileUrl(path?: string | null): string | null {
  if (!path) return null;
  return `${API_BASE}/file/${encodeURIComponent(path).replace(/%2F/g, "/")}`;
}

export function Reports() {
  const { currentLanguage: language } = useLanguage();
  const [range, setRange] = useState<RangeKey>("30d");
  const [trendGranularity, setTrendGranularity] = useState<"hourly" | "daily" | "weekly">("daily");
  const [guardExportDays, setGuardExportDays] = useState<3 | 7>(7);

  const [summary, setSummary] = useState<AnalyticsSummaryDto | null>(null);
  const [falseAnalytics, setFalseAnalytics] = useState<FalseAlarmAnalyticsDto | null>(null);
  const [adminActivity, setAdminActivity] = useState<AdminActivityDto | null>(null);
  const [dutyLogs, setDutyLogs] = useState<DutyLogDto[]>([]);
  const [trend, setTrend] = useState<AlertTrendDto | null>(null);
  const [verifiedEvidence, setVerifiedEvidence] = useState<AlertDto[]>([]);
  const [falseEvidence, setFalseEvidence] = useState<AlertDto[]>([]);

  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const dateFrom = useMemo(() => {
    if (range === "7d") return toIsoDate(7);
    if (range === "90d") return toIsoDate(90);
    return toIsoDate(30);
  }, [range]);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        setLoading(true);
        const [summaryRes, falseRes, adminRes, trendRes, verifiedRes, falseListRes, dutyLogsRes] = await Promise.all([
          fetchAnalyticsSummary(dateFrom),
          fetchFalseAlarmAnalytics(20, dateFrom),
          fetchAdminActivity(200),
          fetchAlertTrends(trendGranularity, dateFrom),
          fetchVerifiedAlerts(12),
          fetchFalseAlarms(12),
          fetchDutyLogs(200),
        ]);

        if (cancelled) return;
        setSummary(summaryRes);
        setFalseAnalytics(falseRes);
        setAdminActivity(adminRes);
        setTrend(trendRes);
        setVerifiedEvidence(
          (verifiedRes || []).filter((item) => {
            if (!item.multi_angle_verified) return false;
            const evidence = (item.evidence_urls || []).filter((path) => Boolean(path));
            return evidence.length > 0 || Boolean(item.frame_path);
          })
        );
        setFalseEvidence((falseListRes || []).filter((item) => Boolean(item.frame_path)));
        setDutyLogs(dutyLogsRes);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : "Failed to load report analytics";
        setError(msg);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    const interval = setInterval(load, 15000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [dateFrom, trendGranularity]);

  const topTrendRows = (trend?.data || []).slice(-8);
  const byTypeLineData = useMemo(() => {
    const byType = summary?.by_type || {};
    const readCount = (model: ModelKey, key: "verified" | "false_alarm" | "pending") =>
      Number(byType[model]?.[key] || 0);

    return [
      {
        status: "Verified",
        weapon: readCount("weapon", "verified"),
        violence: readCount("violence", "verified"),
        fire: readCount("fire", "verified"),
        anomaly: readCount("anomaly", "verified"),
      },
      {
        status: "False Alarm",
        weapon: readCount("weapon", "false_alarm"),
        violence: readCount("violence", "false_alarm"),
        fire: readCount("fire", "false_alarm"),
        anomaly: readCount("anomaly", "false_alarm"),
      },
      {
        status: "Pending",
        weapon: readCount("weapon", "pending"),
        violence: readCount("violence", "pending"),
        fire: readCount("fire", "pending"),
        anomaly: readCount("anomaly", "pending"),
      },
    ];
  }, [summary]);

  const modelSummaryRows = useMemo(() => {
    const byType = summary?.by_type || {};
    return MODEL_ORDER.map((model) => {
      const stats = byType[model] || {
        total: 0,
        verified: 0,
        confirmed: 0,
        false_alarm: 0,
        pending: 0,
      };
      return {
        model,
        label: typeLabel(language, model),
        total: Number(stats.total || 0),
        verified: Number(stats.verified || 0),
        falseAlarm: Number(stats.false_alarm || 0),
        pending: Number(stats.pending || 0),
      };
    });
  }, [language, summary]);

  const hasByTypeData = modelSummaryRows.some((row) => row.total > 0);
  const guardExportUrl = useMemo(
    () => buildGuardActivityExcelExportUrl(guardExportDays),
    [guardExportDays]
  );

  return (
    <div className="app-page flex h-screen">
      <Sidebar />

      <div className="flex-1 flex flex-col overflow-visible">
        <Header />

        <main className="flex-1 overflow-auto p-6 pb-20">
          <section className="mb-6 rounded-2xl bg-gradient-to-r from-slate-900 via-blue-900 to-cyan-800 p-6 text-white shadow-lg app-animate-enter">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <h2 className="text-2xl font-semibold">{t(language, "reportsTitle")}</h2>
                <p className="mt-1 text-sm text-blue-100">
                  {t(language, "reportsSubtitle")}
                </p>
              </div>

              <div className="flex items-center gap-2 rounded-xl bg-white/10 p-1 backdrop-blur">
                <button onClick={() => setRange("7d")} className={`rounded-lg px-3 py-1.5 text-sm ${range === "7d" ? "bg-white text-slate-900" : "text-white"}`}>7D</button>
                <button onClick={() => setRange("30d")} className={`rounded-lg px-3 py-1.5 text-sm ${range === "30d" ? "bg-white text-slate-900" : "text-white"}`}>30D</button>
                <button onClick={() => setRange("90d")} className={`rounded-lg px-3 py-1.5 text-sm ${range === "90d" ? "bg-white text-slate-900" : "text-white"}`}>90D</button>
              </div>
            </div>
          </section>

          {error && (
            <div className="mb-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              {error}
            </div>
          )}

          <section className="mb-6 grid gap-4 md:grid-cols-2 xl:grid-cols-5">
            <article className="app-surface p-4">
              <div className="flex items-center gap-2 text-slate-500"><Shield className="h-4 w-4" /><span className="text-xs uppercase">{t(language, "totalAlerts")}</span></div>
              <p className="mt-2 text-3xl font-semibold text-slate-900">{summary?.overall.total_alerts ?? 0}</p>
            </article>

            <article className="app-surface p-4">
              <div className="flex items-center gap-2 text-red-600"><AlertTriangle className="h-4 w-4" /><span className="text-xs uppercase">{t(language, "twoAngleVerifiedThreats")}</span></div>
              <p className="mt-2 text-3xl font-semibold text-slate-900">{summary?.overall.two_angle_verified_count ?? 0}</p>
            </article>

            <article className="app-surface p-4">
              <div className="flex items-center gap-2 text-emerald-600"><FolderCheck className="h-4 w-4" /><span className="text-xs uppercase">{t(language, "verifiedRate")}</span></div>
              <p className="mt-2 text-3xl font-semibold text-slate-900">{formatPct(summary?.overall.verified_rate ?? 0)}</p>
            </article>

            <article className="app-surface p-4">
              <div className="flex items-center gap-2 text-amber-600"><FolderX className="h-4 w-4" /><span className="text-xs uppercase">{t(language, "falseAlarmRate")}</span></div>
              <p className="mt-2 text-3xl font-semibold text-slate-900">{formatPct(summary?.overall.false_alarm_rate ?? 0)}</p>
            </article>

            <article className="app-surface p-4">
              <div className="flex items-center gap-2 text-indigo-600"><Clock3 className="h-4 w-4" /><span className="text-xs uppercase">{t(language, "avgResponse")}</span></div>
              <p className="mt-2 text-3xl font-semibold text-slate-900">{formatSeconds(summary?.response_metrics.avg_response_seconds ?? 0)}</p>
            </article>
          </section>

          <section className="mb-6 grid gap-6 xl:grid-cols-3">
            <article className="app-surface p-5 xl:col-span-1">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-600">{t(language, "verifiedVsFalseByType")}</h3>
              {!hasByTypeData && <p className="mt-4 text-sm text-slate-500">{t(language, "noTypeAnalytics")}</p>}

              {hasByTypeData && (
                <>
                  <div className="mt-4 h-64 rounded-xl border border-border bg-card/70 p-2">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={byTypeLineData}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="status" tickLine={false} axisLine={false} />
                        <YAxis allowDecimals={false} tickLine={false} axisLine={false} />
                        <RechartsTooltip
                          formatter={(value: number | string, name: string) => [Number(value).toLocaleString(), name]}
                          labelFormatter={(label) => `Status: ${label}`}
                        />
                        <Legend />
                        {MODEL_ORDER.map((model) => (
                          <Line
                            key={model}
                            type="monotone"
                            dataKey={model}
                            name={typeLabel(language, model)}
                            stroke={MODEL_COLORS[model]}
                            strokeWidth={3}
                            dot={{ r: 4 }}
                            activeDot={{ r: 6 }}
                          />
                        ))}
                      </LineChart>
                    </ResponsiveContainer>
                  </div>

                  <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
                    {modelSummaryRows.map((row) => (
                      <div key={row.model} className="rounded-lg border border-border bg-card/70 px-3 py-2 text-xs text-slate-700">
                        <div className="mb-1 flex items-center justify-between">
                          <span className="flex items-center gap-2 font-semibold uppercase text-slate-800">
                            <span className={`h-2.5 w-2.5 rounded-full ${MODEL_DOT_CLASS[row.model]}`} />
                            {row.label}
                          </span>
                          <span className="text-slate-500">Total {row.total}</span>
                        </div>
                        <div className="flex items-center justify-between text-[11px]">
                          <span>Verified {row.verified}</span>
                          <span>False {row.falseAlarm}</span>
                          <span>Pending {row.pending}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </article>

            <article className="app-surface p-5 xl:col-span-1">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-600">{t(language, "falseAlarmQuality")}</h3>
              <div className="mt-4 grid grid-cols-3 gap-3 text-center">
                <div className="rounded-lg bg-slate-50 p-3">
                  <p className="text-xs text-slate-500">{t(language, "low")}</p>
                  <p className="text-xl font-semibold text-slate-900">{falseAnalytics?.by_confidence_range.low_lt_0_50 ?? 0}</p>
                </div>
                <div className="rounded-lg bg-slate-50 p-3">
                  <p className="text-xs text-slate-500">{t(language, "medium")}</p>
                  <p className="text-xl font-semibold text-slate-900">{falseAnalytics?.by_confidence_range.medium_0_50_to_0_80 ?? 0}</p>
                </div>
                <div className="rounded-lg bg-slate-50 p-3">
                  <p className="text-xs text-slate-500">{t(language, "high")}</p>
                  <p className="text-xl font-semibold text-slate-900">{falseAnalytics?.by_confidence_range.high_gt_0_80 ?? 0}</p>
                </div>
              </div>

              <div className="mt-4">
                <p className="text-xs uppercase tracking-wide text-slate-500">{t(language, "topFalseAlarmGuards")}</p>
                <div className="mt-2 space-y-2">
                  {(falseAnalytics?.by_guard || []).slice(0, 5).map((row) => (
                    <div key={row.email} className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm">
                      <span className="truncate text-slate-700">{row.email}</span>
                      <span className="font-semibold text-slate-900">{row.count}</span>
                    </div>
                  ))}
                  {(falseAnalytics?.by_guard || []).length === 0 && <p className="text-sm text-slate-500">{t(language, "noGuardData")}</p>}
                </div>
              </div>
            </article>

            <article className="app-surface p-5 xl:col-span-1">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-600">{t(language, "trendIntelligence")}</h3>
                <select
                  aria-label="Trend granularity"
                  value={trendGranularity}
                  onChange={(e) => setTrendGranularity(e.target.value as "hourly" | "daily" | "weekly")}
                  className="rounded-md border border-border bg-card px-2 py-1 text-xs text-foreground"
                >
                  <option value="hourly">{t(language, "trendHourly")}</option>
                  <option value="daily">{t(language, "trendDaily")}</option>
                  <option value="weekly">{t(language, "trendWeekly")}</option>
                </select>
              </div>

              <div className="mt-4 space-y-2">
                {topTrendRows.map((row) => (
                  <div key={row.bucket} className="rounded-lg border border-border bg-card/70 p-2">
                    <div className="flex items-center justify-between text-xs text-slate-500">
                      <span>{row.bucket}</span>
                      <span>{t(language, "trendTotal")} {row.total}</span>
                    </div>
                    <div className="mt-1 grid grid-cols-3 gap-2 text-xs">
                      <span className="rounded bg-emerald-50 px-2 py-1 text-emerald-700">{t(language, "trendVerified")} {row.verified}</span>
                      <span className="rounded bg-amber-50 px-2 py-1 text-amber-700">{t(language, "trendFalse")} {row.false_alarm}</span>
                      <span className="rounded bg-slate-100 px-2 py-1 text-slate-700">{t(language, "trendPending")} {row.pending}</span>
                    </div>
                  </div>
                ))}
                {topTrendRows.length === 0 && <p className="text-sm text-slate-500">{t(language, "noTrendPoints")}</p>}
              </div>
            </article>
          </section>

          <section className="mb-6 app-surface p-5">
            <div className="mb-4 flex items-center gap-2">
              <Activity className="h-4 w-4 text-slate-600" />
              <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-600">Admin Section - Activities</h3>
            </div>

            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
                Total Alerts Reviewed: <span className="font-semibold text-slate-900">{summary?.overall.total_alerts ?? 0}</span>
              </div>
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                Confirmed Threats: <span className="font-semibold">{summary?.overall.confirmed_count ?? 0}</span>
              </div>
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
                Resolved Cases: <span className="font-semibold">{summary?.overall.verified_count ?? 0}</span>
              </div>
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-700">
                Dismissed Alerts: <span className="font-semibold">{summary?.overall.false_alarm_count ?? 0}</span>
              </div>
            </div>
          </section>

          <section className="mb-6 app-surface p-5">
            <div className="mb-4 flex items-center gap-2">
              <Users className="h-4 w-4 text-slate-600" />
              <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-600">Admin Activity</h3>
            </div>

            <div className="mb-4 grid gap-3 md:grid-cols-1">
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
                Total Admins: <span className="font-semibold">{adminActivity?.total_admins ?? 0}</span>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="py-2">Admin Name</th>
                    <th className="py-2">Email</th>
                    <th className="py-2">{t(language, "phone")}</th>
                    <th className="py-2">Activity</th>
                    <th className="py-2">Verification</th>
                    <th className="py-2">Created</th>
                    <th className="py-2">Last Login</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {(adminActivity?.admins || []).map((admin) => (
                    <tr key={admin.id}>
                      <td className="py-2 text-slate-700">{admin.full_name || "Administrator"}</td>
                      <td className="py-2 text-slate-700">{admin.email || "-"}</td>
                      <td className="py-2 text-slate-700">{admin.phone_number || "-"}</td>
                      <td className="py-2">
                        <span className={`rounded-full px-2 py-1 text-xs font-semibold uppercase ${admin.status === "active"
                          ? "bg-emerald-100 text-emerald-700"
                          : "bg-slate-100 text-slate-700"
                          }`}>
                          {admin.status === "active" ? "Active" : "Offline"}
                        </span>
                      </td>
                      <td className="py-2 text-slate-900">{admin.is_verified ? "Verified" : "Pending"}</td>
                      <td className="py-2 text-slate-900">{admin.created_at ? new Date(admin.created_at).toLocaleString() : "-"}</td>
                      <td className="py-2 text-slate-900">{admin.last_login ? new Date(admin.last_login).toLocaleString() : "Never"}</td>
                    </tr>
                  ))}
                  {(adminActivity?.admins || []).length === 0 && (
                    <tr>
                      <td colSpan={7} className="py-6 text-center text-slate-500">No admin records found</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section className="mb-6 app-surface p-5">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Clock3 className="h-4 w-4 text-slate-600" />
                <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-600">Guard Section - Duty Log Audit Trail & Activity</h3>
              </div>
              <div className="flex items-center gap-2">
                <select
                  aria-label="Guard export range"
                  value={guardExportDays}
                  onChange={(event) => setGuardExportDays(Number(event.target.value) as 3 | 7)}
                  className="rounded-md border border-border bg-card px-2 py-1 text-xs text-foreground"
                >
                  <option value={3}>Last 3 Days</option>
                  <option value={7}>Last 7 Days</option>
                </select>
                <a
                  href={guardExportUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-emerald-700"
                >
                  Open / Download Excel
                </a>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="py-2">Guard</th>
                    <th className="py-2">Phone</th>
                    <th className="py-2">Activity</th>
                    <th className="py-2">Check In</th>
                    <th className="py-2">Check Out</th>
                    <th className="py-2">Alerts Received</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {dutyLogs.map((row) => (
                    <tr key={row.id}>
                      <td className="py-2 text-slate-700">{row.guardName || row.guardId}</td>
                      <td className="py-2 text-slate-700">{row.phone_number || "-"}</td>
                      <td className="py-2">
                        <span className={`rounded-full px-2 py-1 text-xs font-semibold uppercase ${row.checkOutTime
                          ? "bg-slate-100 text-slate-700"
                          : "bg-emerald-100 text-emerald-700"
                          }`}>
                          {row.checkOutTime ? "Offline" : "Active"}
                        </span>
                      </td>
                      <td className="py-2 text-slate-900">{row.checkInTime ? new Date(row.checkInTime).toLocaleString() : "-"}</td>
                      <td className="py-2 text-slate-900">{row.checkOutTime ? new Date(row.checkOutTime).toLocaleString() : "On Duty"}</td>
                      <td className="py-2 text-slate-900">{row.totalAlertsReceived}</td>
                    </tr>
                  ))}
                  {dutyLogs.length === 0 && (
                    <tr>
                      <td colSpan={6} className="py-6 text-center text-slate-500">No duty logs found</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section className="grid gap-6 xl:grid-cols-2">
            <article className="app-surface p-5">
              <div className="mb-3 flex items-center gap-2">
                <TrendingUp className="h-4 w-4 text-emerald-600" />
                <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-600">Verified Threats</h3>
              </div>
              <div className="grid grid-cols-1 gap-3">
                {verifiedEvidence.map((item) => {
                  const evidencePaths = (item.evidence_urls || []).filter((path) => Boolean(path));
                  const displayPaths = evidencePaths.length > 0
                    ? evidencePaths.slice(0, 2)
                    : (item.frame_path ? [item.frame_path] : []);
                  return (
                    <div key={item.id} className="overflow-hidden rounded-lg border border-border bg-card/70">
                      <div className={`grid gap-2 p-2 ${displayPaths.length > 1 ? "md:grid-cols-2" : "grid-cols-1"}`}>
                        {displayPaths.map((path, index) => {
                          const imageUrl = buildFileUrl(path);
                          return (
                            <div key={`${item.id}_${index}`} className="aspect-video overflow-hidden rounded bg-slate-900">
                              {imageUrl ? (
                                <img
                                  src={imageUrl}
                                  alt={`Verified threat evidence ${index + 1}`}
                                  className="h-full w-full object-cover"
                                />
                              ) : null}
                            </div>
                          );
                        })}
                      </div>
                      <div className="p-2 text-xs text-slate-600">
                        <p className="font-semibold uppercase text-slate-800">{typeLabel(language, item.type)}</p>
                        <p>{new Date(item.timestamp).toLocaleString()}</p>
                      </div>
                    </div>
                  );
                })}
                {verifiedEvidence.length === 0 && <p className="text-sm text-slate-500">{t(language, "noVerifiedEvidence")}</p>}
              </div>
            </article>

            <article className="app-surface p-5">
              <div className="mb-3 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-amber-600" />
                <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-600">{t(language, "recentFalseAlarms")}</h3>
              </div>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {falseEvidence.map((item) => {
                  const imageUrl = buildFileUrl(item.frame_path);
                  return (
                    <div key={item.id} className="overflow-hidden rounded-lg border border-border bg-card/70">
                      <div className="aspect-video bg-slate-900">
                        {imageUrl ? <img src={imageUrl} alt={t(language, "falseAlarm")} className="h-full w-full object-cover opacity-75" /> : null}
                      </div>
                      <div className="p-2 text-xs text-slate-600">
                        <p className="font-semibold uppercase text-slate-800">{typeLabel(language, item.type)}</p>
                        <p>{new Date(item.timestamp).toLocaleString()}</p>
                      </div>
                    </div>
                  );
                })}
                {falseEvidence.length === 0 && <p className="text-sm text-slate-500">{t(language, "noFalseEvidence")}</p>}
              </div>
            </article>
          </section>

          {loading && <p className="mt-6 text-sm text-slate-500">{t(language, "refreshingReports")}</p>}
        </main>
      </div>
    </div>
  );
}
