import { AlertTriangle, CheckCircle2, ChevronDown, MessageSquare, Paperclip, SendHorizontal, Shield, X } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { askChat } from "../api/client";
import { APP_LANGUAGE_EVENT, getAppLanguage, normalizeLanguage, t } from "../utils/language";

type ChatMessage = {
    id: string;
    sender: "user" | "bot";
    text: string;
    timestamp: string;
    source?: "gemini" | "fallback";
    suggestions?: string[];
    latencyMs?: number;
};

const IMPORTANT_WORDS_REGEX = /(\b(?:critical|urgent|warning|risk|threat|alert|important|immediately|recommended|action required|next steps?|high|medium|low|blocked|failure|failed|error)\b|\b\d{1,3}%\b|\b\d+(?:\.\d+)?\s?(?:ms|sec|secs|seconds?|min|mins|minutes?|hr|hrs|hours?|days?)\b)/gi;

const parseBoldSegments = (value: string) => {
    const parts = value.split(/(\*\*[^*]+\*\*)/g);
    return parts.filter(Boolean).map((part) => ({
        text: part.replace(/^\*\*|\*\*$/g, ""),
        strong: /^\*\*[^*]+\*\*$/.test(part),
    }));
};

const highlightClassFor = (token: string) => {
    if (/\d{1,3}%/.test(token)) {
        return "bg-indigo-400/20 text-indigo-100 ring-1 ring-indigo-300/40";
    }
    if (/\d+(?:\.\d+)?\s?(?:ms|sec|secs|seconds?|min|mins|minutes?|hr|hrs|hours?|days?)/i.test(token)) {
        return "bg-sky-400/20 text-sky-100 ring-1 ring-sky-300/40";
    }
    if (/critical|urgent|warning|risk|threat|alert|error|failed|failure|blocked|immediately/i.test(token)) {
        return "bg-amber-400/25 text-amber-100 ring-1 ring-amber-300/50";
    }
    return "bg-emerald-400/20 text-emerald-100 ring-1 ring-emerald-300/40";
};

const isImportantToken = (token: string) =>
    /(\b(?:critical|urgent|warning|risk|threat|alert|important|immediately|recommended|action required|next steps?|high|medium|low|blocked|failure|failed|error)\b|\b\d{1,3}%\b|\b\d+(?:\.\d+)?\s?(?:ms|sec|secs|seconds?|min|mins|minutes?|hr|hrs|hours?|days?)\b)/i.test(token);

const formatTime = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
};

