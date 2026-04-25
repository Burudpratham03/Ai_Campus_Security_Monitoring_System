/**
 * Sound notification system using Web Audio API
 * Generates different alert sounds for different threat types
 */

const API_BASE = "http://127.0.0.1:8000";
const ALERT_AUDIO_BASE = `${API_BASE}/alert-audio`;

const CUSTOM_ALERT_AUDIO: Record<"fire" | "violence" | "suspicious", string> = {
    fire: `${ALERT_AUDIO_BASE}/maka-bhosda-aag-meme-amitabh-bachan-made-with-Voicemod.mp3`,
    violence: `${ALERT_AUDIO_BASE}/oh_my_god_vine.mp3`,
    suspicious: `${ALERT_AUDIO_BASE}/matlab-wo-alag-hi-level-ka-banda-tha.mp3`,
};

let audioContext: AudioContext | null = null;
let activeAudio: HTMLAudioElement | null = null;

const stopActiveAudio = () => {
    if (!activeAudio) {
        return;
    }
    try {
        activeAudio.pause();
        activeAudio.currentTime = 0;
    } catch {
        // Ignore playback teardown issues.
    }
    activeAudio = null;
};

const playCustomAudioByUrl = async (url: string): Promise<boolean> => {
    try {
        stopActiveAudio();
        const audio = new Audio(url);
        audio.preload = "auto";
        activeAudio = audio;
        await audio.play();
        return true;
    } catch (error) {
        console.error("Failed to play custom alert audio:", error);
        return false;
    }
};

const getAlertAudioByThreatType = (threatType: string): string | null => {
    const type = String(threatType || "").toLowerCase();

    if (type.includes("fire")) {
        return CUSTOM_ALERT_AUDIO.fire;
    }

    if (
        type.includes("violence") ||
        type.includes("violent") ||
        type.includes("fight") ||
        type.includes("fighting")
    ) {
        return CUSTOM_ALERT_AUDIO.violence;
    }

    if (
        type.includes("suspicious") ||
        type.includes("anomaly") ||
        type.includes("mask")
    ) {
        return CUSTOM_ALERT_AUDIO.suspicious;
    }

    return null;
};

const getAudioContext = (): AudioContext => {
    if (!audioContext) {
        audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
    }
    return audioContext;
};

const ensureAudioReady = () => {
    const ctx = getAudioContext();
    if (ctx.state === "suspended") {
        void ctx.resume().catch(() => {
            // Browser autoplay policies can still block audio until a gesture.
        });
    }
    return ctx;
};

/**
 * Play a weapon alert sound - high frequency rapid beeps with urgency
 */
export const playWeaponAlert = () => {
    try {
        const ctx = ensureAudioReady();
        const now = ctx.currentTime;

        // Create oscillator for high-frequency alert
        const oscillator = ctx.createOscillator();
        const gainNode = ctx.createGain();

        oscillator.connect(gainNode);
        gainNode.connect(ctx.destination);

        oscillator.frequency.value = 1200; // High frequency (1200 Hz)
        oscillator.type = "sine";

        // Rapid pulses for weapon alert
        gainNode.gain.setValueAtTime(0.4, now);
        gainNode.gain.linearRampToValueAtTime(0, now + 0.1);

        oscillator.start(now);
        oscillator.stop(now + 0.1);

        // Second pulse after 50ms
        const osc2 = ctx.createOscillator();
        const gain2 = ctx.createGain();
        osc2.connect(gain2);
        gain2.connect(ctx.destination);
        osc2.frequency.value = 1200;
        osc2.type = "sine";

        gain2.gain.setValueAtTime(0.4, now + 0.15);
        gain2.gain.linearRampToValueAtTime(0, now + 0.25);

        osc2.start(now + 0.15);
        osc2.stop(now + 0.25);

        // Third pulse - longer to indicate severity
        const osc3 = ctx.createOscillator();
        const gain3 = ctx.createGain();
        osc3.connect(gain3);
        gain3.connect(ctx.destination);
        osc3.frequency.value = 1300;
        osc3.type = "sine";

        gain3.gain.setValueAtTime(0.4, now + 0.3);
        gain3.gain.linearRampToValueAtTime(0, now + 0.5);

        osc3.start(now + 0.3);
        osc3.stop(now + 0.5);
    } catch (error) {
        console.error("Failed to play weapon alert sound:", error);
    }
};

