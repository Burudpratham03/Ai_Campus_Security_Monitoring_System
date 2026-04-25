import { Shield, Mail, Lock } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { login } from "../api/client";

export function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setLoading(true);

      const res: any = await login(email, password);

      if (res && res.status === "Login Successful") {
        // Store tokens under unified keys used elsewhere in the app
        if (res.user_id) localStorage.setItem("user_id", res.user_id);
        if (res.token) {
          localStorage.setItem("token", res.token);
          localStorage.setItem("authToken", res.token);
        }
        // persist email and name for UI
        if (email) localStorage.setItem("authEmail", email);
        if (res.name || res.full_name) localStorage.setItem("authName", res.name || res.full_name);
        window.dispatchEvent(new Event("auth-session-changed"));
        window.location.href = "/dashboard";
        return;
      }

      // On failure, show explicit alert so UI doesn't appear frozen
      window.alert("Invalid Credentials");
    } catch (err) {
      console.error(err);
      const message = err instanceof Error ? err.message : "Unable to sign in.";

      if (message.includes("Email not verified")) {
        window.alert("Your account is not verified yet. Enter the OTP sent to your email.");
        navigate(`/auth/verify?email=${encodeURIComponent(email)}`);
        return;
      }

      window.alert(message || "Invalid credentials");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app-page flex items-center justify-center p-6">
      <div className="w-full max-w-md">
        {/* Logo & Brand */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-primary rounded-2xl mb-4 shadow-lg">
            <Shield className="w-9 h-9 text-white" />
          </div>
          <h1 className="text-3xl font-bold text-gray-900 mb-2">Campus Guard AI</h1>
          <p className="text-gray-600">Security Operations Center</p>
        </div>

        {/* Login Card */}
        <div className="app-surface rounded-2xl p-8">
          <h2 className="text-2xl font-semibold text-gray-900 mb-2">Sign In</h2>
          <p className="text-gray-600 mb-6">Enter your credentials to access the dashboard</p>

          <form onSubmit={handleSubmit} className="space-y-5">
            {/* Email Field */}
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-2">
                Email Address
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="officer@campus.edu"
                  required
                  className="app-input pl-10"
                />
              </div>
            </div>

            {/* Password Field */}
            <div>
              <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-2">
                Password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                <input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  required
                  className="app-input pl-10"
                />
              </div>
            </div>

            {/* Remember Me & Forgot Password */}
            <div className="flex items-center justify-between">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  className="w-4 h-4 text-primary border-gray-300 rounded focus:ring-2 focus:ring-primary"
                />
                <span className="text-sm text-gray-600">Remember me</span>
              </label>
              <a href="#" className="text-sm text-primary hover:opacity-80 font-medium">
                Forgot password?
              </a>
            </div>

            {/* Login Button */}
            <button
              type="submit"
              disabled={loading}
              className="app-btn-primary w-full py-3"
            >
              {loading ? "Signing In..." : "Login"}
            </button>
          </form>

          {/* Help Text */}
          <div className="mt-6 pt-6 border-t border-gray-200 text-center">
            <p className="text-sm text-gray-600">
              Don&apos;t have an account?{" "}
              <button
                type="button"
                onClick={() => navigate("/auth/signup")}
                className="text-primary hover:opacity-80 font-medium"
              >
                Sign Up
              </button>
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="mt-6 text-center text-sm text-gray-500">
          <p>Campus Guard AI v2.0 • Secure Access Portal</p>
        </div>
      </div>
    </div>
  );
}
