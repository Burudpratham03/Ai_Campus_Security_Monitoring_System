import { ArrowLeft, ShieldCheck, Smartphone } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { guardLoginStart, guardResendOtp, guardSignInStart, guardVerifyOtp } from "../api/client";

export function GuardLogin() {
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const initialMode = searchParams.get("mode") === "signup" ? "signup" : "signin";

    const [mode, setMode] = useState<"signin" | "signup">(initialMode);
    const [firstName, setFirstName] = useState("");
    const [middleName, setMiddleName] = useState("");
    const [lastName, setLastName] = useState("");
    const [phoneNumber, setPhoneNumber] = useState("");
    const [otp, setOtp] = useState("");
    const [otpRequested, setOtpRequested] = useState(false);
    const [otpHint, setOtpHint] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [resending, setResending] = useState(false);
    const autoSubmittedOtpRef = useRef<string | null>(null);

    const canRequestOtp = useMemo(() => {
        if (mode === "signin") {
            return Boolean(phoneNumber.trim());
        }
        return Boolean(firstName.trim() && lastName.trim() && phoneNumber.trim());
    }, [mode, firstName, lastName, phoneNumber]);

    const switchMode = (nextMode: "signin" | "signup") => {
        setMode(nextMode);
        setOtpRequested(false);
        setOtp("");
        setOtpHint(null);
        setError(null);
        autoSubmittedOtpRef.current = null;
    };

    const requestOtp = async () => {
        if (!canRequestOtp) {
            setError(mode === "signin"
                ? "Please provide Phone Number."
                : "Please provide First Name, Last Name, and Phone Number.");
            return;
        }

        const normalizedPhone = phoneNumber.trim();
        const normalizedFirst = firstName.trim().replace(/\s+/g, " ");
        const normalizedMiddle = middleName.trim().replace(/\s+/g, " ");
        const normalizedLast = lastName.trim().replace(/\s+/g, " ");

        setLoading(true);
        setError(null);

        try {
            const response = mode === "signin"
                ? await guardSignInStart({ phone_number: normalizedPhone })
                : await guardLoginStart({
                    first_name: normalizedFirst,
                    middle_name: normalizedMiddle,
                    last_name: normalizedLast,
                    phone_number: normalizedPhone,
                });
            setPhoneNumber(normalizedPhone);
            if (mode === "signup") {
                setFirstName(normalizedFirst);
                setMiddleName(normalizedMiddle);
                setLastName(normalizedLast);
            }
            setOtpRequested(true);
            setOtpHint(response.message);
            setOtp("");
            autoSubmittedOtpRef.current = null;
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to request OTP.");
        } finally {
            setLoading(false);
        }
    };

    const verifyGuardOtp = async () => {
        if (!otp.trim()) {
            setError("Please enter OTP.");
            return;
        }

        const normalizedPhone = phoneNumber.trim();

        setLoading(true);
        setError(null);

        try {
            const response = await guardVerifyOtp(normalizedPhone, otp.trim());
            localStorage.removeItem("authEmail");
            localStorage.removeItem("user_id");
            localStorage.setItem("authToken", response.access_token);
            localStorage.setItem("authRole", "guard");
            localStorage.setItem("authPhone", normalizedPhone);
            const fallbackName = [firstName, middleName, lastName].filter(Boolean).join(" ");
            const resolvedName = response.full_name || fallbackName || "Security Personnel";
            localStorage.setItem("authName", resolvedName);
            window.dispatchEvent(new Event("auth-session-changed"));
            navigate("/guard/status");
        } catch (err) {
            setError(err instanceof Error ? err.message : "OTP verification failed.");
        } finally {
            setLoading(false);
        }
    };

    const resendOtp = async () => {
        if (!phoneNumber.trim()) {
            setError("Phone number is required to resend OTP.");
            return;
        }

        const normalizedPhone = phoneNumber.trim();

        setResending(true);
        setError(null);
        try {
            const response = await guardResendOtp(normalizedPhone);
            setPhoneNumber(normalizedPhone);
            setOtpRequested(true);
            setOtpHint(response.message);
            setOtp("");
            autoSubmittedOtpRef.current = null;
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to resend OTP.");
        } finally {
            setResending(false);
        }
    };

    useEffect(() => {
        if (mode !== "signin") {
            return;
        }
        if (!otpRequested || loading) {
            return;
        }
        const normalizedOtp = otp.trim();
        if (normalizedOtp.length !== 6) {
            return;
        }
        if (!/^\d{6}$/.test(normalizedOtp)) {
            return;
        }
        if (autoSubmittedOtpRef.current === normalizedOtp) {
            return;
        }

        autoSubmittedOtpRef.current = normalizedOtp;
        void verifyGuardOtp();
    }, [mode, otpRequested, otp, loading]);

    return (
        <div className="app-page px-4 py-6 text-foreground sm:px-6">
            <div className="mx-auto w-full max-w-md app-auth-card p-5">
                <button
                    type="button"
                    onClick={() => navigate("/")}
                    className="mb-5 inline-flex items-center gap-2 text-sm font-semibold text-muted-foreground transition hover:text-foreground"
                >
                    <ArrowLeft className="h-4 w-4" />
                    ← Back to Home
                </button>

                <div className="app-panel mb-6 p-4">
                    <div className="mb-3 inline-flex rounded-xl bg-primary/10 p-3 text-primary">
                        <ShieldCheck className="h-7 w-7" />
                    </div>
                    <h1 className="text-2xl font-bold tracking-tight text-foreground">Security Personnel Access</h1>
                    <p className="mt-2 text-sm text-muted-foreground">Use phone and WhatsApp OTP to sign in. New guards can create access using Sign Up.</p>
                    <p className="mt-1 text-xs text-muted-foreground">Guards do not use password. Enter phone number, receive OTP, and access dashboard.</p>
                </div>

                <div className="mb-4 grid grid-cols-2 gap-2 rounded-2xl border border-border bg-secondary/40 p-2">
                    <button
                        type="button"
                        onClick={() => switchMode("signin")}
                        className={`rounded-xl px-3 py-2 text-sm font-semibold transition ${mode === "signin"
                            ? "bg-primary text-primary-foreground"
                            : "bg-card text-muted-foreground hover:bg-secondary"
                            }`}
                    >
                        Sign In
                    </button>
                    <button
                        type="button"
                        onClick={() => switchMode("signup")}
                        className={`rounded-xl px-3 py-2 text-sm font-semibold transition ${mode === "signup"
                            ? "bg-primary text-primary-foreground"
                            : "bg-card text-muted-foreground hover:bg-secondary"
                            }`}
                    >
                        Sign Up
                    </button>
                </div>

                <div className="space-y-4">
                    {mode === "signup" && (
                        <>
                            <div>
                                <label htmlFor="guard-first" className="mb-1 block text-sm font-semibold text-foreground">First Name</label>
                                <input
                                    id="guard-first"
                                    value={firstName}
                                    onChange={(e) => setFirstName(e.target.value)}
                                    className="app-input px-4 py-3 text-base"
                                    placeholder="First name"
                                />
                            </div>

                            <div>
                                <label htmlFor="guard-middle" className="mb-1 block text-sm font-semibold text-foreground">Middle Name</label>
                                <input
                                    id="guard-middle"
                                    value={middleName}
                                    onChange={(e) => setMiddleName(e.target.value)}
                                    className="app-input px-4 py-3 text-base"
                                    placeholder="Middle name"
                                />
                            </div>

                            <div>
                                <label htmlFor="guard-last" className="mb-1 block text-sm font-semibold text-foreground">Last Name</label>
                                <input
                                    id="guard-last"
                                    value={lastName}
                                    onChange={(e) => setLastName(e.target.value)}
                                    className="app-input px-4 py-3 text-base"
                                    placeholder="Last name"
                                />
                            </div>
                        </>
                    )}

                    <div>
                        <label htmlFor="guard-phone" className="mb-1 block text-sm font-semibold text-foreground">Phone Number</label>
                        <div className="relative">
                            <Smartphone className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground" />
                            <input
                                id="guard-phone"
                                value={phoneNumber}
                                onChange={(e) => setPhoneNumber(e.target.value)}
                                className="app-input py-3 pl-10 pr-4 text-base"
                                placeholder="+91 98xxxxxx"
                            />
                        </div>
                    </div>

                    <button
                        type="button"
                        onClick={requestOtp}
                        disabled={loading || !canRequestOtp}
                        className="app-btn-primary w-full py-3 text-sm font-bold"
                    >
                        {loading
                            ? "Sending OTP to WhatsApp..."
                            : mode === "signin"
                                ? "Sign In"
                                : "Create Account & Send OTP"}
                    </button>

                    <div>
                        <label htmlFor="guard-otp" className="mb-1 block text-sm font-semibold text-foreground">OTP</label>
                        <input
                            id="guard-otp"
                            value={otp}
                            onChange={(e) => setOtp(e.target.value)}
                            className="app-input px-4 py-3 text-base tracking-[0.4em]"
                            placeholder="----"
                            inputMode="numeric"
                            maxLength={6}
                        />
                    </div>

                    {otpHint && <p className="rounded-lg border border-emerald-300/40 bg-emerald-400/10 px-3 py-2 text-sm text-emerald-700">{otpHint}</p>}
                    {error && <p className="rounded-lg border border-red-300/50 bg-red-400/10 px-3 py-2 text-sm text-red-700">{error}</p>}

                    <button
                        type="button"
                        onClick={verifyGuardOtp}
                        disabled={loading || !otpRequested}
                        className="app-btn-secondary w-full py-3 text-sm font-bold"
                    >
                        {loading ? "Verifying..." : "Verify OTP"}
                    </button>

                    <button
                        type="button"
                        onClick={resendOtp}
                        disabled={resending || !phoneNumber.trim()}
                        className="app-btn-secondary w-full py-3 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
                    >
                        {resending ? "Resending..." : "Resend OTP"}
                    </button>
                </div>
            </div>
        </div>
    );
}
