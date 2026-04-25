from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Final

SUPPORTED_GUARD_LANGUAGES: Final[set[str]] = {"en", "hi", "mr"}
IST_TIMEZONE = timezone(timedelta(hours=5, minutes=30))


def normalize_guard_language(language: str | None) -> str:
    code = str(language or "en").strip().lower()
    return code if code in SUPPORTED_GUARD_LANGUAGES else "en"


def _threat_label(alert_type: str | None, subtype: str | None, language: str) -> str:
    code = normalize_guard_language(language)
    key = str(subtype or alert_type or "alert").strip().lower()

    labels = {
        "en": {
            "weapon": "Weapon",
            "violence": "Violence",
            "fire": "Fire",
            "anomaly": "Anomaly",
            "pistol": "Pistol",
            "long_knife": "Long Knife",
            "pocket_knife": "Pocket Knife",
        },
        "hi": {
            "weapon": "हथियार",
            "violence": "हिंसा",
            "fire": "आग",
            "anomaly": "असामान्य घटना",
            "pistol": "पिस्तौल",
            "long_knife": "लंबा चाकू",
            "pocket_knife": "पॉकेट चाकू",
        },
        "mr": {
            "weapon": "शस्त्र",
            "violence": "हिंसाचार",
            "fire": "आग",
            "anomaly": "असामान्य घटना",
            "pistol": "पिस्तूल",
            "long_knife": "लांब चाकू",
            "pocket_knife": "पॉकेट चाकू",
        },
    }
    return labels.get(code, labels["en"]).get(key, key.replace("_", " ").title())


def _deterministic_variant_index(seed: str | None, variants: int) -> int:
    if variants <= 1:
        return 0
    raw = str(seed or "").strip()
    if not raw:
        return 0
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % variants


def _format_guard_alert_time(value: str | None, language: str) -> str:
    code = normalize_guard_language(language)
    token = str(value or "").strip()
    if not token:
        return "N/A"

    normalized = token.replace("Z", "+00:00")
    dt: datetime | None = None
    try:
        dt = datetime.fromisoformat(normalized)
    except Exception:
        dt = None

    if dt is not None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_ist = dt.astimezone(IST_TIMEZONE)
        if code == "en":
            return dt_ist.strftime("%d %b %Y, %I:%M %p IST")
        return dt_ist.strftime("%d-%m-%Y %H:%M IST")

    cleaned = token.replace("T", " ")
    if "." in cleaned:
        cleaned = cleaned.split(".", 1)[0]
    return cleaned


def build_guard_otp_message(otp: str, language: str, expiry_minutes: int = 10) -> str:
    code = normalize_guard_language(language)

    if code == "hi":
        return (
            "*CAMPUS GUARD AI - सुरक्षित OTP*\n\n"
            "नमस्ते अधिकारी,\n"
            "कृपया नीचे दिया गया सत्यापन कोड उपयोग करें:\n\n"
            f"*OTP:* {otp}\n"
            f"*समय सीमा:* {expiry_minutes} मिनट\n\n"
            "*सुरक्षा सूचना:*\n"
            "- OTP किसी के साथ साझा न करें।\n"
            "- Campus Guard AI टीम कभी भी OTP नहीं मांगती।\n\n"
            "यदि आपने यह अनुरोध नहीं किया है, तो इस संदेश को नजरअंदाज करें और प्रशासक को सूचित करें।"
        )

    if code == "mr":
        return (
            "*CAMPUS GUARD AI - सुरक्षित OTP*\n\n"
            "नमस्कार अधिकारी,\n"
            "कृपया खालील सत्यापन कोड वापरा:\n\n"
            f"*OTP:* {otp}\n"
            f"*वैधता:* {expiry_minutes} मिनिटे\n\n"
            "*सुरक्षा सूचना:*\n"
            "- OTP कोणाशीही शेअर करू नका.\n"
            "- Campus Guard AI टीम कधीही OTP विचारत नाही.\n\n"
            "जर हा विनंती संदेश तुमचा नसेल तर हा संदेश दुर्लक्ष करा आणि प्रशासकाला कळवा."
        )

    return (
        "*CAMPUS GUARD AI - SECURE OTP*\n\n"
        "Hello Officer,\n"
        "Please use the verification code below to continue:\n\n"
        f"*OTP:* {otp}\n"
        f"*Validity:* {expiry_minutes} minutes\n\n"
        "*Security Notice:*\n"
        "- Never share this OTP with anyone.\n"
        "- Campus Guard AI team will never ask for your OTP.\n\n"
        "If you did not request this, ignore this message and report to admin."
    )


