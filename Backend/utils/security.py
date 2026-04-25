import os
import base64
import mimetypes
from datetime import datetime, timedelta
from typing import Optional
import logging
import smtplib
import requests
from urllib.parse import urlparse
from html import escape
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import traceback

# ADDED find_dotenv to guarantee it finds your .env file anywhere in the project
from dotenv import load_dotenv
from pathlib import Path
from jose import jwt, JWTError
from passlib.context import CryptContext

# Load the .env file located in the Backend directory (relative to this file)
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=str(env_path))

# Debug prints to help diagnose missing MAIL_USERNAME when starting from project root
print(f"[ENV] Loaded .env from: {env_path}")
_mail_user_debug = os.getenv("MAIL_USERNAME")
print(
    f"[ENV] MAIL_USERNAME {'FOUND' if _mail_user_debug else 'MISSING'}: {(_mail_user_debug[:3] + '...') if _mail_user_debug else ''}")

SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# Cleaned up credential loading to ensure no spaces or stray quotes
MAIL_USERNAME = os.getenv("MAIL_USERNAME", "").strip()
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "").strip()
MAIL_FROM_NAME = os.getenv(
    "MAIL_FROM_NAME", "Campus Guard AI").strip('"').strip("'")

# Support either SMTP_HOST or MAIL_SERVER
SMTP_HOST = os.getenv("SMTP_HOST") or os.getenv(
    "MAIL_SERVER") or "smtp.gmail.com"
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

# Configure basic logging for debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai_campus.security")

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def _normalize_password(secret: str) -> str:
    """
    Normalize password input before hashing/verifying.

    We keep this as a dedicated helper so auth behavior stays consistent even
    if the hashing scheme changes again later.
    """
    return secret


