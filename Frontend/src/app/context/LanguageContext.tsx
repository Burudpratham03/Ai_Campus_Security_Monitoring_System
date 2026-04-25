import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { getMyLanguage } from "../api/client";
import { APP_LANGUAGE_EVENT, getAppLanguage, normalizeLanguage, setAppLanguage, type AppLanguage } from "../utils/language";

interface LanguageContextValue {
    currentLanguage: AppLanguage;
    changeLanguage: (langCode: string) => AppLanguage;
    syncLanguageFromBackend: () => Promise<void>;
}

const LanguageContext = createContext<LanguageContextValue | undefined>(undefined);

export function LanguageProvider({ children }: { children: ReactNode }) {
    const [currentLanguage, setCurrentLanguage] = useState<AppLanguage>(getAppLanguage());

    const applyLanguage = useCallback((langCode: string) => {
        const normalized = setAppLanguage(langCode);
        setCurrentLanguage(normalized);
        return normalized;
    }, []);

    const syncLanguageFromBackend = useCallback(async () => {
        const authToken = localStorage.getItem("authToken") || localStorage.getItem("token");
        if (!authToken) {
            setCurrentLanguage(getAppLanguage());
            return;
        }

        try {
            const response = await getMyLanguage(authToken);
            if (response?.user_id) {
                localStorage.setItem("user_id", response.user_id);
            }
            if (response?.email) {
                localStorage.setItem("authEmail", response.email);
            }
            const backendLang = normalizeLanguage(response?.preferred_language);
            applyLanguage(backendLang);
        } catch (error) {
            console.error("Failed to sync language from backend", error);
            setCurrentLanguage(getAppLanguage());
        }
    }, [applyLanguage]);

    useEffect(() => {
        void syncLanguageFromBackend();

        const onLanguageChanged = () => {
            setCurrentLanguage(getAppLanguage());
        };

        const onAuthSessionChanged = () => {
            void syncLanguageFromBackend();
        };

        const onStorageChanged = (event: StorageEvent) => {
            if (event.key === "authEmail" || event.key === "authPhone" || event.key === "authRole" || event.key === "user_id") {
                void syncLanguageFromBackend();
            }
        };

        window.addEventListener(APP_LANGUAGE_EVENT, onLanguageChanged as EventListener);
        window.addEventListener("auth-session-changed", onAuthSessionChanged as EventListener);
        window.addEventListener("storage", onStorageChanged);
        return () => {
            window.removeEventListener(APP_LANGUAGE_EVENT, onLanguageChanged as EventListener);
            window.removeEventListener("auth-session-changed", onAuthSessionChanged as EventListener);
            window.removeEventListener("storage", onStorageChanged);
        };
    }, [syncLanguageFromBackend]);

    const value = useMemo(() => ({
        currentLanguage,
        changeLanguage: applyLanguage,
        syncLanguageFromBackend,
    }), [currentLanguage, applyLanguage, syncLanguageFromBackend]);

    return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage() {
    const context = useContext(LanguageContext);
    if (!context) {
        throw new Error("useLanguage must be used within a LanguageProvider");
    }
    return context;
}
