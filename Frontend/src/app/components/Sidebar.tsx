import { Home, FileText, Settings, Shield } from "lucide-react";
import { Link, useLocation } from "react-router";
import ChatWidget from "./ChatWidget";
import { t } from "../utils/language";
import { useLanguage } from "../context/LanguageContext";

export function Sidebar() {
  const location = useLocation();
  const { currentLanguage: language } = useLanguage();

  const navItems = [
    { path: "/dashboard", label: t(language, "home"), icon: Home },
    { path: "/reports", label: t(language, "reports"), icon: FileText },
    { path: "/settings", label: t(language, "settings"), icon: Settings },
  ];

  return (
    <div className="w-72 bg-sidebar text-sidebar-foreground border-r border-sidebar-border flex flex-col h-screen overflow-hidden">
      {/* Logo */}
      <div className="p-6 border-b border-sidebar-border">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl flex items-center justify-center bg-primary text-primary-foreground shadow">
            <Shield className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="font-semibold text-lg">{t(language, "appTitle")}</h1>
            <p className="text-xs text-sidebar-foreground/70">{t(language, "appSubtitle")}</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="p-4 flex-shrink-0">
        <ul className="space-y-2">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = location.pathname === item.path;
            return (
              <li key={item.path}>
                <Link
                  to={item.path}
                  className={`flex items-center gap-3 px-4 py-3 rounded-xl transition-colors ${isActive
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground/80 hover:bg-sidebar-accent/65"
                    }`}
                >
                  <Icon className="w-5 h-5" />
                  <span className="font-medium">{item.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>

      </nav>

      {/* Chat zone takes remaining sidebar height */}
      <div className="min-h-0 flex-1 border-t border-sidebar-border p-3">
        {/* Chat widget sits at the bottom of the sidebar */}
        <ChatWidget />
      </div>
    </div>
  );
}