def get_password_hash(password: str) -> str:
    safe = _normalize_password(password)
    return pwd_context.hash(safe)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    safe = _normalize_password(plain_password)
    return pwd_context.verify(safe, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def _build_multilingual_otp_email(destination: str, otp: str) -> tuple[str, str, str]:
    """Build multilingual OTP email payload (subject, plain_text, html)."""
    local_part = str(destination or "user").split(
        "@", 1)[0].replace(".", " ").replace("_", " ").strip()
    recipient_name = local_part.title() if local_part else "Officer"
    safe_name = escape(recipient_name)
    otp_compact = str(otp or "").strip()
    otp_display = " ".join(list(otp_compact))

    subject = f"Campus Guard AI Verification Code | OTP: {otp_compact}"

    plain_text = (
        f"Hello {recipient_name},\n\n"
        f"Your one-time verification code is: {otp_compact}\n"
        f"This code is valid for 10 minutes.\n\n"
        "Hindi (हिन्दी):\n"
        f"नमस्ते {recipient_name},\n"
        f"आपका एक-बार उपयोग होने वाला सत्यापन कोड: {otp_compact}\n"
        "यह कोड 10 मिनट तक मान्य है।\n\n"
        "Marathi (मराठी):\n"
        f"नमस्कार {recipient_name},\n"
        f"तुमचा एकदाच वापरायचा सत्यापन कोड: {otp_compact}\n"
        "हा कोड 10 मिनिटे वैध आहे.\n\n"
        "Security note:\n"
        "Do not share this code with anyone. Campus Guard AI team will never ask for your OTP.\n"
    )

    html = f"""
    <!doctype html>
    <html>
    <head>
        <meta charset=\"utf-8\">
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
        <style>
            body {{ margin: 0; padding: 20px; background: #eef3fb; font-family: Segoe UI, Arial, sans-serif; }}
            .card {{ max-width: 620px; margin: 0 auto; background: #ffffff; border-radius: 14px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.08); }}
            .header {{ background: linear-gradient(135deg, #0f4c81, #1779ba); color: #fff; padding: 24px; }}
            .header h1 {{ margin: 0; font-size: 22px; }}
            .header p {{ margin: 8px 0 0; opacity: 0.9; font-size: 13px; }}
            .section {{ padding: 18px 24px; border-top: 1px solid #edf1f7; }}
            .lang {{ font-size: 12px; font-weight: 700; color: #1779ba; text-transform: uppercase; letter-spacing: 0.4px; margin-bottom: 8px; }}
            .text {{ margin: 0; color: #243447; line-height: 1.6; font-size: 14px; }}
            .otp-box {{ margin-top: 14px; background: #f0f7ff; border: 1px solid #d3e8ff; border-radius: 10px; padding: 14px; text-align: center; }}
            .otp-label {{ font-size: 12px; color: #4b647d; text-transform: uppercase; letter-spacing: 1px; }}
            .otp-code {{ margin-top: 8px; font-size: 30px; font-weight: 700; letter-spacing: 8px; color: #0f4c81; font-family: Consolas, monospace; }}
            .notice {{ margin: 0; color: #734c00; background: #fff8e6; border: 1px solid #ffe8a3; border-radius: 10px; padding: 12px 14px; font-size: 13px; line-height: 1.5; }}
            .footer {{ padding: 14px 24px 20px; color: #60758a; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class=\"card\">
            <div class=\"header\">
                <h1>Campus Guard AI</h1>
                <p>Secure verification for your account access</p>
            </div>

            <div class=\"section\">
                <div class=\"lang\">English</div>
                <p class=\"text\">Hello {safe_name}, your one-time verification code is:</p>
                <div class=\"otp-box\">
                    <div class=\"otp-label\">Verification Code</div>
                    <div class=\"otp-code\">{otp_display}</div>
                </div>
                <p class=\"text\" style=\"margin-top: 10px;\">This code is valid for 10 minutes.</p>
            </div>

            <div class=\"section\">
                <div class=\"lang\">हिन्दी</div>
                <p class=\"text\">नमस्ते {safe_name}, आपका एक-बार उपयोग होने वाला सत्यापन कोड ऊपर दिया गया है। यह कोड 10 मिनट तक मान्य है।</p>
            </div>

            <div class=\"section\">
                <div class=\"lang\">मराठी</div>
                <p class=\"text\">नमस्कार {safe_name}, तुमचा एकदाच वापरायचा सत्यापन कोड वर दिलेला आहे. हा कोड 10 मिनिटे वैध आहे.</p>
            </div>

            <div class=\"section\">
                <p class=\"notice\"><strong>Security Notice:</strong> Do not share this code with anyone. Our team never asks for your OTP.</p>
            </div>

            <div class=\"footer\">
                This is an automated security email from Campus Guard AI.
            </div>
        </div>
    </body>
    </html>
    """

    return subject, plain_text, html


def send_otp(destination: str, otp: str) -> None:
    """
    Send OTP via SMTP with multilingual plain text + HTML fallback.
    """
    if not MAIL_USERNAME or not MAIL_PASSWORD:
        logger.error(
            "❌ [OTP] Credentials missing! Python could not read the .env file.")
        return

    subject, plain_text, html = _build_multilingual_otp_email(destination, otp)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{MAIL_FROM_NAME} <{MAIL_USERNAME}>"
    msg["To"] = destination
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    logger.info(
        f"[OTP] Sending email to {destination} via {SMTP_HOST}:{SMTP_PORT}...")

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.set_debuglevel(1)
            server.ehlo()

            if SMTP_PORT == 587:
                server.starttls()
                server.ehlo()

            # Login with the exact 16-character app password
            server.login(MAIL_USERNAME, MAIL_PASSWORD)

            # Send the email
            server.sendmail(MAIL_USERNAME, [destination], msg.as_string())

        logger.info(f"✅ SUCCESS: OTP successfully sent to {destination}")

    except Exception as exc:
        logger.error(f"❌ [OTP] Failed to send email to {destination}: {exc}")
        logger.error(traceback.format_exc())


def send_email(destination: str, subject: str, body: str, html: bool = False) -> bool:
    """Send a generic email (blocking). Returns True on success.

    Set `html=True` to send an HTML email body.
    """
    if not MAIL_USERNAME or not MAIL_PASSWORD:
        logger.error("Email credentials missing; cannot send email")
        return False

    try:
        if html:
            msg = MIMEText(body, "html")
        else:
            msg = MIMEText(body)

        msg["Subject"] = subject
        msg["From"] = f"{MAIL_FROM_NAME} <{MAIL_USERNAME}>"
        msg["To"] = destination

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.set_debuglevel(0)
            server.ehlo()
            if SMTP_PORT == 587:
                server.starttls()
                server.ehlo()
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.sendmail(MAIL_USERNAME, [destination], msg.as_string())

        logger.info(f"Email sent to {destination}")
        return True
    except Exception as exc:
        logger.error(f"Failed to send email to {destination}: {exc}")
        logger.error(traceback.format_exc())
        return False


def send_sms(phone: str, body: str) -> bool:
    """Send SMS via Twilio if configured. Returns True on success or False."""
    TWILIO_SID = os.getenv("TWILIO_SID")
    TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")
    TWILIO_FROM = os.getenv("TWILIO_FROM")

    if not (TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM):
        logger.warning("Twilio not configured; skipping SMS to %s", phone)
        return False

    try:
        from twilio.rest import Client

        client = Client(TWILIO_SID, TWILIO_TOKEN)
        msg = client.messages.create(body=body, from_=TWILIO_FROM, to=phone)
        logger.info("SMS sent to %s sid=%s", phone, getattr(msg, 'sid', 'n/a'))
        return True
    except Exception as exc:
        logger.error("Failed to send SMS to %s: %s", phone, exc)
        logger.error(traceback.format_exc())
        return False


def _to_waha_chat_id(phone: str) -> str:
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    return f"{digits}@c.us"


def send_whatsapp(phone: str, body: str) -> bool:
    """Send WhatsApp text through WAHA HTTP API. Returns True on success."""
    waha_url = os.getenv("WAHA_API_URL", "http://localhost:3000").strip()
    waha_key = os.getenv("WAHA_API_KEY", "").strip()
    waha_session = os.getenv("WAHA_SESSION", "").strip()
    timeout_sec = float(os.getenv("WAHA_TIMEOUT_SEC", "10"))

    if not phone:
        logger.warning("WAHA send skipped: missing destination phone")
        return False

    chat_id = _to_waha_chat_id(phone)
    digits = "".join(ch for ch in str(phone) if ch.isdigit())

    def _candidate_urls(base_url: str) -> list[str]:
        base = base_url.rstrip("/")
        parsed = urlparse(base)
        path = parsed.path or ""

        candidates = []
        if path.endswith("/api/sendText"):
            candidates.append(base)
        else:
            candidates.append(f"{base}/api/sendText")
            if "/api" in path:
                candidates.append(base)

        if waha_session:
            candidates.append(f"{base}/api/{waha_session}/sendText")

        # Remove duplicates while preserving order.
        seen = set()
        deduped = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                deduped.append(c)
        return deduped

    payload_candidates = [
        {"chatId": chat_id, "text": body, **
            ({"session": waha_session} if waha_session else {})},
        {"chatId": chat_id, "text": body},
        {"to": chat_id, "text": body, **
            ({"session": waha_session} if waha_session else {})},
        {"phone": digits, "message": body, **
            ({"session": waha_session} if waha_session else {})},
    ]

    headers = {"Content-Type": "application/json"}
    if waha_key:
        headers["X-Api-Key"] = waha_key

    last_error = ""
    urls = _candidate_urls(waha_url)
    for url in urls:
        for payload in payload_candidates:
            try:
                res = requests.post(url, json=payload,
                                    headers=headers, timeout=timeout_sec)
                if res.status_code < 400:
                    logger.info("WAHA message sent to %s via %s", phone, url)
                    return True
                last_error = f"status={res.status_code} body={res.text}"
            except Exception as exc:
                last_error = str(exc)

    logger.error("WAHA send failed for %s after trying %d endpoints. Last error: %s",
                 phone, len(urls), last_error)
    return False


def send_whatsapp_image(phone: str, caption: str, image_path: str) -> bool:
    """Send WhatsApp image through WAHA /api/sendImage. Returns True on success."""
    waha_url = os.getenv("WAHA_API_URL", "http://localhost:3000").strip()
    waha_key = os.getenv("WAHA_API_KEY", "").strip()
    waha_session = os.getenv("WAHA_SESSION", "default").strip() or "default"
    timeout_sec = float(os.getenv("WAHA_TIMEOUT_SEC", "10"))

    if not phone:
        logger.warning("WAHA image send skipped: missing destination phone")
        return False
    if not image_path or not os.path.isfile(image_path):
        logger.warning(
            "WAHA image send skipped: snapshot not found at %s", image_path)
        return False

    try:
        with open(image_path, "rb") as image_file:
            binary_data = image_file.read()
    except Exception as exc:
        logger.error("WAHA image read failed for %s: %s", image_path, exc)
        return False

    mime_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    encoded = base64.b64encode(binary_data).decode("utf-8")
    data_uri = f"data:{mime_type};base64,{encoded}"

    chat_id = _to_waha_chat_id(phone)

    def _candidate_urls(base_url: str) -> list[str]:
        base = base_url.rstrip("/")
        parsed = urlparse(base)
        path = parsed.path or ""

        candidates = []
        if path.endswith("/api/sendImage"):
            candidates.append(base)
        else:
            candidates.append(f"{base}/api/sendImage")
            if "/api" in path:
                candidates.append(base)
            candidates.append(f"{base}/api/{waha_session}/sendImage")

        seen = set()
        deduped = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                deduped.append(c)
        return deduped

    payload_candidates = [
        {
            "session": waha_session,
            "chatId": chat_id,
            "file": data_uri,
            "caption": caption,
        },
        {
            "chatId": chat_id,
            "file": data_uri,
            "caption": caption,
        },
    ]

    headers = {"Content-Type": "application/json"}
    if waha_key:
        headers["X-Api-Key"] = waha_key

    last_error = ""
    urls = _candidate_urls(waha_url)
    for url in urls:
        for payload in payload_candidates:
            try:
                res = requests.post(url, json=payload,
                                    headers=headers, timeout=timeout_sec)
                if res.status_code < 400:
                    logger.info("WAHA image sent to %s via %s", phone, url)
                    return True
                last_error = f"status={res.status_code} body={res.text}"
            except Exception as exc:
                last_error = str(exc)

    logger.error(
        "WAHA image send failed for %s after trying %d endpoints. Last error: %s",
        phone,
        len(urls),
        last_error,
    )
    return False


def send_notification(email: Optional[str], phone: Optional[str], subject: str, body: str, use_email: bool = True, use_sms: bool = True, html: bool = False) -> dict:
    """Send notifications to provided email/phone. Returns status dict.

    Pass `html=True` to send the `body` as HTML email.
    """
    result = {"email": None, "sms": None}
    if use_email and email:
        result["email"] = send_email(email, subject, body, html=html)
    if use_sms and phone:
        result["sms"] = send_sms(phone, body)
    return result
