import { AlertTriangle } from "lucide-react";
import { useState } from "react";

const API_BASE = "http://127.0.0.1:8000";

interface SOSButtonProps {
    onTriggered?: () => void;
}

export function SOSButton({ onTriggered }: SOSButtonProps) {
    const [isLockdown, setIsLockdown] = useState(false);
    const [isSubmitting, setIsSubmitting] = useState(false);

    const handleTrigger = async () => {
        if (isSubmitting || isLockdown) {
            return;
        }

        const confirmed = window.confirm(
            "CRITICAL ACTION: This will trigger CAMPUS LOCKDOWN escalation for all on-duty guards. Continue?"
        );
        if (!confirmed) {
            return;
        }

        const triggeredBy =
            localStorage.getItem("user_id") ||
            localStorage.getItem("authEmail") ||
            localStorage.getItem("authName") ||
            "admin";

        setIsSubmitting(true);
        try {
            const token = localStorage.getItem("authToken");
            const res = await fetch(`${API_BASE}/api/lockdown`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...(token ? { Authorization: `Bearer ${token}` } : {}),
                },
                body: JSON.stringify({ triggered_by: triggeredBy }),
            });

            if (!res.ok) {
                const text = await res.text();
                throw new Error(text || `Request failed with status ${res.status}`);
            }

            setIsLockdown(true);
            onTriggered?.();
        } catch (error) {
            const message = error instanceof Error ? error.message : "Failed to trigger lockdown";
            window.alert(`Lockdown trigger failed: ${message}`);
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <button
            type="button"
            onClick={handleTrigger}
            disabled={isSubmitting}
            className={[
                "flex items-center gap-2 px-6 py-2.5 rounded-xl font-semibold text-white transition-all shadow-lg hover:shadow-xl",
                isLockdown
                    ? "bg-red-900 hover:brightness-100 animate-pulse"
                    : "bg-gradient-to-br from-red-600 to-red-700 hover:brightness-105",
                isSubmitting ? "opacity-70 cursor-not-allowed" : "",
            ].join(" ")}
            aria-live="polite"
        >
            <AlertTriangle className="w-5 h-5" />
            <span>{isLockdown ? "LOCKDOWN ACTIVE" : "SOS / LOCKDOWN"}</span>
        </button>
    );
}
