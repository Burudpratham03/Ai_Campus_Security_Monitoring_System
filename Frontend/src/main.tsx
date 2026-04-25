
import { createRoot } from "react-dom/client";
import App from "./app/App.tsx";
import "./styles/index.css";
import { AlertsProvider } from "./app/context/AlertsContext";
import { LanguageProvider } from "./app/context/LanguageContext";
import { Toaster } from "sonner";

createRoot(document.getElementById("root")!).render(
  <LanguageProvider>
    <AlertsProvider>
      <App />
      <Toaster position="top-right" richColors closeButton />
    </AlertsProvider>
  </LanguageProvider>
);
