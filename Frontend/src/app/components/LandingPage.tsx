import React from "react";
import {
    motion,
    useMotionValue,
    useSpring,
    useTransform,
    type Variants
} from "framer-motion";
import {
    ArrowRight,
    Camera,
    CheckCircle2,
    MessageSquare,
    Shield,
    Smartphone,
    Sparkles,
    Workflow,
} from "lucide-react";
import { useNavigate } from "react-router";

// --- 3D Hover Tilt Card Component ---
function TiltCard({ children, className }: { children: React.ReactNode; className?: string }) {
    const x = useMotionValue(0);
    const y = useMotionValue(0);

    // Apply spring physics for natural, fluid rotation (UI/UX Guideline §7)
    const mouseXSpring = useSpring(x, { stiffness: 150, damping: 20 });
    const mouseYSpring = useSpring(y, { stiffness: 150, damping: 20 });

    // Constrain rotation to 7 degrees to maintain professionalism and readability
    const rotateX = useTransform(mouseYSpring, [-0.5, 0.5], ["7deg", "-7deg"]);
    const rotateY = useTransform(mouseXSpring, [-0.5, 0.5], ["-7deg", "7deg"]);

    const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
        const rect = e.currentTarget.getBoundingClientRect();
        const width = rect.width;
        const height = rect.height;
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;

        // Calculate mouse position relative to the center of the card
        x.set(mouseX / width - 0.5);
        y.set(mouseY / height - 0.5);
    };

    const handleMouseLeave = () => {
        x.set(0);
        y.set(0);
    };

    return (
        <motion.div
            style={{ perspective: "1000px" }}
            className={className}
        >
            <motion.div
                onMouseMove={handleMouseMove}
                onMouseLeave={handleMouseLeave}
                style={{
                    rotateX,
                    rotateY,
                    transformStyle: "preserve-3d",
                }}
                className="h-full w-full"
            >
                {children}
            </motion.div>
        </motion.div>
    );
}
// -----------------------------------

const containerVariants: Variants = {
    hidden: { opacity: 0 },
    show: {
        opacity: 1,
        transition: {
            staggerChildren: 0.08,
            delayChildren: 0.06,
        },
    },
};

const itemVariants: Variants = {
    hidden: { opacity: 0, y: 14 },
    show: {
        opacity: 1,
        y: 0,
        transition: {
            duration: 0.4,
            ease: [0.16, 1, 0.3, 1],
        },
    },
};

const capabilities = [
    {
        title: "Real-Time Vision AI",
        body: "Continuous camera inference identifies weapons, fire, violence, and suspicious anomalies for immediate review.",
        icon: Camera,
        tone: "text-blue-700 bg-blue-50/80 border-blue-200/50 dark:bg-blue-900/20 dark:border-blue-800/50 dark:text-blue-400",
    },
    {
        title: "Gemini-Assisted Summaries",
        body: "Structured incident context and multilingual communication support for rapid, accurate response decisions.",
        icon: Sparkles,
        tone: "text-indigo-700 bg-indigo-50/80 border-indigo-200/50 dark:bg-indigo-900/20 dark:border-indigo-800/50 dark:text-indigo-400",
    },
    {
        title: "WAHA Guard Dispatch",
        body: "Administrator-confirmed alerts are delivered through WhatsApp with clear, actionable instructions.",
        icon: MessageSquare,
        tone: "text-emerald-700 bg-emerald-50/80 border-emerald-200/50 dark:bg-emerald-900/20 dark:border-emerald-800/50 dark:text-emerald-400",
    },
];

const flowSteps = [
    { title: "AI Detects Incident", subtitle: "Camera monitoring pipeline", icon: Camera },
    { title: "Administrator Validates", subtitle: "Human-in-the-loop confirmation", icon: Shield },
    { title: "Guards Receive Alert", subtitle: "Immediate field coordination", icon: Smartphone },
];