def build_guard_onboarding_message(full_name: str | None, language: str) -> str:
    code = normalize_guard_language(language)
    name = (full_name or "Guard").strip() or "Guard"

    if code == "hi":
        return (
            "*CAMPUS GUARD AI - ACCESS CONFIRMED*\n\n"
            f"स्वागत है, *{name}*।\n"
            "आपका गार्ड खाता अब कैंपस सुरक्षा प्रणाली में सक्रिय है।\n\n"
            "*आपको ये अपडेट मिलेंगे:*\n"
            "1) पुष्टि किए गए खतरे (हथियार, हिंसा, आग, असामान्य घटना)\n"
            "2) ड्यूटी से जुड़े संचालन निर्देश\n"
            "3) प्रशासक से महत्वपूर्ण एस्केलेशन अपडेट\n\n"
            "*आवश्यक कार्रवाई:*\n"
            "जब भी पुष्टि किया गया खतरा आए, गार्ड डैशबोर्ड खोलकर तुरंत प्रोटोकॉल का पालन करें।\n\n"
            "सतर्क रहें। सुरक्षित रहें।"
        )

    if code == "mr":
        return (
            "*CAMPUS GUARD AI - ACCESS CONFIRMED*\n\n"
            f"स्वागत आहे, *{name}*।\n"
            "तुमचे गार्ड खाते आता कॅम्पस सुरक्षा प्रणालीमध्ये सक्रिय आहे।\n\n"
            "*तुम्हाला हे अपडेट मिळतील:*\n"
            "1) पुष्टी झालेले धोके (शस्त्र, हिंसाचार, आग, असामान्य घटना)\n"
            "2) ड्युटी संबंधी कार्यसूचना\n"
            "3) प्रशासकाकडून महत्त्वाचे एस्कलेशन अपडेट्स\n\n"
            "*आवश्यक कृती:*\n"
            "पुष्टी झालेला धोका आला की गार्ड डॅशबोर्ड उघडा आणि तात्काळ प्रोटोकॉलनुसार प्रतिसाद द्या।\n\n"
            "सतर्क रहा। सुरक्षित रहा।"
        )

    return (
        "*CAMPUS GUARD AI - ACCESS CONFIRMED*\n\n"
        f"Welcome, *{name}*.\n"
        "Your guard account is now active in the Campus Security System.\n\n"
        "*You will receive updates for:*\n"
        "1) Confirmed threats (weapon, violence, fire, anomaly)\n"
        "2) Duty-related operational instructions\n"
        "3) Critical escalation updates from administrators\n\n"
        "*Action Required:*\n"
        "When a confirmed threat arrives, open the Guard Dashboard and respond immediately as per protocol.\n\n"
        "Stay alert. Stay safe."
    )


