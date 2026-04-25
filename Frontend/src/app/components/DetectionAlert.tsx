import { useState, useEffect } from "react";
import { AlertTriangle, Flame, Skull, Eye, X, ShieldCheck, XCircle } from "lucide-react";
import { t, type AppLanguage } from "../utils/language";

export interface DetectionData {
    id: string;
    type: "weapon" | "violence" | "fire" | "suspicious";
    confidence: number;
    timestamp: string;
    location: string;
    frameId: number;
    imagePath?: string;
}

interface DetectionAlertProps {
    detection: DetectionData;
    language: AppLanguage;
    onDismiss: (id: string) => void;
    onConfirm?: (id: string) => void;
    onFalseAlarm?: (id: string) => void;
}

export function DetectionAlert({ detection, language, onDismiss, onConfirm, onFalseAlarm }: DetectionAlertProps) {
    const [isVisible, setIsVisible] = useState(true);

    // Allow users to disable detection popups by setting
    // `localStorage.enable_detection_popups = 'false'` in their browser.
    const notificationsEnabled =
        typeof window !== "undefined"
            ? localStorage.getItem("enable_detection_popups") !== "false"
            : true;

    if (!notificationsEnabled) return null;

    useEffect(() => {
        // Auto-dismiss after 5 seconds
        const timer = setTimeout(() => {
            setIsVisible(false);
            setTimeout(() => onDismiss(detection.id), 300);
        }, 5000);
        return () => clearTimeout(timer);
    }, [detection.id, onDismiss]);

    if (!isVisible) return null;

    const getTypeConfig = (type: string) => {
        switch (type) {
            case "weapon":
                return {
                    icon: Skull,
                    color: "bg-red-50 border-red-300",
                    badge: "bg-red-100 text-red-800",
                    title: `⚠️ ${t(language, "detectionPopupWeapon")}`,
                    bgColor: "from-red-500 to-red-600",
                };
            case "violence":
                return {
                    icon: AlertTriangle,
                    color: "bg-orange-50 border-orange-300",
                    badge: "bg-orange-100 text-orange-800",
                    title: `🚨 ${t(language, "detectionPopupViolence")}`,
                    bgColor: "from-orange-500 to-orange-600",
                };
            case "fire":
                return {
                    icon: Flame,
                    color: "bg-yellow-50 border-yellow-300",
                    badge: "bg-yellow-100 text-yellow-800",
                    title: `🔥 ${t(language, "detectionPopupFire")}`,
                    bgColor: "from-yellow-500 to-yellow-600",
                };
            case "suspicious":
                return {
                    icon: Eye,
                    color: "bg-blue-50 border-blue-300",
                    badge: "bg-blue-100 text-blue-800",
                    title: `👁️ ${t(language, "detectionPopupSuspicious")}`,
                    bgColor: "from-blue-500 to-blue-600",
                };
            default:
                return {
                    icon: AlertTriangle,
                    color: "bg-gray-50 border-gray-300",
                    badge: "bg-gray-100 text-gray-800",
                    title: t(language, "detectionPopupDefault"),
                    bgColor: "from-gray-500 to-gray-600",
                };
        }
    };

    const config = getTypeConfig(detection.type);
    const IconComponent = config.icon;

    return (
        <div
            className={`fixed bottom-4 right-4 z-[9999] w-96 rounded-lg border-l-4 border-l-red-500 shadow-2xl animate-in slide-in-from-right-full duration-300 max-md:w-full max-md:max-w-sm`}
        >
            <div className={`${config.color} border bg-card/95 rounded-lg overflow-hidden backdrop-blur`}>
                {/* Header with gradient */}
                <div className={`bg-gradient-to-r ${config.bgColor} p-4 text-white`}>
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                            <IconComponent className="w-6 h-6" strokeWidth={2.5} />
                            <h3 className="font-bold text-lg">{config.title}</h3>
                        </div>
                        <button
                            onClick={() => {
                                setIsVisible(false);
                                setTimeout(() => onDismiss(detection.id), 300);
                            }}
                            className="rounded p-1 transition-colors hover:bg-white/20"
                            aria-label={t(language, "dismissAlert")}
                        >
                            <X className="w-5 h-5" />
                        </button>
                    </div>
                </div>

                {/* Content */}
                <div className="p-4 space-y-4">
                    {/* Visual Representation */}
                    <div className={`h-32 rounded-lg ${config.color.split(" ")[0]} border border-dashed ${config.color.split(" ")[1]} flex items-center justify-center relative overflow-hidden`}>
                        {/* Bounding box animation */}
                        <div className="absolute inset-2 border-2 border-dotted border-red-400 animate-pulse" />
                        <div className="text-center relative z-10">
                            <IconComponent className="w-12 h-12 text-red-400 mx-auto mb-1 opacity-50" />
                            <p className="text-sm font-semibold text-slate-600">{t(language, "detectionArea")}</p>
                        </div>
                    </div>

                    {/* Details Grid */}
                    <div className="grid grid-cols-2 gap-4">
                        {/* Confidence */}
                        <div className="rounded-lg bg-muted p-3">
                            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t(language, "confidence")}</p>
                            <p className="mt-1 text-2xl font-bold text-foreground">
                                {(detection.confidence * 100).toFixed(1)}%
                            </p>
                            <progress className="mt-2 h-2 w-full overflow-hidden rounded-full accent-red-500" max={100} value={Math.round(detection.confidence * 100)} />
                        </div>

                        {/* Frame ID */}
                        <div className="rounded-lg bg-muted p-3">
                            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t(language, "frameId")}</p>
                            <p className="mt-1 text-2xl font-bold text-foreground">{detection.frameId}</p>
                            <p className="mt-1 text-xs text-muted-foreground">{t(language, "datasetReference")}</p>
                        </div>

                        {/* Timestamp */}
                        <div className="rounded-lg bg-muted p-3">
                            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t(language, "time")}</p>
                            <p className="mt-1 text-sm font-semibold text-foreground">{detection.timestamp}</p>
                        </div>

                        {/* Location */}
                        <div className="rounded-lg bg-muted p-3">
                            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t(language, "location")}</p>
                            <p className="mt-1 text-sm font-semibold text-foreground">📍 {detection.location}</p>
                        </div>
                    </div>

                    {/* Storage Path */}
                    <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
                        <p className="text-xs text-blue-600 font-semibold uppercase tracking-wide mb-1">
                            📁 {t(language, "captureStorageTitle")}
                        </p>
                        <p className="text-sm font-mono text-blue-900 break-all">
                            /captures/{detection.type}/{detection.timestamp.replace(/[: ]/g, "-")}.jpg
                        </p>
                    </div>

                    {/* Action Buttons */}
                    <div className="flex gap-2">
                        {onConfirm && (
                            <button
                                onClick={() => {
                                    onConfirm(detection.id);
                                    setIsVisible(false);
                                    setTimeout(() => onDismiss(detection.id), 300);
                                }}
                                className="app-btn-danger flex-1 items-center justify-center gap-2 py-2 rounded-lg"
                            >
                                <ShieldCheck className="w-4 h-4" />
                                {t(language, "confirmThreat")}
                            </button>
                        )}
                        {onFalseAlarm && (
                            <button
                                onClick={() => {
                                    onFalseAlarm(detection.id);
                                    setIsVisible(false);
                                    setTimeout(() => onDismiss(detection.id), 300);
                                }}
                                className="app-btn-secondary flex-1 items-center justify-center gap-2 py-2 rounded-lg"
                            >
                                <XCircle className="w-4 h-4" />
                                {t(language, "falseAlarm")}
                            </button>
                        )}
                    </div>
                </div>

                {/* Footer - Auto-dismiss timer */}
                <div className="flex items-center justify-between bg-muted px-4 py-2 text-xs text-muted-foreground">
                    <span>{t(language, "detectionLogged")}</span>
                    <span className="animate-pulse">●</span>
                </div>
            </div>
        </div>
    );
}
