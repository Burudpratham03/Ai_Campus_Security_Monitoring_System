import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { Sidebar } from "./Sidebar";
import { Header } from "./Header";
import { DetectionAlert, type DetectionData } from "./DetectionAlert";
import { AlertTriangle, CheckCircle, MapPin, Clock, HardDrive, Activity, Volume2, VolumeX, Eye, ShieldAlert, ShieldCheck, XCircle } from "lucide-react";
import { askChat, cameraStreamUrlById, captureCurrentFrame, fetchAlerts, fetchSystemRuntimeStats, type AlertDto, type SystemRuntimeStatsDto, getGuardStatus, getGuardStatusByPhone } from "../api/client";
import { useAlerts, type LiveAlert } from "../context/AlertsContext";
import { useLanguage } from "../context/LanguageContext";
import { playAlertSound } from "../../utils/soundNotification";
import { GuardDutyPanel } from "./GuardDutyPanel";
import { statusLabel, t, tf, typeLabel } from "../utils/language";
import { toast } from "sonner";

const API_BASE = "http://127.0.0.1:8000";

function formatAlertTime(timestamp: string): string {
    return new Date(timestamp).toLocaleString();
}

function normalizeDetectionType(type: string): DetectionData["type"] {
    const normalized = type.toLowerCase();
    if (normalized === "anomaly") {
        return "suspicious";
    }
    if (normalized === "weapon" || normalized === "violence" || normalized === "fire") {
        return normalized;
    }
    return "suspicious";
}

function mapAlertDtoToLiveAlert(alert: AlertDto): LiveAlert {
    const normalizedType = alert.type.toLowerCase();
    const subtype = alert.subtype || null;
    const label = subtype || normalizedType;

    return {
        id: alert.id,
        type: normalizedType,
        subtype,
        message: `${label} detected`,
        timestamp: alert.timestamp,
        time: formatAlertTime(alert.timestamp),
        location: alert.location || "AI Camera",
        confidence: alert.confidence || 0,
        frameId: alert.frame_id,
        framePath: alert.frame_path,
        sourceCameraId: alert.source_camera_id ?? null,
        primaryCameraId: alert.primary_camera_id ?? null,
        multiAngleVerified: Boolean(alert.multi_angle_verified),
        aiSummaryEn: alert.ai_summary_en,
        aiSummaryHi: alert.ai_summary_hi,
        aiSummaryMr: alert.ai_summary_mr,
        aiNarrativeEn: alert.ai_narrative_en,
        aiNarrativeHi: alert.ai_narrative_hi,
        aiNarrativeMr: alert.ai_narrative_mr,
        movementDirection: alert.movement_direction,
        movementConfidence: alert.movement_confidence,
        narrativeGenerationMode: alert.narrative_generation_mode,
        status: alert.status || (alert.verified ? "confirmed" : "pending"),
        actionHistory: alert.action_history || [],
    };
}

function getLocalizedSummary(alert: LiveAlert, language: string): string | null {
    if (language === "hi") return alert.aiSummaryHi || alert.aiSummaryEn || null;
    if (language === "mr") return alert.aiSummaryMr || alert.aiSummaryEn || null;
    return alert.aiSummaryEn || alert.aiSummaryHi || alert.aiSummaryMr || null;
}

function getLocalizedNarrative(alert: LiveAlert, language: string): string | null {
    if (language === "hi") return alert.aiNarrativeHi || alert.aiNarrativeEn || null;
    if (language === "mr") return alert.aiNarrativeMr || alert.aiNarrativeEn || null;
    return alert.aiNarrativeEn || alert.aiNarrativeHi || alert.aiNarrativeMr || null;
}

function movementDirectionLabel(direction: string | null | undefined, language: string): string {
    const normalized = String(direction || "unknown").toLowerCase();
    const langKey = language === "hi" || language === "mr" ? language : "en";

    if (langKey === "hi") {
        switch (normalized) {
            case "left": return "संभावित रूप से बाईं ओर गया";
            case "right": return "संभावित रूप से दाईं ओर गया";
            case "straight": return "संभावित रूप से सीधे गया";
            case "towards_camera": return "संभावित रूप से कैमरे की ओर आया";
            case "away_from_camera": return "संभावित रूप से कैमरे से दूर गया";
            default: return "मूवमेंट स्पष्ट नहीं है";
        }
    }

    if (langKey === "mr") {
        switch (normalized) {
            case "left": return "बहुधा डावीकडे गेला";
            case "right": return "बहुधा उजवीकडे गेला";
            case "straight": return "बहुधा सरळ गेला";
            case "towards_camera": return "बहुधा कॅमेराकडे आला";
            case "away_from_camera": return "बहुधा कॅमेरापासून दूर गेला";
            default: return "हालचाल स्पष्ट नाही";
        }
    }

    switch (normalized) {
        case "left": return "Likely moved left";
        case "right": return "Likely moved right";
        case "straight": return "Likely moved straight";
        case "towards_camera": return "Likely moved toward camera";
        case "away_from_camera": return "Likely moved away from camera";
        default: return "Movement unclear";
    }
}

