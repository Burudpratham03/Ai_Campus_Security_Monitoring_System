import { ArrowLeft, Lock, Mail, Shield } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";

import { adminForgotPassword, adminLogin } from "../api/client";

export function AdminLogin() {
    const navigate = useNavigate();
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [resetLoading, setResetLoading] = useState(false);
    const [resetMessage, setResetMessage] = useState<string | null>(null);

    const handleSubmit = async (event: React.FormEvent) => {
        event.preventDefault();
        setLoading(true);
        setError(null);

        try {
            const res = await adminLogin({ email, password });
            localStorage.removeItem("authPhone");
            localStorage.removeItem("user_id");
            localStorage.setItem("authToken", res.access_token);
            localStorage.setItem("authEmail", email);
            localStorage.setItem("authRole", "admin");
            if (res.full_name) {
                localStorage.setItem("authName", res.full_name);
            }
            window.dispatchEvent(new Event("auth-session-changed"));
            navigate("/admin/dashboard");
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unable to sign in.");
        } finally {
            setLoading(false);
        }
    };

    const handleForgotPassword = async () => {
        if (!email.trim()) {
            setError("Please enter your registered email first.");
            return;
        }
        setResetLoading(true);
        setError(null);
        setResetMessage(null);
        try {
            const res = await adminForgotPassword(email.trim());
            setResetMessage(res.message || "Temporary password sent to your registered email.");
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unable to send temporary password.");
        } finally {
            setResetLoading(false);
        }
    };

    return (
        <div className="app-page text-foreground">
            <div className="app-auth-shell flex min-h-screen items-center">
                <div className="app-auth-card">
                    <button
                        type="button"
                        onClick={() => navigate("/")}
                        className="mb-8 inline-flex items-center gap-2 text-sm font-medium text-muted-foreground transition hover:text-foreground"
                    >
                        <ArrowLeft className="h-4 w-4" />
                        ← Back to Home
                    </button>

                    <div className="grid gap-10 md:grid-cols-2 md:items-center">
                        <div>
                            <div className="mb-5 inline-flex rounded-2xl bg-primary/10 p-4 text-primary">
                                <Shield className="h-8 w-8" />
                            </div>
                            <h1 className="text-3xl font-semibold text-foreground md:text-4xl">Administrator Portal</h1>
                            <p className="mt-4 text-muted-foreground">
                                Desktop-first secure access for system administrators. Authenticate with your registered email and password.
                            </p>
                        </div>

                        <form onSubmit={handleSubmit} className="app-panel space-y-5">
                            <div>
                                <label htmlFor="admin-email" className="mb-2 block text-sm font-medium text-foreground">
                                    Email Address
                                </label>
                                <div className="relative">
                                    <Mail className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground" />
                                    <input
                                        id="admin-email"
                                        type="email"
                                        value={email}
                                        onChange={(e) => setEmail(e.target.value)}
                                        required
                                        className="app-input py-3 pl-10 pr-4"
                                        placeholder="admin@campus.edu"
                                    />
                                </div>
                            </div>

                            <div>
                                <label htmlFor="admin-password" className="mb-2 block text-sm font-medium text-foreground">
                                    Password
                                </label>
                                <div className="relative">
                                    <Lock className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground" />
                                    <input
                                        id="admin-password"
                                        type="password"
                                        value={password}
                                        onChange={(e) => setPassword(e.target.value)}
                                        required
                                        className="app-input py-3 pl-10 pr-4"
                                        placeholder="Enter password"
                                    />
                                </div>
                                <div className="mt-2 text-right">
                                    <button
                                        type="button"
                                        onClick={handleForgotPassword}
                                        disabled={resetLoading}
                                        className="text-xs font-semibold text-primary hover:opacity-85"
                                    >
                                        {resetLoading ? "Sending..." : "Forgot password?"}
                                    </button>
                                </div>
                            </div>

                            {resetMessage && <p className="rounded-lg border border-emerald-400/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-700">{resetMessage}</p>}
                            {error && <p className="rounded-lg border border-red-400/40 bg-red-500/10 px-3 py-2 text-sm text-red-700">{error}</p>}

                            <button
                                type="submit"
                                disabled={loading}
                                className="app-btn-primary w-full py-3"
                            >
                                {loading ? "Signing In..." : "Sign In as Administrator"}
                            </button>

                            <p className="text-center text-sm text-muted-foreground">
                                New administrator?{" "}
                                <button
                                    type="button"
                                    onClick={() => navigate("/admin/signup")}
                                    className="font-semibold text-primary hover:opacity-85"
                                >
                                    Create account with OTP
                                </button>
                            </p>
                        </form>
                    </div>
                </div>
            </div>
        </div>
    );
}
