import { Shield, Mail, Lock, Phone } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { signup } from "../api/client";

export function Signup() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setLoading(true);
      await signup({
        full_name: fullName,
        email,
        phone_number: phone,
        password,
      });
      // Persist officer identity for dashboard display
      localStorage.setItem("authEmail", email);
      localStorage.setItem("authName", fullName);
      // On success, redirect to OTP verification with email in query
      navigate(`/auth/verify?email=${encodeURIComponent(email)}`);
    } catch (err) {
      console.error(err);
      const message = err instanceof Error ? err.message : "Signup failed. Please check your details and try again.";
      alert(message);
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
          <p className="text-gray-600">Create your security account</p>
        </div>

        {/* Signup Card */}
        <div className="app-surface rounded-2xl p-8">
          <h2 className="text-2xl font-semibold text-gray-900 mb-2">Sign Up</h2>
          <p className="text-gray-600 mb-6">Register to access the AI security dashboard</p>

          <form onSubmit={handleSubmit} className="space-y-5">
            {/* Name Field */}
            <div>
              <label htmlFor="fullName" className="block text-sm font-medium text-gray-700 mb-2">
                Full Name
              </label>
              <input
                id="fullName"
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Officer Name"
                required
                className="app-input"
              />
            </div>

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

            {/* Phone Field */}
            <div>
              <label htmlFor="phone" className="block text-sm font-medium text-gray-700 mb-2">
                Phone Number
              </label>
              <div className="relative">
                <Phone className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                <input
                  id="phone"
                  type="tel"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="+91-98******"
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

            {/* Signup Button */}
            <button
              type="submit"
              disabled={loading}
              className="app-btn-primary w-full py-3"
            >
              {loading ? "Creating Account..." : "Sign Up"}
            </button>
          </form>

          {/* Switch to Sign In */}
          <div className="mt-6 pt-6 border-t border-gray-200 text-center">
            <p className="text-sm text-gray-600">
              Already have an account?{" "}
              <button
                type="button"
                onClick={() => navigate("/auth/login")}
                className="text-primary hover:opacity-80 font-medium"
              >
                Sign In
              </button>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