function adminIncidentStatusLabel(status: string, language: string): string {
    const normalized = String(status || "").trim().toUpperCase();
    const langKey = language === "hi" || language === "mr" ? language : "en";

    if (langKey === "hi") {
        switch (normalized) {
            case "RESOLVED": return "समाधान किया गया";
            case "NOT_FOUND": return "मौके पर नहीं मिला";
            case "NEED_HELP": return "तत्काल सहायता आवश्यक";
            case "SAFE_FALSE_ALARM": return "सुरक्षित (गलत अलार्म)";
            default: return normalized || "स्थिति अपडेट";
        }
    }

    if (langKey === "mr") {
        switch (normalized) {
            case "RESOLVED": return "निकाली काढले";
            case "NOT_FOUND": return "ठिकाणी सापडला नाही";
            case "NEED_HELP": return "तात्काळ मदत आवश्यक";
            case "SAFE_FALSE_ALARM": return "सुरक्षित (चुकीचा इशारा)";
            default: return normalized || "स्थिती अपडेट";
        }
    }

    switch (normalized) {
        case "RESOLVED": return "Resolved";
        case "NOT_FOUND": return "Not Found";
        case "NEED_HELP": return "Need Help";
        case "SAFE_FALSE_ALARM": return "Safe (False Alarm)";
        default: return normalized || "Status Updated";
    }
}

interface ChatMessage {
    id: number;
    sender: "user" | "bot";
    message: string;
}

