import React, { createContext, useContext, useMemo, useState, ReactNode } from "react";
import { confirmAlert, markAsFalseAlarm } from "../api/client";

export interface LiveAlert {
    id: string;
    type: string;
    subtype?: string | null;
    message: string;
    timestamp: string;
    time: string;
    location: string;
    confidence: number;
    frameId?: number;
    framePath?: string;
    sourceCameraId?: number | null;
    primaryCameraId?: number | null;
    multiAngleVerified?: boolean;
    aiSummaryEn?: string | null;
    aiSummaryHi?: string | null;
    aiSummaryMr?: string | null;
    aiNarrativeEn?: string | null;
    aiNarrativeHi?: string | null;
    aiNarrativeMr?: string | null;
    movementDirection?: string | null;
    movementConfidence?: number | null;
    narrativeGenerationMode?: string | null;
    status: "pending" | "confirmed" | "dismissed" | "resolved";
    actionHistory: Array<{
        action: string;
        by?: string | null;
        timestamp?: string;
    }>;
}

const FALSE_ALARM_STORAGE_KEY = "false_alarm_history";

function persistFalseAlarmLocally(alert: LiveAlert) {
    if (typeof window === "undefined") return;

    const raw = window.localStorage.getItem(FALSE_ALARM_STORAGE_KEY);
    const items: LiveAlert[] = raw ? JSON.parse(raw) : [];
    const next = [
        {
            ...alert,
            status: "dismissed" as const,
        },
        ...items.filter((item) => item.id !== alert.id),
    ].slice(0, 100);

    window.localStorage.setItem(FALSE_ALARM_STORAGE_KEY, JSON.stringify(next));
}

interface AlertsContextValue {
    alerts: LiveAlert[];
    setAlerts: (a: LiveAlert[]) => void;
    addOrReplaceAlert: (a: LiveAlert) => void;
    removeAlert: (id: string) => void;
    confirmThreat: (id: string, email?: string, confirmedFramePath?: string, primaryCameraId?: number) => Promise<void>;
    markFalseAlarm: (id: string, email?: string) => Promise<void>;
    clearAllResolved: () => void;
    seenAlertIds: Set<string>;
    markAlertSeen: (id: string) => void;
}

const AlertsContext = createContext<AlertsContextValue | null>(null);

export const useAlerts = () => {
    const ctx = useContext(AlertsContext);
    if (!ctx) throw new Error("useAlerts must be used within AlertsProvider");
    return ctx;
};

export function AlertsProvider({ children }: { children: ReactNode }) {
    const [alerts, setAlerts] = useState<LiveAlert[]>([]);
    const [seenAlertIds, setSeenAlertIds] = useState<Set<string>>(new Set());

    const addOrReplaceAlert = (a: LiveAlert) => {
        setAlerts((prev) => {
            const idx = prev.findIndex((p) => p.id === a.id);
            if (idx === -1) {
                return [a, ...prev].sort((left, right) => right.timestamp.localeCompare(left.timestamp));
            }
            const copy = [...prev];
            copy[idx] = { ...copy[idx], ...a };
            return copy.sort((left, right) => right.timestamp.localeCompare(left.timestamp));
        });
    };

    const removeAlert = (id: string) => setAlerts((prev) => prev.filter((p) => p.id !== id));

    const markAlertSeen = (id: string) => {
        setSeenAlertIds((prev) => {
            const copy = new Set(prev);
            copy.add(id);
            return copy;
        });
    };

    const confirmThreat = async (id: string, email?: string, confirmedFramePath?: string, primaryCameraId?: number) => {
        let response;
        try {
            response = await confirmAlert(id, email, confirmedFramePath, primaryCameraId);
        } catch (err) {
            console.error("confirmThreat API failed:", err);
            throw err;
        }
        setAlerts((prev) => prev.map((p) => {
            if (p.id !== id) return p;
            return {
                ...p,
                status: "confirmed",
                framePath: response?.frame_path_used || p.framePath,
                primaryCameraId: response?.primary_camera_id ?? primaryCameraId ?? p.primaryCameraId,
                aiSummaryEn: response?.narrative?.ai_summary_en ?? p.aiSummaryEn,
                aiSummaryHi: response?.narrative?.ai_summary_hi ?? p.aiSummaryHi,
                aiSummaryMr: response?.narrative?.ai_summary_mr ?? p.aiSummaryMr,
                aiNarrativeEn: response?.narrative?.ai_narrative_en ?? p.aiNarrativeEn,
                aiNarrativeHi: response?.narrative?.ai_narrative_hi ?? p.aiNarrativeHi,
                aiNarrativeMr: response?.narrative?.ai_narrative_mr ?? p.aiNarrativeMr,
                movementDirection: response?.narrative?.movement_direction ?? p.movementDirection,
                movementConfidence: response?.narrative?.movement_confidence ?? p.movementConfidence,
                narrativeGenerationMode: response?.narrative?.narrative_generation_mode ?? p.narrativeGenerationMode,
            };
        }));
    };

    const markFalseAlarm = async (id: string, email?: string) => {
        const target = alerts.find((alert) => alert.id === id);
        try {
            await markAsFalseAlarm(id, email);
        } catch (err) {
            console.error("markFalseAlarm API failed:", err);
            throw err;
        }
        if (target) {
            persistFalseAlarmLocally(target);
        }
        setAlerts((prev) => prev.map((p) => (p.id === id ? { ...p, status: "dismissed" } : p)));
    };

    const clearAllResolved = () => {
        setAlerts((prev) => prev.filter((p) => p.status === "pending"));
    };

    const value = useMemo<AlertsContextValue>(() => ({
        alerts,
        setAlerts: (a) => setAlerts(a),
        addOrReplaceAlert,
        removeAlert,
        confirmThreat,
        markFalseAlarm,
        clearAllResolved,
        seenAlertIds,
        markAlertSeen,
    }), [alerts, seenAlertIds]);

    return <AlertsContext.Provider value={value}>{children}</AlertsContext.Provider>;
}

export default AlertsContext;
