import { Search, User, Wifi } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { APP_LANGUAGE_EVENT, getAppLanguage, normalizeLanguage, t } from "../utils/language";
import { SOSButton } from "./SOSButton";

interface HeaderProps {
  onSOSClick?: () => void;
}

export function Header({ onSOSClick }: HeaderProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const [language, setLanguage] = useState(getAppLanguage());
  const [query, setQuery] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(false);
  const searchWrapRef = useRef<HTMLDivElement | null>(null);

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

  const officerName = useMemo(() => {
    const name = localStorage.getItem("authName");
    if (!name) return t(language, "roleOfficer");
    return `${t(language, "roleOfficer")} ${name}`;
  }, [language]);

  const searchOptions = useMemo(() => {
    return [
      { label: t(language, "dashboard"), route: "/dashboard", tags: ["home", "overview", "alerts"] },
      { label: t(language, "reports"), route: "/reports", tags: ["analytics", "evidence", "history"] },
      { label: t(language, "settings"), route: "/settings", tags: ["maintenance", "configuration", "danger zone"] },
      { label: "Guard Status", route: "/guard/status", tags: ["guard", "duty", "status"] },
    ];
  }, [language]);

  const filteredOptions = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return searchOptions;
    return searchOptions.filter((opt) => {
      if (opt.label.toLowerCase().includes(q)) return true;
      return opt.tags.some((tag) => tag.includes(q));
    });
  }, [query, searchOptions]);

  useEffect(() => {
    const onClickOutside = (event: MouseEvent) => {
      if (!searchWrapRef.current) return;
      if (!searchWrapRef.current.contains(event.target as Node)) {
        setShowSuggestions(false);
      }
    };
    window.addEventListener("mousedown", onClickOutside);
    return () => window.removeEventListener("mousedown", onClickOutside);
  }, []);

  const executeSearch = (rawValue: string) => {
    const value = rawValue.trim();
    if (!value) return;

    const lower = value.toLowerCase();
    const exact = searchOptions.find((opt) => opt.label.toLowerCase() === lower);
    if (exact) {
      navigate(exact.route);
      setShowSuggestions(false);
      return;
    }

    const tagged = searchOptions.find(
      (opt) => opt.tags.some((tag) => tag.includes(lower)) || opt.label.toLowerCase().includes(lower)
    );
    if (tagged) {
      navigate(tagged.route);
      setShowSuggestions(false);
      return;
    }

    navigate(`/reports?q=${encodeURIComponent(value)}`);
    setShowSuggestions(false);
  };

  useEffect(() => {
    setShowSuggestions(false);
  }, [location.pathname]);

  return (
    <header className="relative z-[100] h-16 overflow-visible border-b border-border bg-card/88 px-6 py-3 backdrop-blur">
      <div className="flex h-full items-center justify-between overflow-visible">
        {/* Search Bar */}
        <div className="max-w-2xl flex-1 overflow-visible">
          <div ref={searchWrapRef} className="relative overflow-visible">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />
            <input
              type="text"
              placeholder={t(language, "searchPlaceholder")}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setShowSuggestions(true);
              }}
              onFocus={() => setShowSuggestions(true)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  executeSearch(query);
                }
                if (e.key === "Escape") {
                  setShowSuggestions(false);
                }
              }}
              className="app-input pl-10"
            />
            {showSuggestions && (
              <div className="absolute top-full z-[9999] mt-2 w-full rounded-xl border border-border bg-card p-2 shadow-[0px_10px_30px_rgba(0,0,0,0.1)]">
                {filteredOptions.slice(0, 5).map((opt) => (
                  <button
                    key={`${opt.route}:${opt.label}`}
                    type="button"
                    onClick={() => executeSearch(opt.label)}
                    className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm text-foreground transition-colors hover:bg-secondary"
                  >
                    <span>{opt.label}</span>
                    <span className="text-xs text-muted-foreground">{opt.route}</span>
                  </button>
                ))}
                {query.trim() && (
                  <button
                    type="button"
                    onClick={() => executeSearch(query)}
                    className="mt-1 flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm text-foreground transition-colors hover:bg-secondary"
                  >
                    <span>Search reports for "{query.trim()}"</span>
                    <span className="text-xs text-muted-foreground">Enter</span>
                  </button>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Right Controls */}
        <div className="flex items-center gap-4 ml-6">
          {/* Network Status */}
          <div className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2">
            <div className="w-2 h-2 bg-emerald-500 rounded-full app-alert-pulse"></div>
            <Wifi className="w-4 h-4 text-emerald-600" />
            <span className="text-sm font-medium text-emerald-700">{t(language, "online")}</span>
          </div>

          {/* User Profile */}
          <div className="flex items-center gap-3 rounded-xl px-2 py-1">
            <div className="text-right">
              <p className="text-sm font-medium text-foreground">{officerName}</p>
              <p className="text-xs text-muted-foreground">{t(language, "profileLocation")}</p>
            </div>
            <div className="w-10 h-10 bg-secondary rounded-full flex items-center justify-center">
              <User className="w-5 h-5 text-muted-foreground" />
            </div>
          </div>

          {/* SOS EMERGENCY BUTTON */}
          <SOSButton onTriggered={onSOSClick} />
        </div>
      </div>
    </header>
  );
}