import { ArrowLeft, Lock, Mail, ShieldPlus, Smartphone, UserRound } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";

import { adminSignup, adminVerifyOtp } from "../api/client";

export function AdminSignup() {
    const navigate = useNavigate();
    const [firstName, setFirstName] = useState("");
    const [middleName, setMiddleName] = useState("");
    const [lastName, setLastName] = useState("");
    const [email, setEmail] = useState("");
    const [phoneNumber, setPhoneNumber] = useState("");
    const [password, setPassword] = useState("");
    const [otp, setOtp] = useState("");
    const [signupDone, setSignupDone] = useState(false);
    const [loading, setLoading] = useState(false);
    const [statusMessage, setStatusMessage] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    const handleSignup = async (event: React.FormEvent) => {
        event.preventDefault();
        setLoading(true);
        setError(null);
        setStatusMessage(null);

        const normalizedFirstName = firstName.trim().replace(/\s+/g, " ");
        const normalizedMiddleName = middleName.trim().replace(/\s+/g, " ");
        const normalizedLastName = lastName.trim().replace(/\s+/g, " ");
        const normalizedEmail = email.trim().toLowerCase();
        const normalizedPhone = phoneNumber.trim();

        try {
            const res = await adminSignup({
                first_name: normalizedFirstName,
                middle_name: normalizedMiddleName,
                last_name: normalizedLastName,
                email: normalizedEmail,
                phone_number: normalizedPhone,
                password,
            });
            setFirstName(normalizedFirstName);
            setMiddleName(normalizedMiddleName);
            setLastName(normalizedLastName);
            setEmail(normalizedEmail);
            setPhoneNumber(normalizedPhone);
            setSignupDone(true);
            setStatusMessage(res.message);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unable to create administrator account.");
        } finally {
            setLoading(false);
        }
    };

    const handleVerify = async (event: React.FormEvent) => {
        event.preventDefault();
        setLoading(true);
        setError(null);
        setStatusMessage(null);

        try {
            const res = await adminVerifyOtp(email, otp);
            localStorage.removeItem("authPhone");
            localStorage.removeItem("user_id");
            localStorage.setItem("authToken", res.access_token);
            localStorage.setItem("authEmail", email);
            localStorage.setItem("authRole", "admin");
            if (res.full_name) {
                localStorage.setItem("authName", res.full_name);
            } else {
                localStorage.setItem("authName", [firstName, middleName, lastName].filter(Boolean).join(" "));
            }
            window.dispatchEvent(new Event("auth-session-changed"));
            navigate("/admin/dashboard");
        } catch (err) {
            setError(err instanceof Error ? err.message : "OTP verification failed.");
        } finally {
            setLoading(false);
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

                    <div className="grid gap-10 md:grid-cols-2 md:items-start">
                        <div>
                            <div className="mb-5 inline-flex rounded-2xl bg-primary/10 p-4 text-primary">
                                <ShieldPlus className="h-8 w-8" />
                            </div>
                            <h1 className="text-3xl font-semibold text-foreground md:text-4xl">Administrator Signup</h1>
                            <p className="mt-4 text-muted-foreground">
                                Create an administrator account and verify it with the OTP sent to your email.
                            </p>
                        </div>

                        {!signupDone ? (
                            <form onSubmit={handleSignup} className="app-panel space-y-5">
                                <div>
                                    <label htmlFor="admin-first-name" className="mb-2 block text-sm font-medium text-foreground">First Name</label>
                                    <div className="relative">
                                        <UserRound className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground" />
                                        <input
                                            id="admin-first-name"
                                            value={firstName}
                                            onChange={(e) => setFirstName(e.target.value)}
                                            required
                                            className="app-input py-3 pl-10 pr-4"
                                            placeholder="First name"
                                        />
                                    </div>
                                </div>

                                <div>
                                    <label htmlFor="admin-middle-name" className="mb-2 block text-sm font-medium text-foreground">Middle Name</label>
                                    <div className="relative">
                                        <UserRound className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground" />
                                        <input
                                            id="admin-middle-name"
                                            value={middleName}
                                            onChange={(e) => setMiddleName(e.target.value)}
                                            className="app-input py-3 pl-10 pr-4"
                                            placeholder="Middle name (optional)"
                                        />
                                    </div>
                                </div>

                                <div>
                                    <label htmlFor="admin-last-name" className="mb-2 block text-sm font-medium text-foreground">Last Name</label>
                                    <div className="relative">
                                        <UserRound className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground" />
                                        <input
                                            id="admin-last-name"
                                            value={lastName}
                                            onChange={(e) => setLastName(e.target.value)}
                                            required
                                            className="app-input py-3 pl-10 pr-4"
                                            placeholder="Last name"
                                        />
                                    </div>
                                </div>

                                <div>
                                    <label htmlFor="admin-signup-email" className="mb-2 block text-sm font-medium text-foreground">Email Address</label>
                                    <div className="relative">
                                        <Mail className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground" />
                                        <input
                                            id="admin-signup-email"
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
                                    <label htmlFor="admin-signup-phone" className="mb-2 block text-sm font-medium text-foreground">Phone Number</label>
                                    <div className="relative">
                                        <Smartphone className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground" />
                                        <input
                                            id="admin-signup-phone"
                                            value={phoneNumber}
                                            onChange={(e) => setPhoneNumber(e.target.value)}
                                            required
                                            className="app-input py-3 pl-10 pr-4"
                                            placeholder="+91 98xxxxxx"
                                        />
                                    </div>
                                </div>

                                <div>
                                    <label htmlFor="admin-signup-password" className="mb-2 block text-sm font-medium text-foreground">Password</label>
                                    <div className="relative">
                                        <Lock className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground" />
                                        <input
                                            id="admin-signup-password"
                                            type="password"
                                            value={password}
                                            onChange={(e) => setPassword(e.target.value)}
                                            required
                                            className="app-input py-3 pl-10 pr-4"
                                            placeholder="Minimum 6 characters"
                                        />
                                    </div>
                                </div>

                                {error && <p className="rounded-lg border border-red-400/40 bg-red-500/10 px-3 py-2 text-sm text-red-700">{error}</p>}

                                <button
                                    type="submit"
                                    disabled={loading}
                                    className="app-btn-primary w-full py-3"
                                >
                                    {loading ? "Creating Account..." : "Create Admin Account"}
                                </button>
                            </form>
                        ) : (
                            <form onSubmit={handleVerify} className="app-panel space-y-5">
                                <p className="rounded-lg border border-primary/30 bg-primary/10 px-3 py-2 text-sm text-primary">
                                    {statusMessage || "OTP sent to your email."}
                                </p>

                                <div>
                                    <label htmlFor="admin-otp" className="mb-2 block text-sm font-medium text-foreground">Enter OTP</label>
                                    <input
                                        id="admin-otp"
                                        value={otp}
                                        onChange={(e) => setOtp(e.target.value)}
                                        required
                                        maxLength={6}
                                        className="app-input px-4 py-3 tracking-[0.35em]"
                                        placeholder="----"
                                    />
                                </div>

                                {error && <p className="rounded-lg border border-red-400/40 bg-red-500/10 px-3 py-2 text-sm text-red-700">{error}</p>}

                                <button
                                    type="submit"
                                    disabled={loading}
                                    className="app-btn-primary w-full py-3"
                                >
                                    {loading ? "Verifying OTP..." : "Verify OTP & Continue"}
                                </button>
                            </form>
                        )}
                    </div>

                    <div className="mt-8 border-t border-border pt-6 text-sm text-muted-foreground">
                        Already have an admin account?{" "}
                        <button type="button" onClick={() => navigate("/admin/login")} className="font-semibold text-primary hover:opacity-85">
                            Sign In
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