/**
 * Play a violence alert sound - medium frequency with varying pulses
 */
export const playViolenceAlert = () => {
    try {
        const ctx = ensureAudioReady();
        const now = ctx.currentTime;

        const oscillator = ctx.createOscillator();
        const gainNode = ctx.createGain();

        oscillator.connect(gainNode);
        gainNode.connect(ctx.destination);

        oscillator.frequency.value = 900; // Medium-high frequency (900 Hz)
        oscillator.type = "sine";

        // Two main pulses for violence alert
        gainNode.gain.setValueAtTime(0.3, now);
        gainNode.gain.linearRampToValueAtTime(0, now + 0.15);

        oscillator.start(now);
        oscillator.stop(now + 0.15);

        // Second pulse
        const osc2 = ctx.createOscillator();
        const gain2 = ctx.createGain();
        osc2.connect(gain2);
        gain2.connect(ctx.destination);
        osc2.frequency.value = 850;
        osc2.type = "sine";

        gain2.gain.setValueAtTime(0.3, now + 0.25);
        gain2.gain.linearRampToValueAtTime(0, now + 0.4);

        osc2.start(now + 0.25);
        osc2.stop(now + 0.4);
    } catch (error) {
        console.error("Failed to play violence alert sound:", error);
    }
};

/**
 * Play a fire alert sound - lower frequency with sustained tone
 */
export const playFireAlert = () => {
    try {
        const ctx = ensureAudioReady();
        const now = ctx.currentTime;

        const oscillator = ctx.createOscillator();
        const gainNode = ctx.createGain();

        oscillator.connect(gainNode);
        gainNode.connect(ctx.destination);

        oscillator.frequency.value = 700; // Lower frequency (700 Hz)
        oscillator.type = "sine";

        // Sustained tone for fire alert
        gainNode.gain.setValueAtTime(0.3, now);
        gainNode.gain.linearRampToValueAtTime(0, now + 0.5);

        oscillator.start(now);
        oscillator.stop(now + 0.5);
    } catch (error) {
        console.error("Failed to play fire alert sound:", error);
    }
};

/**
 * Play a general notification sound
 */
export const playNotification = () => {
    try {
        const ctx = ensureAudioReady();
        const now = ctx.currentTime;

        const oscillator = ctx.createOscillator();
        const gainNode = ctx.createGain();

        oscillator.connect(gainNode);
        gainNode.connect(ctx.destination);

        oscillator.frequency.value = 600; // Medium frequency
        oscillator.type = "sine";

        gainNode.gain.setValueAtTime(0.2, now);
        gainNode.gain.linearRampToValueAtTime(0, now + 0.2);

        oscillator.start(now);
        oscillator.stop(now + 0.2);
    } catch (error) {
        console.error("Failed to play notification sound:", error);
    }
};

/**
 * Play alert sound based on threat type
 */
export const playAlertSound = (threatType: string) => {
    const type = threatType.toLowerCase();

    const customAudioUrl = getAlertAudioByThreatType(type);
    if (customAudioUrl) {
        void playCustomAudioByUrl(customAudioUrl).then((played) => {
            if (played) {
                return;
            }

            if (type.includes("violence") || type.includes("fight")) {
                playViolenceAlert();
            } else if (type.includes("fire")) {
                playFireAlert();
            } else if (type.includes("suspicious") || type.includes("anomaly") || type.includes("mask")) {
                playNotification();
            }
        });
        return;
    }

    if (type.includes("weapon")) {
        playWeaponAlert();
    } else if (type.includes("violence") || type.includes("fight")) {
        playViolenceAlert();
    } else if (type.includes("fire")) {
        playFireAlert();
    } else if (type.includes("suspicious") || type.includes("anomaly") || type.includes("mask")) {
        playNotification();
    } else {
        playNotification();
    }
};