def build_guard_confirmed_alert_message(
    *,
    alert_type: str,
    subtype: str | None,
    confidence: float,
    camera_location: str,
    ist_time: str,
    language: str,
    variation_seed: str | None = None,
) -> str:
    code = normalize_guard_language(language)
    threat = _threat_label(alert_type, subtype, code)
    display_time = _format_guard_alert_time(ist_time, code)
    confidence_pct = round((confidence or 0) * 100, 2)
    variant = _deterministic_variant_index(variation_seed, 3)

    if code == "hi":
        variants = [
            (
                "🚨 *कोड रेड // CAMPUS GUARD AI* 🚨\n\n"
                "*स्थिति:* प्रशासक द्वारा खतरा पुष्टि\n"
                f"*खतरा:* {threat}\n"
                f"*स्थान:* {camera_location}\n"
                f"*समय (IST):* {display_time}\n"
                f"*विश्वास स्तर:* {confidence_pct}%\n\n"
                "*तुरंत 60-सेकंड कार्रवाई:*\n"
                "1) निकटतम टीम को अलर्ट करें\n"
                "2) एरिया सुरक्षित करें और निकास कंट्रोल करें\n"
                "3) कंट्रोल रूम में स्थिति अपडेट दें"
            ),
            (
                "🚨 *तात्कालिक सुरक्षा सूचना*\n\n"
                "कंट्रोल रूम से पुष्टि: यह सक्रिय घटना है।\n"
                f"*घटना:* {threat}\n"
                f"*लोकेशन:* {camera_location}\n"
                f"*समय:* {display_time}\n"
                f"*मॉडल विश्वास:* {confidence_pct}%\n\n"
                "*कार्रवाई:*\n"
                "• तुरंत पहुंचें\n"
                "• नागरिकों को सुरक्षित दूरी पर रखें\n"
                "• बैकअप के लिए रेडियो अपडेट भेजें"
            ),
            (
                "🚨 *कैंपस शील्ड अलर्ट*\n\n"
                f"पुष्टि किया गया खतरा: *{threat}*\n"
                f"कैमरा ज़ोन: {camera_location}\n"
                f"लॉग समय: {display_time}\n"
                f"AI विश्वास स्कोर: {confidence_pct}%\n\n"
                "तुरंत मूव करें, क्षेत्र लॉक करें, और ACK भेजें।"
            ),
        ]
        return variants[variant]

    if code == "mr":
        variants = [
            (
                "🚨 *कोड रेड // CAMPUS GUARD AI* 🚨\n\n"
                "*स्थिती:* प्रशासकाकडून पुष्टी\n"
                f"*धोका:* {threat}\n"
                f"*स्थान:* {camera_location}\n"
                f"*वेळ (IST):* {display_time}\n"
                f"*विश्वास पातळी:* {confidence_pct}%\n\n"
                "*तात्काळ 60-सेकंद कृती:*\n"
                "1) जवळच्या टीमला सतर्क करा\n"
                "2) परिसर सुरक्षित करा आणि बाहेरचे मार्ग नियंत्रित करा\n"
                "3) कंट्रोल रूमला स्थिती अपडेट द्या"
            ),
            (
                "🚨 *तातडीची सुरक्षा सूचना*\n\n"
                "कंट्रोल रूम पुष्टी: ही सक्रिय घटना आहे।\n"
                f"*घटना:* {threat}\n"
                f"*लोकेशन:* {camera_location}\n"
                f"*वेळ:* {display_time}\n"
                f"*मॉडेल विश्वास:* {confidence_pct}%\n\n"
                "*कृती:*\n"
                "• तात्काळ घटनास्थळी पोहोचा\n"
                "• नागरिकांना सुरक्षित अंतरावर ठेवा\n"
                "• बॅकअपसाठी रेडिओ अपडेट पाठवा"
            ),
            (
                "🚨 *कॅम्पस शिल्ड अलर्ट*\n\n"
                f"पुष्टी झालेला धोका: *{threat}*\n"
                f"कॅमेरा झोन: {camera_location}\n"
                f"नोंद वेळ: {display_time}\n"
                f"AI विश्वास स्कोर: {confidence_pct}%\n\n"
                "ताबडतोब हालचाल करा, परिसर लॉक करा आणि ACK पाठवा।"
            ),
        ]
        return variants[variant]

    variants = [
        (
            "🚨 *CAMPUS THREAT ALERT*\n\n"
            f"Category: {threat}\n"
            f"Location: {camera_location}\n"
            f"Time: {display_time}\n"
            f"Confidence: {confidence_pct}%\n\n"
            "Action: Reach location, secure civilians, and update control room."
        ),
        (
            "🚨 *URGENT CAMPUS THREAT UPDATE*\n\n"
            f"Category: {threat}\n"
            f"Location: {camera_location}\n"
            f"Logged at: {display_time}\n"
            f"Model confidence: {confidence_pct}%\n\n"
            "Action now: secure civilians and report status."
        ),
        (
            "🚨 *CONTROL ROOM PRIORITY ALERT*\n\n"
            f"Threat: {threat}\n"
            f"Area: {camera_location}\n"
            f"Time: {display_time}\n"
            f"AI confidence: {confidence_pct}%\n\n"
            "Proceed immediately. Secure area and send live update."
        ),
    ]
    return variants[variant]


