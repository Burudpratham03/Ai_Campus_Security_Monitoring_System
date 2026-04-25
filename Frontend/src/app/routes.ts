import { createBrowserRouter, redirect } from "react-router";
import { Dashboard } from "./components/Dashboard";
import { Reports } from "./components/Reports";
import { Settings } from "./components/Settings";
import { LandingPage } from "./components/LandingPage";
import { AdminLogin } from "./components/AdminLogin";
import { AdminSignup } from "./components/AdminSignup";
import { GuardLogin } from "./components/GuardLogin";
import { GuardStatus } from "./components/GuardStatus";
import { Login } from "./components/Login";
import { OTPVerification } from "./components/OTPVerification";
import { Signup } from "./components/Signup";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: LandingPage,
  },
  {
    path: "/auth/login",
    Component: Login,
  },
  {
    path: "/admin/login",
    Component: AdminLogin,
  },
  {
    path: "/admin/signup",
    Component: AdminSignup,
  },
  {
    path: "/guard/login",
    Component: GuardLogin,
  },
  {
    path: "/guard/status",
    Component: GuardStatus,
  },
  {
    path: "/auth/signup",
    Component: Signup,
  },
  {
    path: "/auth/verify",
    Component: OTPVerification,
  },
  {
    path: "/dashboard",
    loader: () => {
      const token = localStorage.getItem("authToken");
      const role = localStorage.getItem("authRole");
      if (!token) {
        throw redirect("/");
      }
      if (role !== "admin") {
        throw redirect(role === "guard" ? "/guard/status" : "/");
      }
      return null;
    },
    Component: Dashboard,
  },
  {
    path: "/admin/dashboard",
    loader: () => {
      const token = localStorage.getItem("authToken");
      const role = localStorage.getItem("authRole");
      if (!token) {
        throw redirect("/");
      }
      if (role !== "admin") {
        throw redirect(role === "guard" ? "/guard/status" : "/");
      }
      return null;
    },
    Component: Dashboard,
  },
  {
    path: "/reports",
    Component: Reports,
  },
  {
    path: "/settings",
    Component: Settings,
  },
]);