export function Dashboard(): React.JSX.Element {
    const navigate = useNavigate();
    const { currentLanguage: language } = useLanguage();
    const [email, setEmail] = useState<string | null>(null);
    const [phoneNumber, setPhoneNumber] = useState<string | null>(null);
    const { alerts, addOrReplaceAlert, clearAllResolved, seenAlertIds, markAlertSeen, confirmThreat, markFalseAlarm } = useAlerts();

    const [detectionAlerts, setDetectionAlerts] = useState<Map<string, DetectionData>>(new Map());
    const [selectedAlert, setSelectedAlert] = useState<string | null>(null);
    const [alertSoundEnabled, setAlertSoundEnabled] = useState(true);
    const [guardOnDuty, setGuardOnDuty] = useState(false);
    const [actionError, setActionError] = useState<string | null>(null);
    const [actionInFlight, setActionInFlight] = useState<string | null>(null);
    const [activeCameraId, setActiveCameraId] = useState<0 | 1>(0);
    const [isConnected, setIsConnected] = useState(false);

    const [chatMessages, setChatMessages] = useState<ChatMessage[]>([{ id: 1, sender: "bot", message: "Hello! I'm GuardGPT. How can I assist you today?" }]);
    const [chatInput, setChatInput] = useState("");

    const canvasRef = useRef<HTMLCanvasElement | null>(null);
    const imgElRef = useRef<HTMLImageElement | null>(null);
    const chatEndRef = useRef<HTMLDivElement | null>(null);
    const languageRef = useRef(language);
    const soundCooldownRef = useRef<Map<string, number>>(new Map());
    const seenAlertTimestamps = useRef<Map<string, string>>(new Map());
    const hasInitializedAlerts = useRef(false);
    const [currentTime, setCurrentTime] = useState<string>(() => new Date().toLocaleString());
    const [systemStats, setSystemStats] = useState<SystemRuntimeStatsDto>({
        captured_frames: 0,
        captures_storage_bytes: 0,
        mongodb_storage_bytes: 0,
        mongodb_alerts_storage_bytes: 0,
    });
    // Testing mode: allow single-camera detections to raise popup + sound.
    // Set localStorage.single_camera_alert_test = "false" to disable.
    const singleCameraAlertTestMode =
        typeof window !== "undefined"
            ? localStorage.getItem("single_camera_alert_test") !== "false"
            : true;

    useEffect(() => {
        const token = localStorage.getItem("authToken");
        const role = localStorage.getItem("authRole");

        if (!token) {
            navigate("/", { replace: true });
            return;
        }
        if (role !== "admin") {
            navigate(role === "guard" ? "/guard/status" : "/", { replace: true });
        }
    }, [navigate]);

    useEffect(() => {
        const storedEmail = localStorage.getItem("authEmail");
        const storedPhone = localStorage.getItem("authPhone");
        setEmail(storedEmail);
        setPhoneNumber(storedPhone);
    }, []);

    useEffect(() => {
        languageRef.current = language;
    }, [language]);

    useEffect(() => {
        const token = localStorage.getItem("authToken");
        const role = localStorage.getItem("authRole");
        if (!token || role !== "admin") {
            setIsConnected(false);
            return;
        }

        const wsBase = API_BASE.replace(/^http/i, "ws");
        const wsUrl = `${wsBase}/ws/admin-notifications?token=${encodeURIComponent(token)}`;

        let socket: WebSocket | null = null;
        let reconnectTimer: number | null = null;
        let heartbeatTimer: number | null = null;
        let stopped = false;
        const RECONNECT_DELAY_MS = 3000;

        const clearHeartbeat = () => {
            if (heartbeatTimer !== null) {
                window.clearInterval(heartbeatTimer);
                heartbeatTimer = null;
            }
        };

        const startHeartbeat = () => {
            clearHeartbeat();
            heartbeatTimer = window.setInterval(() => {
                if (socket && socket.readyState === WebSocket.OPEN) {
                    try {
                        socket.send("ping");
                    } catch {
                        // Ignore heartbeat send failures; onclose handles reconnect.
                    }
                }
            }, 25000);
        };

        const clearReconnectTimer = () => {
            if (reconnectTimer !== null) {
                window.clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }
        };

        const scheduleReconnect = () => {
            if (stopped || reconnectTimer !== null) {
                return;
            }
            reconnectTimer = window.setTimeout(() => {
                reconnectTimer = null;
                connect();
            }, RECONNECT_DELAY_MS);
        };

        const shouldReconnect = (code: number) => {
            // Policy/auth failures should not reconnect in a loop.
            if (code === 1008 || code === 1002 || code === 1003) {
                return false;
            }
            return true;
        };

        const connect = () => {
            if (stopped) {
                return;
            }

            socket = new WebSocket(wsUrl);

            socket.onopen = () => {
                setIsConnected(true);
                clearReconnectTimer();
                startHeartbeat();
            };

            socket.onmessage = (event) => {
                try {
                    const alertData = JSON.parse(event.data || "{}");

                    const cameraIdCandidate =
                        alertData?.camera_id ??
                        alertData?.source_camera_id ??
                        alertData?.primary_camera_id;
                    const hasAlertShape =
                        Boolean(alertData?.type) &&
                        cameraIdCandidate !== undefined &&
                        cameraIdCandidate !== null &&
                        `${cameraIdCandidate}`.trim() !== "";

                    if (hasAlertShape) {
                        const isVerified = alertData.multi_angle_verified === true;
                        const shouldTriggerInstantAlert = isVerified || singleCameraAlertTestMode;
                        const alertType = String(alertData.type);
                        const cameraLabel = `Camera ${cameraIdCandidate}`;
                        const nowIso = new Date().toISOString();
                        const wsAlertId = String(
                            alertData.id ||
                            alertData.alert_id ||
                            `ws-${alertType}-${cameraIdCandidate}-${Date.now()}`
                        );

                        const wsAlert: LiveAlert = {
                            id: wsAlertId,
                            type: String(alertType || "unknown").toLowerCase(),
                            subtype: alertData?.subtype ? String(alertData.subtype) : null,
                            message: `${alertType} detected`,
                            timestamp: String(alertData.timestamp || nowIso),
                            time: formatAlertTime(String(alertData.timestamp || nowIso)),
                            location: String(alertData.location || cameraLabel),
                            confidence: Number(alertData.confidence || 0),
                            frameId: alertData.frame_id ? Number(alertData.frame_id) : undefined,
                            framePath: alertData.frame_path ? String(alertData.frame_path) : undefined,
                            sourceCameraId: Number.isFinite(Number(alertData.source_camera_id)) ? Number(alertData.source_camera_id) : Number(cameraIdCandidate),
                            primaryCameraId: Number.isFinite(Number(alertData.primary_camera_id)) ? Number(alertData.primary_camera_id) : Number(cameraIdCandidate),
                            multiAngleVerified: isVerified,
                            status: "pending",
                            actionHistory: [],
                            aiSummaryEn: null,
                            aiSummaryHi: null,
                            aiSummaryMr: null,
                            aiNarrativeEn: null,
                            aiNarrativeHi: null,
                            aiNarrativeMr: null,
                            movementDirection: null,
                            movementConfidence: null,
                            narrativeGenerationMode: null,
                        };

                        addOrReplaceAlert(wsAlert);
                        markAlertSeen(wsAlert.id);

                        if (shouldTriggerInstantAlert) {
                            const detectionType = normalizeDetectionType(wsAlert.type);
                            addDetectionAlert({
                                id: wsAlert.id,
                                type: detectionType,
                                confidence: wsAlert.confidence,
                                timestamp: wsAlert.time,
                                location: wsAlert.location,
                                frameId: wsAlert.frameId ?? 0,
                                imagePath: wsAlert.framePath,
                            });
                            if (alertSoundEnabled) {
                                const now = Date.now();
                                const lastPlayed = soundCooldownRef.current.get(wsAlert.type) || 0;
                                const soundCooldownMs = wsAlert.type === "weapon" ? 300_000 : 30_000;
                                if (now - lastPlayed >= soundCooldownMs) {
                                    playAlertSound(detectionType);
                                    soundCooldownRef.current.set(wsAlert.type, now);
                                }
                            }
                        }

                        if (isVerified) {
                            toast.error("🔴 TWO-CAMERA VERIFICATION: Threat Detected!", {
                                description: `Threat: ${alertType}. Verified by TWO Camera Angles simultaneously. Immediate action required.`,
                                duration: 10000,
                                action: {
                                    label: "Confirm Threat",
                                    onClick: () => {
                                        setSelectedAlert(wsAlert.id);
                                        void handleConfirmThreat(wsAlert.id);
                                    },
                                },
                                style: {
                                    background: "#7f1d1d",
                                    color: "#ffffff",
                                    border: "1px solid #ef4444",
                                },
                            });
                        }
                        return;
                    }

                    if (alertData?.type === "ALERT_STATUS_UPDATE" || alertData?.type === "ALERT_ESCALATION") {
                        const guardName = String(alertData.guard_name || "Guard");
                        const statusRaw = String(alertData.status || "STATUS_UPDATE");
                        const statusText = adminIncidentStatusLabel(statusRaw, languageRef.current);
                        const alertId = String(alertData.alert_id || "N/A");
                        const location = String(alertData.location || "AI Camera");
                        const description = `Guard: ${guardName} | Alert ID: ${alertId} | Location: ${location}`;

                        if (String(alertData.type) === "ALERT_ESCALATION" || statusRaw.toUpperCase() === "NEED_HELP") {
                            toast.error(`Emergency Update: ${statusText}`, {
                                description,
                                duration: 10000,
                                icon: "🚨",
                            });
                        } else {
                            toast(`Incident Update: ${statusText}`, {
                                description,
                                duration: 7000,
                                icon: "✅",
                            });
                        }
                        return;
                    }

                    if (alertData?.type !== "STATUS_CHANGE") {
                        return;
                    }
                    const guardName = String(alertData.guard_name || "Guard");
                    const status = String(alertData.status || "status updated");
                    const source = String(alertData.source || "WhatsApp");
                    toast(`${guardName} went ${status} via ${source}.`, {
                        description: "Live duty update received",
                        icon: "🔔",
                    });
                } catch {
                    // Ignore malformed websocket payloads.
                }
            };

            socket.onclose = (event) => {
                setIsConnected(false);
                clearHeartbeat();
                if (stopped) {
                    return;
                }

                if (!shouldReconnect(event.code)) {
                    if (event.code === 1008) {
                        toast("Live notifications disconnected", {
                            description: "Admin WebSocket auth failed. Please sign in again.",
                            icon: "⚠️",
                        });
                    }
                    return;
                }

                scheduleReconnect();
            };

            socket.onerror = () => {
                setIsConnected(false);
                if (socket && socket.readyState < WebSocket.CLOSING) {
                    // onclose will schedule reconnect.
                    socket.close();
                    return;
                }
                scheduleReconnect();
            };
        };

        connect();

        return () => {
            stopped = true;
            setIsConnected(false);
            clearHeartbeat();
            clearReconnectTimer();
            if (socket && socket.readyState < WebSocket.CLOSING) {
                socket.close();
            }
        };
    }, []);

    useEffect(() => {
        let cancelled = false;

        const loadDutyStatus = async () => {
            try {
                if (phoneNumber) {
                    const status = await getGuardStatusByPhone(phoneNumber);
                    if (!cancelled) {
                        setGuardOnDuty(status?.status === "on_duty");
                    }
                    return;
                }

                if (email) {
                    const status = await getGuardStatus(email);
                    if (!cancelled) {
                        setGuardOnDuty(status?.status === "on_duty");
                    }
                    return;
                }

                if (!cancelled) {
                    setGuardOnDuty(false);
                }
            } catch (err) {
                console.error("Failed to load guard duty status", err);
                if (!cancelled) {
                    setGuardOnDuty(false);
                }
            }
        };

        void loadDutyStatus();
        return () => {
            cancelled = true;
        };
    }, [email, phoneNumber]);

    useEffect(() => {
        const timer = setInterval(() => setCurrentTime(new Date().toLocaleString()), 1000);
        return () => clearInterval(timer);
    }, []);

    useEffect(() => {
        let cancelled = false;

        const loadSystemStats = async () => {
            try {
                const stats = await fetchSystemRuntimeStats();
                if (!cancelled) {
                    setSystemStats(stats);
                }
            } catch (err) {
                console.error("Failed to load system runtime stats", err);
            }
        };

        loadSystemStats();
        const interval = setInterval(loadSystemStats, 5000);
        return () => {
            cancelled = true;
            clearInterval(interval);
        };
    }, []);

    const formatBytes = (bytes: number) => {
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
    };

    // drawing loop that copies the current image into the canvas overlay
    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        let animationId: number;
        const draw = () => {
            if (ctx) {
                const img = imgElRef.current;
                if (img && img.complete && img.naturalWidth) {
                    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                }
            }
            animationId = requestAnimationFrame(draw);
        };
        draw();
        return () => cancelAnimationFrame(animationId);
    }, []);

    useEffect(() => {
        let cancelled = false;

        const loadAlerts = async () => {
            try {
                const backendAlerts: AlertDto[] = await fetchAlerts(50);
                if (cancelled) return;

                const isInitialLoad = !hasInitializedAlerts.current;

                backendAlerts.forEach((backendAlert) => {
                    const mapped = mapAlertDtoToLiveAlert(backendAlert);
                    addOrReplaceAlert(mapped);

                    // Baseline existing records on first load so refresh doesn't trigger stale popups.
                    if (isInitialLoad) {
                        seenAlertTimestamps.current.set(mapped.id, mapped.timestamp);
                        if (!seenAlertIds.has(mapped.id)) {
                            markAlertSeen(mapped.id);
                        }
                        return;
                    }

                    // Check if this is a genuinely new or updated alert
                    const prevTs = seenAlertTimestamps.current.get(mapped.id);
                    const isUpdated = prevTs !== undefined && prevTs !== mapped.timestamp;
                    const isNew = !seenAlertIds.has(mapped.id);

                    // Always record the latest timestamp for this alert
                    seenAlertTimestamps.current.set(mapped.id, mapped.timestamp);

                    if (!isNew && !isUpdated) {
                        return;
                    }
                    if (isNew) {
                        markAlertSeen(mapped.id);
                    }

                    const shouldTriggerInstantAlert = mapped.multiAngleVerified || singleCameraAlertTestMode;
                    if (shouldTriggerInstantAlert) {
                        // One popup per type: replaces existing same-type popup
                        const detectionType = normalizeDetectionType(mapped.type);
                        addDetectionAlert({
                            id: mapped.id,
                            type: detectionType,
                            confidence: mapped.confidence,
                            timestamp: mapped.time,
                            location: mapped.location,
                            frameId: mapped.frameId ?? 0,
                            imagePath: mapped.framePath,
                        });

                        // Sound with per-type cooldown (weapon=5 min, others=30 s)
                        if (alertSoundEnabled) {
                            const now = Date.now();
                            const lastPlayed = soundCooldownRef.current.get(mapped.type) || 0;
                            const soundCooldownMs = mapped.type === "weapon" ? 300_000 : 30_000;
                            if (now - lastPlayed >= soundCooldownMs) {
                                playAlertSound(detectionType);
                                soundCooldownRef.current.set(mapped.type, now);
                            }
                        }
                    }

                    // Fallback notifications when websocket channel is down.
                    if (!isConnected) {
                        const shouldShowFallbackToast = mapped.multiAngleVerified === true && (isNew || isUpdated);
                        if (shouldShowFallbackToast) {
                            toast.error("🔴 TWO-CAMERA VERIFICATION: Threat Detected!", {
                                description: `Threat: ${mapped.type}. Verified by TWO Camera Angles simultaneously. Immediate action required.`,
                                duration: 10000,
                                action: {
                                    label: "Confirm Threat",
                                    onClick: () => {
                                        setSelectedAlert(mapped.id);
                                        void handleConfirmThreat(mapped.id);
                                    },
                                },
                                style: {
                                    background: "#7f1d1d",
                                    color: "#ffffff",
                                    border: "1px solid #ef4444",
                                },
                            });
                        }
                    }
                });

                if (isInitialLoad) {
                    hasInitializedAlerts.current = true;
                }
            } catch (err) {
                console.error("Failed to load alerts from backend", err);
            }
        };

        loadAlerts();
        const interval = setInterval(loadAlerts, 500);
        return () => { cancelled = true; clearInterval(interval); };
    }, [addOrReplaceAlert, alertSoundEnabled, isConnected, markAlertSeen, seenAlertIds]);

    // helper to add detection popup card – only one popup per type at a time
    const addDetectionAlert = (d: DetectionData) => {
        setDetectionAlerts((prev) => {
            const updated = new Map<string, DetectionData>();
            for (const [key, existing] of prev) {
                if (existing.type !== d.type) {
                    updated.set(key, existing);
                }
            }
            return updated.set(d.id, d);
        });
    };

    const removeDetectionAlert = (id: string) => {
        setDetectionAlerts((prev) => {
            const updated = new Map(prev);
            updated.delete(id);
            return updated;
        });
    };

    const getBorderColor = (type: string) => {
        switch (type) {
            case "weapon": return "border-l-4 border-l-red-500";
            case "violence": return "border-l-4 border-l-orange-500";
            case "fire": return "border-l-4 border-l-yellow-500";
            default: return "border-l-4 border-l-blue-500";
        }
    };

    const handleAlertClick = (alertId: string) => {
        setActionError(null);
        setSelectedAlert(alertId);
    };

    const selectedAlertDetails = selectedAlert ? alerts.find((alert) => alert.id === selectedAlert) ?? null : null;

    /** Save confirmed frame metadata to localStorage for quick local history. */
    const saveFrameToLocalStorage = (alertId: string, alertType: string, framePath?: string | null) => {
        const key = "confirmed_frames";
        const existing: Array<{ id: string; type: string; framePath: string | null; timestamp: string }> = JSON.parse(localStorage.getItem(key) || "[]");
        existing.unshift({
            id: alertId,
            type: alertType,
            framePath: framePath || null,
            timestamp: new Date().toISOString(),
        });
        // Keep at most 100 rows to avoid localStorage growth
        localStorage.setItem(key, JSON.stringify(existing.slice(0, 100)));
    };

    const handleConfirmThreat = async (alertId: string) => {
        try {
            setActionInFlight(`confirm:${alertId}`);
            setActionError(null);

            // 1) Capture a fresh frame on backend to avoid browser CORS canvas issues.
            let confirmedFramePath: string | null = null;
            try {
                const capture = await captureCurrentFrame(activeCameraId);
                confirmedFramePath = capture?.frame_path || null;
            } catch (captureErr) {
                console.warn("Backend frame capture failed, continuing with confirm:", captureErr);
            }

            // 2) Keep a local record for quick browser-side history.
            const alertData = alerts.find((a) => a.id === alertId);
            saveFrameToLocalStorage(alertId, alertData?.type || "unknown", confirmedFramePath);

            // 3) Confirm the threat in the database
            await confirmThreat(alertId, email || undefined, confirmedFramePath || undefined, activeCameraId);
            setChatMessages((prev) => [...prev, { id: Date.now(), sender: "bot", message: t(language, "threatConfirmedMsg") }]);
        } catch (err) {
            console.error(err);
            setActionError(err instanceof Error ? err.message : t(language, "confirmThreat"));
        } finally {
            setActionInFlight(null);
        }
    };

    const handleFalseAlarm = async (alertId: string) => {
        try {
            setActionInFlight(`false:${alertId}`);
            setActionError(null);
            await markFalseAlarm(alertId, email || undefined);
            setChatMessages((prev) => [...prev, { id: Date.now(), sender: "bot", message: t(language, "falseAlarmRecordedMsg") }]);
        } catch (err) {
            console.error(err);
            setActionError(err instanceof Error ? err.message : "Failed to mark false alarm.");
        } finally {
            setActionInFlight(null);
        }
    };

    const getStatusBadge = (status: LiveAlert["status"]) => {
        switch (status) {
            case "confirmed":
                return "bg-red-100 text-red-700";
            case "dismissed":
                return "bg-gray-200 text-gray-700";
            case "resolved":
                return "bg-blue-100 text-blue-700";
            default:
                return "bg-amber-100 text-amber-700";
        }
    };

    const getAlertTitle = (alert: LiveAlert): string => {
        const label = typeLabel(language, alert.subtype || alert.type);
        return `${label} ${t(language, "detected")}`.trim();
    };

    const buildCaptureUrl = (framePath?: string) => {
        if (!framePath) return null;
        return `${API_BASE}/file/${encodeURIComponent(framePath).replace(/%2F/g, "/")}`;
    };

    const handleSendMessage = async () => {
        if (!chatInput.trim()) return;
        const userMessage: ChatMessage = { id: Date.now(), sender: "user", message: chatInput };
        setChatMessages((prev) => [...prev, userMessage]);
        setChatInput("");
        try {
            const res = await askChat(userMessage.message, email || undefined, null, language);
            const botMessage: ChatMessage = { id: Date.now() + 1, sender: "bot", message: res.response };
            setChatMessages((prev) => [...prev, botMessage]);
        } catch (err) {
            console.error(err);
            setChatMessages((prev) => [...prev, { id: Date.now() + 1, sender: "bot", message: t(language, "serverUnavailable") }]);
        }
    };

    return (
        <div className="app-page flex h-screen">
            <Sidebar />
            <div className="flex-1 flex flex-col overflow-visible">
                <Header />
                <main className="flex-1 overflow-auto p-6 pb-20">
                    <div className="flex gap-6 h-full">
                        <div className="flex-1">
                            <div className="app-surface p-4 h-full flex flex-col app-animate-enter">
                                <div className="flex items-center justify-between mb-4">
                                    <h2 className="text-lg font-semibold text-foreground">{t(language, "dashboardFeed")}</h2>
                                    <div className="flex items-center gap-4">
                                        <button onClick={() => setAlertSoundEnabled(!alertSoundEnabled)} className={`p-2 rounded-lg border ${alertSoundEnabled ? "border-primary/25 bg-secondary text-primary" : "border-border bg-card text-muted-foreground"}`} title={alertSoundEnabled ? "Mute alerts" : "Unmute alerts"}>
                                            {alertSoundEnabled ? <Volume2 className="w-5 h-5" /> : <VolumeX className="w-5 h-5" />}
                                        </button>
                                        <span className={`rounded-full px-2 py-1 text-xs font-semibold ${isConnected ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"}`}>
                                            {isConnected ? "🟢 Connected" : "🔴 Disconnected - Reconnecting..."}
                                        </span>
                                    </div>
                                </div>

                                {!guardOnDuty && (
                                    <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                                        {t(language, "noGuardOnDuty")}
                                    </div>
                                )}

                                <div className="flex-1 bg-gray-900 rounded-lg relative overflow-hidden min-h-[400px]">
                                    <img
                                        ref={imgElRef}
                                        src={cameraStreamUrlById(activeCameraId)}
                                        alt={t(language, "dashboardFeed")}
                                        className="absolute inset-0 w-full h-full object-cover"
                                    />
                                    {/* canvas sits on top for optional drawing / overlays */}
                                    <canvas ref={canvasRef} width={800} height={600} className="absolute inset-0 w-full h-full" />
                                </div>
                                <div className="mt-3 flex items-center justify-between rounded-lg border border-border bg-card px-3 py-2">
                                    <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                                        Viewing: {activeCameraId === 0 ? "Camera 1 Area" : "Camera 2 Area"}
                                    </span>
                                    <button
                                        onClick={() => setActiveCameraId((prev) => (prev === 0 ? 1 : 0))}
                                        className="app-btn-primary rounded-md px-3 py-1.5 text-xs font-semibold"
                                    >
                                        Switch Angle 🔄
                                    </button>
                                </div>
                            </div>
                        </div>

                        <div className="w-[26rem] xl:w-[28rem] flex-shrink-0 flex flex-col gap-6">
                            {email && (
                                <GuardDutyPanel
                                    email={email}
                                    onStatusChange={(status) => {
                                        const nextOnDuty = status?.status === "on_duty";
                                        setGuardOnDuty(nextOnDuty);
                                        if (!nextOnDuty) {
                                            setDetectionAlerts(new Map());
                                            setSelectedAlert(null);
                                        }
                                    }}
                                />
                            )}

                            <div id="live-alerts" className="app-surface p-5 flex-1 overflow-hidden flex flex-col app-animate-enter">
                                <div className="mb-4 border-b border-border/70 pb-3">
                                    <div className="flex items-center justify-between">
                                        <div className="flex items-center gap-2">
                                            <h3 className="font-semibold text-foreground">{t(language, "liveAlerts")}</h3>
                                            <span className="rounded-full border border-border bg-card px-2 py-0.5 text-xs font-semibold text-muted-foreground">
                                                {tf(language, "activeCount", { count: alerts.length })}
                                            </span>
                                        </div>
                                        <button
                                            onClick={() => clearAllResolved()}
                                            disabled={alerts.length === 0}
                                            className="text-sm px-2 py-1 rounded-md border border-border bg-card text-muted-foreground hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-50"
                                        >
                                            {t(language, "clearResolved")}
                                        </button>
                                    </div>
                                    <p className="mt-1 text-xs text-muted-foreground">{t(language, "reviewHint")}</p>
                                </div>

                                <div className="space-y-3 overflow-y-auto overflow-x-hidden flex-1 pr-1">
                                    {selectedAlertDetails && (
                                        <div className="rounded-lg border border-blue-200 bg-blue-50/90 p-4 min-w-0">
                                            <div className="flex items-start justify-between gap-3">
                                                <div>
                                                    <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">{t(language, "reviewAlert")}</p>
                                                    <h4 className="mt-1 text-base font-semibold text-foreground break-words">{getAlertTitle(selectedAlertDetails)}</h4>
                                                    {selectedAlertDetails.multiAngleVerified && (
                                                        <p className="mt-2 inline-flex rounded-md border border-red-300 bg-red-50 px-2 py-1 text-xs font-semibold text-red-700">
                                                            🔴 HIGH CONFIDENCE: Verified on 2 Angles
                                                        </p>
                                                    )}
                                                </div>
                                                <span className={`rounded-full px-2 py-1 text-xs font-semibold uppercase ${getStatusBadge(selectedAlertDetails.status)}`}>
                                                    {statusLabel(language, selectedAlertDetails.status)}
                                                </span>
                                            </div>

                                            <div className="mt-3 grid grid-cols-2 gap-3 text-sm text-slate-700">
                                                <div>
                                                    <p className="text-xs font-semibold uppercase text-gray-500">{t(language, "confidence")}</p>
                                                    <p>{(selectedAlertDetails.confidence * 100).toFixed(1)}%</p>
                                                </div>
                                                <div>
                                                    <p className="text-xs font-semibold uppercase text-gray-500">{t(language, "location")}</p>
                                                    <p>{selectedAlertDetails.location}</p>
                                                </div>
                                                <div>
                                                    <p className="text-xs font-semibold uppercase text-gray-500">{t(language, "detectedAt")}</p>
                                                    <p>{selectedAlertDetails.time}</p>
                                                </div>
                                                <div>
                                                    <p className="text-xs font-semibold uppercase text-gray-500">{t(language, "classLabel")}</p>
                                                    <p>{typeLabel(language, selectedAlertDetails.subtype || selectedAlertDetails.type)}</p>
                                                </div>
                                            </div>

                                            {getLocalizedSummary(selectedAlertDetails, language) && (
                                                <div className="mt-3 rounded-lg border border-blue-200 bg-white/85 p-3 text-sm text-slate-800">
                                                    <p className="text-xs font-semibold uppercase text-blue-700">Incident Summary</p>
                                                    <p className="mt-1 leading-relaxed">{getLocalizedSummary(selectedAlertDetails, language)}</p>
                                                </div>
                                            )}

                                            {getLocalizedNarrative(selectedAlertDetails, language) && (
                                                <div className="mt-3 rounded-lg border border-indigo-200 bg-white/85 p-3 text-sm text-slate-800">
                                                    <p className="text-xs font-semibold uppercase text-indigo-700">Investigation Narrative</p>
                                                    <p className="mt-1 whitespace-pre-wrap leading-relaxed">{getLocalizedNarrative(selectedAlertDetails, language)}</p>
                                                </div>
                                            )}

                                            <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50/80 p-3 text-sm text-amber-900">
                                                <p className="text-xs font-semibold uppercase text-amber-700">Movement Assessment</p>
                                                <p className="mt-1">
                                                    {movementDirectionLabel(selectedAlertDetails.movementDirection, language)}
                                                    {typeof selectedAlertDetails.movementConfidence === "number" && (
                                                        <span className="ml-1">({(selectedAlertDetails.movementConfidence * 100).toFixed(1)}%)</span>
                                                    )}
                                                </p>
                                            </div>

                                            {buildCaptureUrl(selectedAlertDetails.framePath) && (
                                                <img
                                                    src={buildCaptureUrl(selectedAlertDetails.framePath) || undefined}
                                                    alt={t(language, "capturedEvidence")}
                                                    className="mt-3 h-36 w-full rounded-lg object-cover"
                                                />
                                            )}

                                            {actionError && <p className="mt-3 text-sm text-red-600">{actionError}</p>}

                                            <div className="mt-4 grid grid-cols-2 gap-2">
                                                <button
                                                    onClick={() => handleConfirmThreat(selectedAlertDetails.id)}
                                                    disabled={selectedAlertDetails.status !== "pending" || actionInFlight !== null}
                                                    className="app-btn-danger rounded-md px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                                                >
                                                    {t(language, "confirmThreat")}
                                                </button>
                                                <button
                                                    onClick={() => handleFalseAlarm(selectedAlertDetails.id)}
                                                    disabled={selectedAlertDetails.status !== "pending" || actionInFlight !== null}
                                                    className="app-btn-secondary rounded-md px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                                                >
                                                    {t(language, "falseAlarm")}
                                                </button>
                                            </div>
                                        </div>
                                    )}

                                    {!selectedAlertDetails && alerts.length === 0 && (
                                        <div className="rounded-lg border border-dashed border-border bg-card/70 p-4 text-sm text-muted-foreground">
                                            {t(language, "noActiveAlerts")}
                                        </div>
                                    )}

                                    {alerts.map((alert) => (
                                        <div key={alert.id} onClick={() => handleAlertClick(alert.id)} className={`p-4 rounded-lg bg-card/95 border border-border shadow-sm cursor-pointer hover:shadow min-w-0 ${getBorderColor(alert.type)}`}>
                                            <div className="flex items-start gap-3">
                                                <div className={`mt-1 ${alert.type === "weapon" ? "text-red-500" : alert.type === "violence" ? "text-orange-500" : alert.type === "fire" ? "text-yellow-500" : "text-blue-500"}`}>
                                                    {alert.status === "confirmed" ? <ShieldCheck className="w-5 h-5" /> : alert.status === "dismissed" ? <XCircle className="w-5 h-5" /> : <ShieldAlert className="w-5 h-5" />}
                                                </div>
                                                <div className="flex-1 min-w-0">
                                                    <div className="flex items-center justify-between gap-2">
                                                        <p className="font-semibold text-foreground break-words">{getAlertTitle(alert)}</p>
                                                        <span className={`rounded-full px-2 py-1 text-[11px] font-semibold uppercase ${getStatusBadge(alert.status)}`}>
                                                            {statusLabel(language, alert.status)}
                                                        </span>
                                                    </div>
                                                    {alert.multiAngleVerified && (
                                                        <p className="mt-2 rounded-md border border-red-300 bg-red-50 px-2 py-1 text-[11px] font-semibold text-red-700">
                                                            🔴 HIGH CONFIDENCE: Verified on 2 Angles
                                                        </p>
                                                    )}
                                                    <p className="mt-1 text-sm text-muted-foreground">{t(language, "confidence")} {(alert.confidence * 100).toFixed(1)}%</p>
                                                    <div className="mt-2 space-y-1">
                                                        <div className="flex items-center gap-2 text-sm text-muted-foreground"><Clock className="w-4 h-4" /><span>{alert.time}</span></div>
                                                        <div className="flex items-center gap-2 text-sm text-muted-foreground"><MapPin className="w-4 h-4" /><span>{alert.location}</span></div>
                                                    </div>
                                                    <div className="mt-3 grid grid-cols-2 gap-2">
                                                        <button onClick={(e) => { e.stopPropagation(); handleAlertClick(alert.id); }} className="app-btn-primary col-span-2 px-3 py-1.5 rounded-md text-xs flex items-center justify-center gap-1"><Eye className="h-3.5 w-3.5" />{t(language, "reviewAlert")}</button>
                                                        <button onClick={async (e) => { e.stopPropagation(); await handleConfirmThreat(alert.id); }} disabled={alert.status !== "pending" || actionInFlight !== null} className="app-btn-danger px-3 py-1.5 rounded-md text-xs disabled:cursor-not-allowed disabled:opacity-50">{t(language, "confirm")}</button>
                                                        <button onClick={async (e) => { e.stopPropagation(); await handleFalseAlarm(alert.id); }} disabled={alert.status !== "pending" || actionInFlight !== null} className="app-btn-secondary px-3 py-1.5 rounded-md text-xs disabled:cursor-not-allowed disabled:opacity-50">{t(language, "falseAlarm")}</button>
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>
                    </div>
                </main>

                <footer className="fixed bottom-0 left-72 right-0 border-t border-border bg-card/92 backdrop-blur px-6 py-3">
                    <div className="flex items-center justify-between text-sm">
                        <div className="flex items-center gap-6">
                            <div className="flex items-center gap-2 text-muted-foreground"><Activity className="w-4 h-4 text-primary" /><span className="font-medium">{t(language, "capturedFrames")}</span> <span className="font-semibold text-foreground">{systemStats.captured_frames.toLocaleString()}</span></div>
                            <div className="flex items-center gap-2 text-muted-foreground"><HardDrive className="w-4 h-4 text-green-600" /><span className="font-medium">{t(language, "mongoUsed")}</span> <span className="font-semibold text-foreground">{formatBytes(systemStats.mongodb_storage_bytes)}</span></div>
                            <div className="flex items-center gap-2 text-muted-foreground"><HardDrive className="w-4 h-4 text-blue-600" /><span className="font-medium">{t(language, "captureStorage")}</span> <span className="font-semibold text-foreground">{formatBytes(systemStats.captures_storage_bytes)}</span></div>
                        </div>
                        <div className="flex items-center gap-2"><div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" /><span className="text-muted-foreground font-medium">{t(language, "allSystemsOperational")}</span></div>
                    </div>
                </footer>
            </div>

            {/* Detection Alerts - Bottom Right */}
            <div className="fixed bottom-4 right-4 space-y-3 z-50">
                {Array.from(detectionAlerts.values()).map((detection) => (
                    <DetectionAlert
                        key={detection.id}
                        detection={detection}
                        language={language}
                        onDismiss={removeDetectionAlert}
                        onConfirm={handleConfirmThreat}
                        onFalseAlarm={handleFalseAlarm}
                    />
                ))}
            </div>
        </div>
    );
}

export default Dashboard;