def build_guard_duty_quick_reply_hint(language: str) -> str:
    code = normalize_guard_language(language)

    if code == "hi":
        return (
            "*ड्यूटी कंट्रोल:*\n"
            "- ड्यूटी शुरू करने के लिए जवाब दें: *ON*\n"
            "- ड्यूटी बंद करने के लिए जवाब दें: *OFF*"
        )

    if code == "mr":
        return (
            "*ड्युटी कंट्रोल:*\n"
            "- ड्युटी सुरू करण्यासाठी उत्तर द्या: *ON*\n"
            "- ड्युटी बंद करण्यासाठी उत्तर द्या: *OFF*"
        )

    return (
        "*Duty Control:*\n"
        "- Reply *ON* to go ON DUTY\n"
        "- Reply *OFF* to go OFF DUTY"
    )


def build_guard_admin_instruction_message(
    *,
    instruction: str,
    admin_email: str | None,
    timestamp: str,
    language: str,
) -> str:
    code = normalize_guard_language(language)
    sender = admin_email or "System Admin"

    if code == "hi":
        return (
            "*ADMIN INSTRUCTION - CAMPUS GUARD AI*\n"
            f"*समय:* {timestamp}\n"
            f"*प्रेषक:* {sender}\n\n"
            f"{instruction}\n\n"
            "कृपया तुरंत प्राप्ति स्वीकार करें और निर्देशों का पालन करें।"
        )

    if code == "mr":
        return (
            "*ADMIN INSTRUCTION - CAMPUS GUARD AI*\n"
            f"*वेळ:* {timestamp}\n"
            f"*प्रेषक:* {sender}\n\n"
            f"{instruction}\n\n"
            "कृपया तात्काळ स्वीकार नोंदवा आणि सूचनांची अंमलबजावणी करा।"
        )

    return (
        "*ADMIN INSTRUCTION - CAMPUS GUARD AI*\n"
        f"*Time:* {timestamp}\n"
        f"*From:* {sender}\n\n"
        f"{instruction}\n\n"
        "Please acknowledge and execute immediately."
    )


def build_guard_duty_status_message(
    *,
    is_on_duty: bool,
    full_name: str | None,
    language: str,
    timestamp: str,
) -> str:
    code = normalize_guard_language(language)
    name = (full_name or "Guard").strip() or "Guard"

    if code == "hi":
        status_line = "आप अब *ऑन ड्यूटी* हैं।" if is_on_duty else "आप अब *ऑफ ड्यूटी* हैं।"
        action_line = (
            "कृपया गार्ड डैशबोर्ड मॉनिटर करते रहें और पुष्टि किए गए खतरे पर तुरंत प्रतिक्रिया दें।"
            if is_on_duty
            else "आपकी शिफ्ट बंद हो गई है। आपात स्थिति में प्रशासक के निर्देशों का पालन करें।"
        )
        return (
            "*GUARD DUTY STATUS - CAMPUS GUARD AI*\n\n"
            f"नमस्ते *{name}*,\n"
            f"{status_line}\n"
            f"*समय:* {timestamp}\n\n"
            f"{action_line}"
        )

    if code == "mr":
        status_line = "तुम्ही आता *ऑन ड्यूटी* आहात।" if is_on_duty else "तुम्ही आता *ऑफ ड्यूटी* आहात।"
        action_line = (
            "कृपया गार्ड डॅशबोर्डवर लक्ष ठेवा आणि पुष्टी झालेल्या धोक्यावर तात्काळ प्रतिसाद द्या।"
            if is_on_duty
            else "तुमची शिफ्ट बंद झाली आहे। आपत्कालीन स्थितीत प्रशासकाच्या सूचनांचे पालन करा।"
        )
        return (
            "*GUARD DUTY STATUS - CAMPUS GUARD AI*\n\n"
            f"नमस्कार *{name}*,\n"
            f"{status_line}\n"
            f"*वेळ:* {timestamp}\n\n"
            f"{action_line}"
        )

    status_line = "You are now *ON DUTY*." if is_on_duty else "You are now *OFF DUTY*."
    action_line = (
        "Please keep monitoring the Guard Dashboard and respond immediately to confirmed threats."
        if is_on_duty
        else "Your shift has been closed. Follow administrator instructions in case of emergency."
    )
    return (
        "*GUARD DUTY STATUS - CAMPUS GUARD AI*\n\n"
        f"Hello *{name}*,\n"
        f"{status_line}\n"
        f"*Time:* {timestamp}\n\n"
        f"{action_line}"
    )