export function ChatWidget() {
    const [language, setLanguage] = useState(getAppLanguage());
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [input, setInput] = useState("");
    const [loading, setLoading] = useState(false);
    const [selectedImage, setSelectedImage] = useState<File | null>(null);
    const [selectedImagePreview, setSelectedImagePreview] = useState<string | null>(null);
    const [loadingPhraseIndex, setLoadingPhraseIndex] = useState(0);
    const [isNearBottom, setIsNearBottom] = useState(true);
    const scroller = useRef<HTMLDivElement | null>(null);
    const bottomAnchorRef = useRef<HTMLDivElement | null>(null);
    const fileInputRef = useRef<HTMLInputElement | null>(null);
    const textAreaRef = useRef<HTMLTextAreaElement | null>(null);

    const loadingPhrases = [
        t(language, "loadingSearch"),
        t(language, "loadingAnalyze"),
        t(language, "loadingFind"),
        t(language, "loadingLogs"),
    ];

    useEffect(() => {
        if (scroller.current) {
            scroller.current.scrollTop = scroller.current.scrollHeight;
        }
    }, [messages, loading]);

    useEffect(() => {
        if (!loading) {
            setLoadingPhraseIndex(0);
            return;
        }
        const interval = setInterval(() => {
            setLoadingPhraseIndex((i) => (i + 1) % loadingPhrases.length);
        }, 2000);
        return () => clearInterval(interval);
    }, [loading, loadingPhrases.length]);

    useEffect(() => {
        const onLanguageChanged = (event: Event) => {
            const custom = event as CustomEvent<{ language?: string }>;
            if (custom.detail?.language) {
                setLanguage(normalizeLanguage(custom.detail.language));
                return;
            }
            setLanguage(getAppLanguage());
        };
        window.addEventListener(APP_LANGUAGE_EVENT, onLanguageChanged as EventListener);
        return () => window.removeEventListener(APP_LANGUAGE_EVENT, onLanguageChanged as EventListener);
    }, []);

    useEffect(() => {
        if (!selectedImage) {
            setSelectedImagePreview(null);
            return;
        }
        const url = URL.createObjectURL(selectedImage);
        setSelectedImagePreview(url);
        return () => URL.revokeObjectURL(url);
    }, [selectedImage]);

    const scrollToBottom = (behavior: ScrollBehavior = "smooth") => {
        bottomAnchorRef.current?.scrollIntoView({ behavior, block: "end" });
    };

    const onScrollMessages = () => {
        if (!scroller.current) return;
        const { scrollTop, scrollHeight, clientHeight } = scroller.current;
        setIsNearBottom(scrollHeight - (scrollTop + clientHeight) < 32);
    };

    const isApprovalPrompt = (text: string) => {
        const normalized = (text || "").toLowerCase();
        return normalized.includes("should i send this to the active guards") || normalized.includes("(yes/no)") || normalized.includes("yes/no");
    };

    const renderInlineHighlights = (line: string) => {
        const boldSegments = parseBoldSegments(line);
        return boldSegments.map((segment, segIndex) => {
            if (segment.strong) {
                return (
                    <span
                        key={`strong-${segIndex}`}
                        className="rounded-md bg-amber-300/20 px-1 py-0.5 font-semibold text-amber-100 ring-1 ring-amber-300/40"
                    >
                        {segment.text}
                    </span>
                );
            }

            const pieces = segment.text.split(IMPORTANT_WORDS_REGEX);
            return pieces.map((piece, pieceIndex) => {
                if (!piece) return null;
                if (isImportantToken(piece)) {
                    return (
                        <span
                            key={`hl-${segIndex}-${pieceIndex}`}
                            className={`mx-0.5 rounded-md px-1 py-0.5 font-semibold ${highlightClassFor(piece)}`}
                        >
                            {piece}
                        </span>
                    );
                }
                return <span key={`txt-${segIndex}-${pieceIndex}`}>{piece}</span>;
            });
        });
    };

    const renderStructuredText = (text: string) => {
        const lines = String(text || "").split("\n");
        return (
            <div className="space-y-2">
                {lines.map((line, index) => {
                    const trimmed = line.trim();
                    if (!trimmed) {
                        return <div key={`gap-${index}`} className="h-1" />;
                    }

                    if (trimmed.startsWith("###")) {
                        return (
                            <p key={`h-${index}`} className="break-words whitespace-pre-wrap pt-1 text-sm font-semibold text-slate-50">
                                {renderInlineHighlights(trimmed.replace(/^###\s*/, ""))}
                            </p>
                        );
                    }

                    const keyValueMatch = trimmed.match(/^([^:]{2,40}):\s+(.+)$/);
                    if (keyValueMatch) {
                        return (
                            <div key={`kv-${index}`} className="rounded-lg border border-slate-700/80 bg-slate-900/70 px-3 py-2">
                                <p className="text-[11px] uppercase tracking-wide text-slate-400">{keyValueMatch[1]}</p>
                                <p className="mt-1 break-words whitespace-pre-wrap text-sm leading-relaxed text-slate-100">{renderInlineHighlights(keyValueMatch[2])}</p>
                            </div>
                        );
                    }

                    if (/^[-*]\s+/.test(trimmed)) {
                        const bulletText = trimmed.replace(/^[-*]\s+/, "");
                        const isWarning = /fail|error|urgent|critical|alert/i.test(bulletText);
                        return (
                            <div key={`b-${index}`} className="flex items-start gap-2 break-words whitespace-pre-wrap text-sm leading-relaxed text-slate-200">
                                {isWarning ? (
                                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-amber-300" />
                                ) : (
                                    <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-emerald-300" />
                                )}
                                <span>{renderInlineHighlights(bulletText)}</span>
                            </div>
                        );
                    }

                    return (
                        <p key={`p-${index}`} className="break-words whitespace-pre-wrap text-sm leading-relaxed text-slate-200">
                            {renderInlineHighlights(line)}
                        </p>
                    );
                })}
            </div>
        );
    };

    const send = async (forcedText?: string) => {
        const text = (forcedText ?? input).trim();
        if (!text && !selectedImage) return;

        const composedText = text || "Please analyze this image and explain why the event may not have been detected.";

        const nowIso = new Date().toISOString();
        const userMsg: ChatMessage = {
            id: String(Date.now()),
            sender: "user",
            text: selectedImage ? `${composedText}\n[Attached image: ${selectedImage.name}]` : composedText,
            timestamp: nowIso,
        };
        setMessages((s) => [...s, userMsg]);
        setInput("");
        setLoading(true);
        const startedAt = performance.now();

        try {
            const email = localStorage.getItem("authEmail") || undefined;
            const resp = await askChat(composedText, email, selectedImage, language);
            const botMsg: ChatMessage = {
                id: String(Date.now() + 1),
                sender: "bot",
                text: resp.response,
                timestamp: new Date().toISOString(),
                source: resp.source,
                suggestions: Array.isArray(resp.suggestions) ? resp.suggestions.slice(0, 6) : [],
                latencyMs: Math.round(performance.now() - startedAt),
            };
            setMessages((s) => [...s, botMsg]);
            setSelectedImage(null);
            if (fileInputRef.current) {
                fileInputRef.current.value = "";
            }
        } catch (err) {
            const errorText = err instanceof Error
                ? err.message
                : t(language, "serverUnavailable");
            setMessages((s) => [
                ...s,
                {
                    id: String(Date.now() + 2),
                    sender: "bot",
                    text: errorText,
                    timestamp: new Date().toISOString(),
                },
            ]);
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            send();
        }
    };

    return (
        <div className="h-full min-h-0 w-full overflow-hidden rounded-2xl border border-slate-700/70 bg-gradient-to-b from-slate-950 via-slate-950 to-slate-900 p-4 text-slate-100 shadow-[0_20px_60px_-35px_rgba(2,6,23,0.95)] flex flex-col">
            <div className="mb-3 flex items-center justify-between gap-2 border-b border-slate-800/90 pb-3">
                <div className="flex items-center gap-2">
                    <div className="rounded-xl bg-blue-900/40 p-2 text-blue-300 ring-1 ring-blue-500/30">
                        <MessageSquare className="h-4 w-4" />
                    </div>
                    <div>
                        <h3 className="text-sm font-semibold text-slate-100">{t(language, "guardAssistant")}</h3>
                        <p className="text-xs text-slate-400">{t(language, "commandCenter")}</p>
                    </div>
                </div>
                <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-300">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-300" />
                    Live
                </span>
            </div>

            <div ref={scroller} onScroll={onScrollMessages} className="chat-history-scroll relative mb-3 min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
                {messages.length === 0 && (
                    <div className="rounded-xl border border-dashed border-slate-700 bg-slate-900/80 p-4 text-sm leading-relaxed text-slate-400">
                        {t(language, "emptyChatHint")}
                    </div>
                )}

                {messages.map((m) => (
                    <div key={m.id} className={`flex animate-[chatFadeIn_220ms_ease-out] ${m.sender === "user" ? "justify-end" : "justify-start"}`}>
                        {m.sender === "bot" && (
                            <div className="mr-2 mt-1 rounded-full bg-slate-800 p-1.5 text-slate-300">
                                <Shield className="h-3.5 w-3.5" />
                            </div>
                        )}
                        <div className={`min-w-0 max-w-[92%] break-words whitespace-pre-wrap rounded-2xl p-3 text-sm leading-6 ${m.sender === "user"
                            ? "rounded-br-none bg-blue-600 text-white shadow-lg shadow-blue-900/30"
                            : "rounded-bl-none bg-gray-800 text-slate-100"
                            }`}>
                            {m.sender === "bot" ? renderStructuredText(m.text) : <p className="break-words whitespace-pre-wrap">{m.text}</p>}
                            {m.sender === "bot" && isApprovalPrompt(m.text) && (
                                <p className="mt-3 rounded-lg border border-slate-700/80 bg-slate-900/70 px-3 py-2 text-xs leading-relaxed text-slate-300">
                                    {t(language, "approveAndSend")} / {t(language, "cancelAction")} (Yes/No)
                                </p>
                            )}
                            <div className={`mt-1 flex items-center gap-2 text-[10px] ${m.sender === "user" ? "text-blue-100" : "text-slate-400"}`}>
                                <span>{formatTime(m.timestamp)}</span>
                                {m.sender === "bot" && typeof m.latencyMs === "number" && (
                                    <span>Reply in {Math.max(1, Math.round(m.latencyMs / 1000))}s</span>
                                )}
                                {m.sender === "bot" && m.source && (
                                    <span className="rounded-full border border-slate-600 px-1.5 py-0.5 uppercase tracking-wide text-[9px] text-slate-300">
                                        {m.source === "gemini" ? "AI" : "Ops"}
                                    </span>
                                )}
                            </div>
                        </div>
                    </div>
                ))}

                {loading && (
                    <div className="flex justify-start">
                        <div className="mr-2 mt-1 rounded-full bg-slate-800 p-1.5 text-slate-300">
                            <Shield className="h-3.5 w-3.5" />
                        </div>
                        <div className="rounded-2xl border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-slate-200">
                            <span className="inline-flex items-center gap-1.5">
                                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-sky-300" />
                                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-sky-300 [animation-delay:120ms]" />
                                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-sky-300 [animation-delay:240ms]" />
                                {loadingPhrases[loadingPhraseIndex]}
                            </span>
                        </div>
                    </div>
                )}

                {!isNearBottom && (
                    <button
                        type="button"
                        onClick={() => scrollToBottom()}
                        className="absolute bottom-2 right-2 rounded-full border border-slate-600 bg-slate-800 p-1.5 text-slate-200 shadow transition hover:bg-slate-700"
                        title={t(language, "scrollToBottom")}
                        aria-label={t(language, "scrollToBottom")}
                    >
                        <ChevronDown className="h-4 w-4" />
                    </button>
                )}

                <div ref={bottomAnchorRef} />
            </div>

            <div className="mt-auto border-t border-slate-800 pt-3">
                {selectedImage && (
                    <div className="mb-2 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-300 shrink-0">
                        <div className="flex items-center justify-between gap-2">
                            <span className="truncate">{t(language, "attachedPrefix")}: {selectedImage.name}</span>
                            <button
                                type="button"
                                className="ml-2 text-slate-400 hover:text-slate-200"
                                onClick={() => {
                                    setSelectedImage(null);
                                    if (fileInputRef.current) fileInputRef.current.value = "";
                                }}
                                title={t(language, "removeImage")}
                                aria-label={t(language, "removeImage")}
                            >
                                <X className="h-3.5 w-3.5" />
                            </button>
                        </div>
                        {selectedImagePreview && (
                            <img
                                src={selectedImagePreview}
                                alt="Selected upload preview"
                                className="mt-2 h-20 w-full rounded-md border border-slate-700 object-cover"
                            />
                        )}
                    </div>
                )}

                <div className="flex items-center gap-2">
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept="image/*"
                        title={t(language, "attachForAnalysis")}
                        aria-label={t(language, "attachForAnalysis")}
                        onChange={(e) => setSelectedImage(e.target.files?.[0] || null)}
                        className="hidden"
                    />
                    <button
                        type="button"
                        onClick={() => fileInputRef.current?.click()}
                        disabled={loading}
                        className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-200 transition hover:bg-slate-800 disabled:opacity-60"
                        title={t(language, "attachImage")}
                        aria-label={t(language, "attachImage")}
                    >
                        <Paperclip className="w-4 h-4" />
                    </button>

                    <textarea
                        ref={textAreaRef}
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={onKey}
                        rows={1}
                        placeholder={t(language, "askPlaceholder")}
                        className="h-10 flex-1 resize-none overflow-hidden rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500/40"
                    />
                    <button
                        onClick={() => send()}
                        disabled={loading || (!input.trim() && !selectedImage)}
                        className="rounded-md bg-blue-700 px-3 py-2 text-white transition hover:bg-blue-600 disabled:opacity-60"
                        title={t(language, "sendMessage")}
                        aria-label={t(language, "sendMessage")}
                    >
                        <SendHorizontal className="w-4 h-4" />
                    </button>
                </div>
                <p className="mt-1 text-[10px] text-slate-500">{t(language, "enterToSendHint")}</p>
            </div>

            <style>{`
                @keyframes chatFadeIn {
                    0% { opacity: 0; transform: translateY(6px); }
                    100% { opacity: 1; transform: translateY(0); }
                }

                .chat-history-scroll {
                    scrollbar-width: none;
                    -ms-overflow-style: none;
                }

                .chat-history-scroll::-webkit-scrollbar {
                    display: none;
                }
            `}</style>
        </div>
    );
}

export default ChatWidget;
