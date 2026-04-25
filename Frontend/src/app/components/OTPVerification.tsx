import { Shield, ArrowLeft, CheckCircle, MailOpen, RefreshCw } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { requestOtp, verifyOtp } from "../api/client";

export function OTPVerification() {
    const [otp, setOtp] = useState(["", "", "", ""]);
    const inputRefs = [
        useRef<HTMLInputElement>(null),
        useRef<HTMLInputElement>(null),
        useRef<HTMLInputElement>(null),
        useRef<HTMLInputElement>(null),
    ];
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [resendCountdown, setResendCountdown] = useState(0);
    const [showPasteHint, setShowPasteHint] = useState(false);
    const [showSuccess, setShowSuccess] = useState(false);
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();

    const maskedEmail = (() => {
        const email = searchParams.get("email");
        if (!email) return "your registered email";
        const parts = email.split("@");
        const name = parts[0] || "";
        const domain = parts[1] || "";
        const visible = `${name.slice(0, 2)}***`;
        return `${visible}@${domain}`;
    })();

    useEffect(() => {
        inputRefs[0].current?.focus();
    }, []);

    useEffect(() => {
        let timer: ReturnType<typeof setTimeout> | null = null;
        if (resendCountdown > 0) {
            timer = setTimeout(() => setResendCountdown((c) => c - 1), 1000);
        }
        return () => {
            if (timer !== null) {
                clearTimeout(timer);
            }
        };
    }, [resendCountdown]);

    const handleChange = (index: number, value: string) => {
        if (value.length > 1) return;
        if (value && !/^\d+$/.test(value)) return;

        const newOtp = [...otp];
        newOtp[index] = value;
        setOtp(newOtp);
        setNotice(null);

        if (value && index < 3) {
            inputRefs[index + 1].current?.focus();
        }

        if (index === 3 && value !== "") {
            const completedOtp = [...newOtp];
            if (completedOtp.every((digit) => digit !== "")) {
                setTimeout(() => {
                    verifyOtpHandler(completedOtp);
                }, 300);
            }
        }
    };

    const handleKeyDown = (index: number, e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === "Backspace" && !otp[index] && index > 0) {
            inputRefs[index - 1].current?.focus();
        }
    };

    const handlePaste = (e: React.ClipboardEvent) => {
        e.preventDefault();
        const pastedData = e.clipboardData.getData("text").slice(0, 4);
        if (!/^\d+$/.test(pastedData)) return;

        const newOtp = pastedData.split("");
        setOtp([...newOtp, "", "", ""].slice(0, 4));
        setNotice(null);

        if (pastedData.length === 4) {
            setTimeout(() => {
                verifyOtpHandler([...newOtp.slice(0, 4)]);
            }, 300);
        } else {
            const lastIndex = Math.min(pastedData.length, 3);
            inputRefs[lastIndex].current?.focus();
        }
    };

    const verifyOtpHandler = async (otpArray?: string[]) => {
        const otpToUse = otpArray || otp;
        setError(null);
        setNotice(null);

        if (!otpToUse.every((digit) => digit !== "")) {
            setError("Please enter the 4-digit code.");
            return;
        }

        const email = searchParams.get("email");
        if (!email) {
            setError("Missing email from login step. Please login again.");
            navigate("/auth/login");
            return;
        }

        try {
            setLoading(true);
            const code = otpToUse.join("");
            const token = await verifyOtp(email, code);
            localStorage.setItem("authToken", token.access_token);
            if (token.email) localStorage.setItem("authEmail", token.email);
            if (token.full_name) localStorage.setItem("authName", token.full_name);
            window.dispatchEvent(new Event("auth-session-changed"));

            setShowSuccess(true);
            setTimeout(() => {
                navigate("/dashboard");
            }, 1400);
        } catch (err) {
            console.error(err);
            setError("Invalid verification code. Please try again.");
            setOtp(["", "", "", ""]);
            inputRefs[0].current?.focus();
            setShowPasteHint(true);
            setTimeout(() => setShowPasteHint(false), 600);
        } finally {
            setLoading(false);
        }
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        verifyOtpHandler();
    };

    const handleResendCode = async () => {
        const email = searchParams.get("email");
        if (!email) {
            setError("Missing email. Please sign up or log in again.");
            return;
        }

        setOtp(["", "", "", ""]);
        inputRefs[0].current?.focus();
        setError(null);
        setNotice(null);

        try {
            setLoading(true);
            await requestOtp(email);
            setResendCountdown(30);
            setNotice("A new verification code has been sent to your mailbox.");
        } catch (err) {
            console.error(err);
            setError(err instanceof Error ? err.message : "Failed to resend verification code.");
        } finally {
            setLoading(false);
        }
    };

    if (showSuccess) {
        return (
            <div className="app-page flex items-center justify-center p-6">
                <div className="w-full max-w-md text-center">
                    <div className="mb-6">
                        <CheckCircle className="w-20 h-20 text-green-500 mx-auto" />
                    </div>
                    <h2 className="text-3xl font-bold text-gray-900 mb-2">Verified</h2>
                    <p className="text-gray-600 mb-6">Identity confirmed. Redirecting to the dashboard.</p>
                    <div className="app-surface rounded-2xl p-8">
                        <p className="text-gray-600">Please wait...</p>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="app-page flex items-center justify-center p-6">
            <div className="w-full max-w-md">
                <div className="text-center mb-8">
                    <div className="inline-flex items-center justify-center w-16 h-16 bg-primary rounded-2xl mb-4 shadow-lg">
                        <Shield className="w-9 h-9 text-white" />
                    </div>
                    <h1 className="text-3xl font-bold text-gray-900 mb-2">Campus Guard AI</h1>
                    <p className="text-gray-600">Security Operations Center</p>
                </div>

                <div className="app-surface rounded-2xl p-8">
                    <button
                        onClick={() => navigate("/auth/login")}
                        className="flex items-center gap-2 text-gray-600 hover:text-gray-900 mb-6 transition-colors"
                    >
                        <ArrowLeft className="w-4 h-4" />
                        <span className="text-sm">Back to Login</span>
                    </button>

                    <h2 className="text-2xl font-semibold text-gray-900 mb-2">Email Verification</h2>
                    <div className="mb-6 rounded-xl border border-border bg-secondary/35 p-4 text-left">
                        <div className="flex items-start gap-3">
                            <div className="mt-0.5 rounded-lg bg-white p-2 text-primary">
                                <MailOpen className="h-4 w-4" />
                            </div>
                            <div>
                                <p className="text-sm font-semibold text-gray-900">Check your inbox</p>
                                <p className="mt-1 text-sm text-gray-600">
                                    A 4-digit verification code was sent to <span className="font-semibold text-gray-900">{maskedEmail}</span>.
                                </p>
                                <p className="mt-1 text-xs text-gray-500">If it does not appear, check spam or promotions.</p>
                            </div>
                        </div>
                    </div>

                    <form onSubmit={handleSubmit} className="space-y-6">
                        <div className="flex gap-4 justify-center">
                            {otp.map((digit, index) => (
                                <input
                                    key={index}
                                    ref={inputRefs[index]}
                                    type="text"
                                    inputMode="numeric"
                                    maxLength={1}
                                    value={digit}
                                    onFocus={() => setShowPasteHint(true)}
                                    onBlur={() => setShowPasteHint(false)}
                                    onChange={(e) => handleChange(index, e.target.value)}
                                    onKeyDown={(e) => handleKeyDown(index, e)}
                                    onPaste={index === 0 ? handlePaste : undefined}
                                    aria-label={`Digit ${index + 1}`}
                                    className={`h-16 w-16 text-center text-3xl font-bold border-2 rounded-xl transition-all focus:outline-none focus:ring-2 focus:ring-offset-2 ${digit
                                        ? "border-primary bg-blue-50 focus:ring-primary"
                                        : "border-gray-300 bg-white focus:ring-primary"
                                        } ${showPasteHint ? "ring-1 ring-primary/30" : ""}`}
                                />
                            ))}
                        </div>

                        <div className="rounded-lg border border-blue-200 bg-blue-50 py-3 px-4 text-center">
                            <p className="text-sm text-blue-700">
                                Entered code: <strong>{otp.join("") || "____"}</strong>
                            </p>
                        </div>

                        <div className="mt-3 text-center min-h-[1.25rem]">
                            {error ? (
                                <p className="text-sm text-red-600">{error}</p>
                            ) : notice ? (
                                <p className="text-sm text-emerald-700">{notice}</p>
                            ) : showPasteHint ? (
                                <p className="text-sm text-gray-500">You can paste the full 4-digit code in the first box.</p>
                            ) : (
                                <p className="text-sm text-gray-500">Please enter the verification code to continue.</p>
                            )}
                        </div>

                        <div className="flex gap-2">
                            <button
                                type="submit"
                                disabled={!otp.every((digit) => digit !== "") || loading}
                                className="app-btn-primary w-full py-3 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-3"
                            >
                                {loading ? (
                                    <svg
                                        className="animate-spin h-5 w-5 text-white"
                                        xmlns="http://www.w3.org/2000/svg"
                                        fill="none"
                                        viewBox="0 0 24 24"
                                    >
                                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"></path>
                                    </svg>
                                ) : null}
                                {loading ? "Verifying..." : "Verify"}
                            </button>

                            <button
                                type="button"
                                onClick={handleResendCode}
                                disabled={loading || resendCountdown > 0}
                                className="app-btn-secondary min-w-[132px]"
                            >
                                {resendCountdown > 0 ? (
                                    `Resend ${resendCountdown}s`
                                ) : (
                                    <span className="inline-flex items-center gap-2">
                                        <RefreshCw className="h-4 w-4" />
                                        Resend
                                    </span>
                                )}
                            </button>
                        </div>
                    </form>

                    <div className="mt-6 border-t border-gray-200 pt-4 text-center">
                        <p className="text-xs text-gray-500">Verification expires shortly for security reasons.</p>
                    </div>
                </div>

                <div className="mt-6 text-center text-sm text-gray-500">
                    <p>Campus Guard AI v2.0 • Secure Access Portal</p>
                </div>
            </div>
        </div>
    );
}