export function LandingPage() {
    const navigate = useNavigate();

    return (
        <div className="app-page min-h-screen px-4 py-8 text-foreground sm:px-6 lg:px-8 selection:bg-primary/20">
            <div className="mx-auto max-w-6xl">
                <motion.main
                    variants={containerVariants}
                    initial="hidden"
                    animate="show"
                    className="space-y-12 lg:space-y-16"
                >
                    {/* HERO SECTION */}
                    <motion.section variants={itemVariants} className="relative overflow-hidden rounded-[2rem] border border-border/60 bg-card/40 p-6 shadow-[0_8px_40px_-12px_rgba(0,0,0,0.1)] backdrop-blur-xl sm:p-10 lg:p-12">
                        {/* Ambient Tech Glows */}
                        <div className="pointer-events-none absolute -right-40 -top-40 h-96 w-96 rounded-full bg-emerald-500/10 blur-[100px]" />
                        <div className="pointer-events-none absolute -bottom-40 -left-40 h-96 w-96 rounded-full bg-blue-500/10 blur-[100px]" />

                        <div className="relative">
                            <div className="grid gap-10 lg:grid-cols-[1.5fr_1fr] lg:items-center">
                                <div>
                                    <h1 className="bg-gradient-to-b from-foreground to-foreground/70 bg-clip-text text-5xl font-bold tracking-tight text-transparent sm:text-6xl lg:text-7xl">
                                        Campus Guard AI
                                    </h1>
                                    <p className="mt-5 max-w-xl text-lg leading-relaxed text-muted-foreground sm:text-xl">
                                        Formal, reliable campus security operations with verified threat detection, administrator oversight, and rapid guard communication.
                                    </p>
                                </div>

                                {/* Standards Box */}
                                <div className="rounded-2xl border border-border/80 bg-background/60 p-6 backdrop-blur-sm">
                                    <p className="text-xs font-bold uppercase tracking-wider text-primary/80">Operational Standards</p>
                                    <ul className="mt-5 space-y-4 text-sm font-medium text-foreground/90">
                                        {[
                                            "24/7 monitoring across connected camera zones.",
                                            "Administrator confirmation before guard escalation.",
                                            "Multilingual incident messaging for field teams."
                                        ].map((item, i) => (
                                            <li key={i} className="flex items-start gap-3">
                                                <div className="mt-0.5 rounded-full bg-emerald-100 p-0.5 dark:bg-emerald-900/50">
                                                    <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
                                                </div>
                                                <span className="leading-snug">{item}</span>
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            </div>
                        </div>
                    </motion.section>

                    {/* Portals Section */}
                    <motion.section variants={itemVariants} className="grid gap-6 md:grid-cols-2">
                        <TiltCard className="h-full w-full">
                            <article className="group relative h-full overflow-hidden rounded-3xl border border-border/60 bg-card p-7 shadow-sm transition-colors duration-300 hover:border-blue-500/30 hover:shadow-[0_12px_40px_-16px_rgba(59,130,246,0.15)] sm:p-8">
                                <div className="pointer-events-none absolute -right-20 -top-20 h-40 w-40 rounded-full bg-blue-500/5 blur-[50px] transition-opacity group-hover:opacity-100" />
                                <div className="mb-5 inline-flex items-center gap-2 rounded-xl border border-blue-200/60 bg-blue-50/80 px-3 py-2 text-xs font-bold uppercase tracking-wider text-blue-700 dark:border-blue-800/50 dark:bg-blue-900/20 dark:text-blue-400">
                                    <Shield className="h-4 w-4" />
                                    Administrator Portal
                                </div>
                                <h2 className="text-2xl font-bold tracking-tight text-foreground" style={{ transform: "translateZ(30px)" }}>Enterprise Control Hub</h2>
                                <p className="mt-3 text-base leading-relaxed text-muted-foreground" style={{ transform: "translateZ(20px)" }}>
                                    Review incidents, validate threats, and coordinate campus response from a centralized control interface.
                                </p>
                                <div className="mt-8 flex flex-wrap gap-3" style={{ transform: "translateZ(40px)" }}>
                                    <button
                                        type="button"
                                        onClick={() => navigate("/admin/login")}
                                        className="app-btn-primary inline-flex min-h-[44px] items-center gap-2 rounded-lg px-5 py-2.5 font-medium focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
                                    >
                                        Login
                                        <ArrowRight className="h-4 w-4" />
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => navigate("/admin/signup")}
                                        className="app-btn-secondary min-h-[44px] rounded-lg px-5 py-2.5 font-medium focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                                    >
                                        Sign Up
                                    </button>
                                </div>
                            </article>
                        </TiltCard>

                        <TiltCard className="h-full w-full">
                            <article className="group relative h-full overflow-hidden rounded-3xl border border-border/60 bg-card p-7 shadow-sm transition-colors duration-300 hover:border-emerald-500/30 hover:shadow-[0_12px_40px_-16px_rgba(16,185,129,0.15)] sm:p-8">
                                <div className="pointer-events-none absolute -right-20 -top-20 h-40 w-40 rounded-full bg-emerald-500/5 blur-[50px] transition-opacity group-hover:opacity-100" />
                                <div className="mb-5 inline-flex items-center gap-2 rounded-xl border border-emerald-200/60 bg-emerald-50/80 px-3 py-2 text-xs font-bold uppercase tracking-wider text-emerald-700 dark:border-emerald-800/50 dark:bg-emerald-900/20 dark:text-emerald-400">
                                    <Smartphone className="h-4 w-4" />
                                    Security Personnel
                                </div>
                                <h2 className="text-2xl font-bold tracking-tight text-foreground" style={{ transform: "translateZ(30px)" }}>Field Response Access</h2>
                                <p className="mt-3 text-base leading-relaxed text-muted-foreground" style={{ transform: "translateZ(20px)" }}>
                                    Authenticate securely, receive verified alerts, and acknowledge assignments through streamlined guard workflows.
                                </p>
                                <div className="mt-8 flex flex-wrap gap-3" style={{ transform: "translateZ(40px)" }}>
                                    <button
                                        type="button"
                                        onClick={() => navigate("/guard/login?mode=signin")}
                                        className="app-btn-primary inline-flex min-h-[44px] items-center gap-2 rounded-lg px-5 py-2.5 font-medium focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
                                    >
                                        Login
                                        <ArrowRight className="h-4 w-4" />
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => navigate("/guard/login?mode=signup")}
                                        className="app-btn-secondary min-h-[44px] rounded-lg px-5 py-2.5 font-medium focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                                    >
                                        Sign Up
                                    </button>
                                </div>
                            </article>
                        </TiltCard>
                    </motion.section>

                    {/* Capabilities Section */}
                    <motion.section variants={itemVariants}>
                        <div className="mb-8 text-center sm:text-left">
                            <p className="text-xs font-bold uppercase tracking-widest text-primary/80">System Capabilities</p>
                            <h3 className="mt-2 text-3xl font-bold tracking-tight text-foreground sm:text-4xl">Core Intelligence Layer</h3>
                        </div>
                        <div className="grid gap-5 md:grid-cols-3">
                            {capabilities.map((capability) => {
                                const Icon = capability.icon;
                                return (
                                    <TiltCard key={capability.title} className="h-full">
                                        <article className="h-full rounded-2xl border border-border/50 bg-card/30 p-6 transition-colors hover:bg-card/60">
                                            <div className={`mb-4 inline-flex items-center justify-center rounded-xl p-3 ${capability.tone}`} style={{ transform: "translateZ(20px)" }}>
                                                <Icon className="h-6 w-6" />
                                            </div>
                                            <h4 className="text-lg font-semibold text-foreground" style={{ transform: "translateZ(30px)" }}>{capability.title}</h4>
                                            <p className="mt-2 text-sm leading-relaxed text-muted-foreground" style={{ transform: "translateZ(20px)" }}>{capability.body}</p>
                                        </article>
                                    </TiltCard>
                                );
                            })}
                        </div>
                    </motion.section>

                    {/* Operational Flow Section */}
                    <motion.section variants={itemVariants} className="rounded-3xl border border-border/60 bg-card/30 p-8 sm:p-10">
                        <div className="mb-10 text-center">
                            <p className="text-xs font-bold uppercase tracking-widest text-primary/80">Operational Flow</p>
                            <h3 className="mt-2 text-3xl font-bold tracking-tight text-foreground sm:text-4xl">Detection to Response</h3>
                        </div>

                        <div className="grid gap-6 md:grid-cols-3">
                            {flowSteps.map((step, index) => {
                                const Icon = step.icon;
                                return (
                                    <article key={step.title} className="relative rounded-2xl border border-border/60 bg-background p-6 shadow-sm">
                                        <div className="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
                                            <Icon className="h-6 w-6" />
                                        </div>
                                        <div className="mb-2 text-[10px] font-bold uppercase tracking-widest text-primary/60">Step 0{index + 1}</div>
                                        <h4 className="text-xl font-bold tracking-tight text-foreground">{step.title}</h4>
                                        <p className="mt-2 text-sm text-muted-foreground">{step.subtitle}</p>

                                        {/* Improved Connector Line */}
                                        {index < flowSteps.length - 1 && (
                                            <div className="pointer-events-none absolute right-[-24px] top-1/2 hidden w-12 -translate-y-1/2 items-center justify-center md:flex">
                                                <ArrowRight className="h-5 w-5 text-muted-foreground/30" />
                                            </div>
                                        )}
                                    </article>
                                );
                            })}
                        </div>

                        <div className="mt-10 flex justify-center">
                            <div className="inline-flex items-center gap-2 rounded-full border border-border/80 bg-background/80 px-4 py-2 text-xs font-bold uppercase tracking-wider text-muted-foreground shadow-sm backdrop-blur">
                                <Workflow className="h-4 w-4" />
                                Continuous monitoring and guard dispatch loop
                            </div>
                        </div>
                    </motion.section>
                </motion.main>

                <footer className="mt-16 border-t border-border/40 pb-8 pt-8 text-center text-xs font-semibold uppercase tracking-widest text-muted-foreground/60">
                    Campus Guard AI • Professional Security Operations Platform
                </footer>
            </div>
        </div>
    );
}