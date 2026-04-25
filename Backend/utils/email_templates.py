"""
Email templates for signup, OTP verification, and success notifications.
Bilingual support: English and Marathi
"""


def get_signup_otp_template(full_name: str, otp: str) -> dict:
    """
    Get signup OTP email template (HTML + bilingual).
    Returns dict with 'subject' and 'html' keys.
    """
    otp_display = " ".join(list(otp))  # Space-separated OTP for readability

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; }}
            .container {{ max-width: 600px; margin: 0 auto; }}
            .email-wrapper {{ background: white; border-radius: 12px; box-shadow: 0 10px 40px rgba(0,0,0,0.1); overflow: hidden; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 40px 20px; text-align: center; }}
            .header h1 {{ font-size: 28px; margin-bottom: 5px; }}
            .header p {{ font-size: 14px; opacity: 0.9; }}
            .content {{ padding: 40px 30px; }}
            .greeting {{ font-size: 18px; color: #333; margin-bottom: 20px; }}
            .greeting-hi {{ font-weight: 600; color: #667eea; }}
            .instruction {{ color: #666; font-size: 15px; line-height: 1.6; margin-bottom: 25px; }}
            .otp-box {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 25px; border-radius: 12px; text-align: center; margin: 30px 0; }}
            .otp-label {{ font-size: 12px; opacity: 0.9; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 1px; }}
            .otp-code {{ font-size: 36px; font-weight: bold; letter-spacing: 8px; font-family: 'Courier New', monospace; }}
            .warning {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0; border-radius: 4px; font-size: 13px; color: #856404; }}
            .marathi {{ margin-top: 40px; padding-top: 30px; border-top: 1px solid #eee; }}
            .marathi-greeting {{ font-size: 16px; color: #333; margin-bottom: 15px; }}
            .marathi-text {{ color: #666; font-size: 14px; line-height: 1.6; margin-bottom: 15px; }}
            .footer {{ background: #f8f9fa; padding: 20px 30px; text-align: center; font-size: 12px; color: #999; }}
            .footer a {{ color: #667eea; text-decoration: none; }}
            .celebration {{ font-size: 24px; margin: 10px 0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="email-wrapper">
                <!-- HEADER -->
                <div class="header">
                    <h1>🔐 Campus Guard AI</h1>
                    <p>Security Excellence in Every Frame</p>
                </div>

                <!-- CONTENT -->
                <div class="content">
                    <!-- ENGLISH SECTION -->
                    <div class="greeting">
                        <span class="greeting-hi">Hello {full_name}!</span> 👋
                    </div>
                    
                    <div class="instruction">
                        Welcome to <strong>Campus Guard AI</strong>! We're excited to have you join our security team. 
                        To complete your account setup and activate all features, please use the verification code below:
                    </div>

                    <div class="otp-box">
                        <div class="otp-label">Your Verification Code</div>
                        <div class="otp-code">{otp_display}</div>
                    </div>

                    <div class="instruction">
                        <strong>What's Next?</strong><br>
                        ✅ Enter this code in the app to verify your email<br>
                        ✅ Complete your security profile setup<br>
                        ✅ Start monitoring and securing your campus<br>
                    </div>

                    <div class="warning">
                        <strong>⏱️ Important:</strong> This code expires in <strong>10 minutes</strong>. 
                        Please do not share this code with anyone. Our team will never ask for it.
                    </div>

                    <!-- MARATHI SECTION -->
                    <div class="marathi">
                        <div class="marathi-greeting">
                            <span class="greeting-hi">नमस्कार {full_name}!</span> 👋
                        </div>
                        
                        <div class="marathi-text">
                            <strong>Campus Guard AI</strong> मध्ये आपले स्वागत आहे! आमच्या सुरक्षा संघात सामील होऊन आपण खूप आनंदाची बाब आहे. 
                            आपल्या खाते सेटअप पूर्ण करण्यासाठी आणि सर्व वैशिष्ट्ये सक्रिय करण्यासाठी, कृपया खाली दिलेला सत्यापन कोड वापरा:
                        </div>

                        <div class="marathi-text">
                            <strong>पुढचे पाऊल:</strong><br>
                            ✅ अॅपमध्ये हा कोड भरून आपल्या ईमेल सत्यापित करा<br>
                            ✅ आपल्या सुरक्षा प्रोफाइल सेटअप पूर्ण करा<br>
                            ✅ आपल्या कॅम्पसचे निरीक्षण आणि सुरक्षा सुरू करा<br>
                        </div>

                        <div class="warning">
                            <strong>⏱️ महत्वाचे:</strong> हा कोड <strong>10 मिनिटांमध्ये</strong> समाप्त होईल. 
                            कृपया हा कोड कोणाशीही सामायिक करू नका. आमचा संघ त्याचा कधीही विनंती करणार नाही.
                        </div>
                    </div>
                </div>

                <!-- FOOTER -->
                <div class="footer">
                    <p>© 2026 Campus Guard AI. All rights reserved.</p>
                    <p>Questions? Contact support at <a href="mailto:support@campusguard.ai">support@campusguard.ai</a></p>
                    <p style="margin-top: 10px; font-size: 11px;">This is an automated message. Please do not reply to this email.</p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

    return {
        "subject": f"🔐 Verify Your Campus Guard AI Account - Code: {otp}",
        "html": html
    }


def get_signup_success_template(full_name: str) -> dict:
    """
    Get signup success confirmation email template (HTML + bilingual).
    Sent after successful OTP verification.
    """
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; }}
            .container {{ max-width: 600px; margin: 0 auto; }}
            .email-wrapper {{ background: white; border-radius: 12px; box-shadow: 0 10px 40px rgba(0,0,0,0.1); overflow: hidden; }}
            .header {{ background: linear-gradient(135deg, #28a745 0%, #20c997 100%); color: white; padding: 50px 20px; text-align: center; }}
            .header h1 {{ font-size: 32px; margin-bottom: 5px; }}
            .header p {{ font-size: 14px; opacity: 0.9; }}
            .celebration {{ font-size: 60px; margin: 15px 0; animation: bounce 1s; }}
            @keyframes bounce {{ 0%, 100% {{ transform: translateY(0); }} 50% {{ transform: translateY(-10px); }} }}
            .content {{ padding: 40px 30px; }}
            .greeting {{ font-size: 22px; color: #28a745; margin-bottom: 20px; font-weight: 600; }}
            .message {{ color: #333; font-size: 16px; line-height: 1.8; margin-bottom: 25px; }}
            .features {{ background: #f8f9fa; padding: 25px; border-radius: 12px; margin: 25px 0; }}
            .features h3 {{ color: #28a745; margin-bottom: 15px; font-size: 16px; }}
            .feature-list {{ list-style: none; }}
            .feature-list li {{ padding: 10px 0; color: #555; font-size: 14px; padding-left: 30px; position: relative; }}
            .feature-list li:before {{ content: "✓"; position: absolute; left: 0; color: #28a745; font-weight: bold; font-size: 18px; }}
            .cta-button {{ display: inline-block; background: linear-gradient(135deg, #28a745 0%, #20c997 100%); color: white; padding: 15px 40px; border-radius: 8px; text-decoration: none; font-weight: 600; margin-top: 20px; margin-bottom: 20px; }}
            .cta-button:hover {{ transform: translateY(-2px); box-shadow: 0 5px 15px rgba(40, 167, 69, 0.4); }}
            .marathi {{ margin-top: 40px; padding-top: 30px; border-top: 1px solid #eee; }}
            .marathi-greeting {{ font-size: 20px; color: #28a745; margin-bottom: 15px; font-weight: 600; }}
            .marathi-message {{ color: #333; font-size: 15px; line-height: 1.8; margin-bottom: 15px; }}
            .footer {{ background: #f8f9fa; padding: 20px 30px; text-align: center; font-size: 12px; color: #999; }}
            .footer a {{ color: #28a745; text-decoration: none; }}
            .badge {{ display: inline-block; background: #28a745; color: white; padding: 8px 15px; border-radius: 20px; font-size: 12px; font-weight: 600; margin: 10px 5px 10px 0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="email-wrapper">
                <!-- HEADER -->
                <div class="header">
                    <div class="celebration">🎉</div>
                    <h1>Account Activated!</h1>
                    <p>Welcome to the Campus Guard AI Family</p>
                </div>

                <!-- CONTENT -->
                <div class="content">
                    <!-- ENGLISH SECTION -->
                    <div class="greeting">
                        Congratulations, {full_name}! 🚀
                    </div>
                    
                    <div class="message">
                        Your account has been successfully created and verified. You're now part of a growing community 
                        dedicated to campus security excellence. Your dedication to protecting our campus is truly commendable!
                    </div>

                    <div class="message" style="text-align: center; font-size: 14px; color: #28a745;">
                        <span class="badge">✓ Email Verified</span>
                        <span class="badge">✓ Account Active</span>
                        <span class="badge">✓ Ready to Use</span>
                    </div>

                    <div class="features">
                        <h3>🎯 What You Can Do Now:</h3>
                        <ul class="feature-list">
                            <li>Access real-time camera feeds and detection</li>
                            <li>Monitor weapons, violence, and fire incidents</li>
                            <li>Receive instant alerts and notifications</li>
                            <li>Generate detailed security reports</li>
                            <li>Manage your team and permissions</li>
                            <li>Customize detection thresholds</li>
                        </ul>
                    </div>

                    <div class="message">
                        <strong>Next Steps:</strong><br>
                        1. Log in to your Campus Guard AI dashboard<br>
                        2. Complete your security profile settings<br>
                        3. Start monitoring your campus cameras<br>
                        4. Configure alert preferences<br>
                    </div>

                    <center>
                        <a href="#" class="cta-button">Access Your Dashboard</a>
                    </center>

                    <!-- MARATHI SECTION -->
                    <div class="marathi">
                        <div class="marathi-greeting">
                            अभिनंदन, {full_name}! 🚀
                        </div>
                        
                        <div class="marathi-message">
                            आपले खाते यशस्वीरित्या तयार केले गेले आहे आणि सत्यापित केले गेले आहे. आप आता कॅम्पस सुरक्षा उत्कृष्टतेसाठी समर्पित 
                            एक वर्धमान समुदायाचा भाग आहात. आपल्या कॅम्पसचे संरक्षण करण्याबद्दल आपल्या समर्पणाचे प्रशंसा योग्य आहे!
                        </div>

                        <div class="marathi-message" style="text-align: center; font-size: 13px; color: #28a745;">
                            <span class="badge">✓ ईमेल सत्यापित</span>
                            <span class="badge">✓ खाता सक्रिय</span>
                            <span class="badge">✓ उपयोग करण्यासाठी तयार</span>
                        </div>

                        <div class="marathi-message">
                            <strong>पुढचे पाऊल:</strong><br>
                            1. आपल्या Campus Guard AI डॅशबोर्डमध्ये लॉगिन करा<br>
                            2. आपल्या सुरक्षा प्रोफाइल सेटिंग्स पूर्ण करा<br>
                            3. आपल्या कॅम्पस कॅमेरे मॉनिटर करण्यास सुरू करा<br>
                            4. सतर्कता प्राधान्ये कॉन्फिगर करा<br>
                        </div>
                    </div>
                </div>

                <!-- FOOTER -->
                <div class="footer">
                    <p>© 2026 Campus Guard AI. All rights reserved.</p>
                    <p>Questions? Contact support at <a href="mailto:support@campusguard.ai">support@campusguard.ai</a></p>
                    <p style="margin-top: 10px; font-size: 11px;">This is an automated message. Please do not reply to this email.</p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

    return {
        "subject": f"🎉 Welcome to Campus Guard AI, {full_name}! Your Account is Live",
        "html": html
    }


def get_login_otp_template(full_name: str, otp: str) -> dict:
    """
    Get login OTP email template (HTML + bilingual).
    Sent when user requests OTP for login.
    """
    otp_display = " ".join(list(otp))

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; }}
            .container {{ max-width: 600px; margin: 0 auto; }}
            .email-wrapper {{ background: white; border-radius: 12px; box-shadow: 0 10px 40px rgba(0,0,0,0.1); overflow: hidden; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 40px 20px; text-align: center; }}
            .header h1 {{ font-size: 28px; margin-bottom: 5px; }}
            .header p {{ font-size: 14px; opacity: 0.9; }}
            .content {{ padding: 40px 30px; }}
            .greeting {{ font-size: 18px; color: #333; margin-bottom: 20px; }}
            .greeting-hi {{ font-weight: 600; color: #667eea; }}
            .instruction {{ color: #666; font-size: 15px; line-height: 1.6; margin-bottom: 25px; }}
            .otp-box {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 25px; border-radius: 12px; text-align: center; margin: 30px 0; }}
            .otp-label {{ font-size: 12px; opacity: 0.9; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 1px; }}
            .otp-code {{ font-size: 36px; font-weight: bold; letter-spacing: 8px; font-family: 'Courier New', monospace; }}
            .security-note {{ background: #cfe2ff; border-left: 4px solid #0d6efd; padding: 15px; margin: 20px 0; border-radius: 4px; font-size: 13px; color: #084298; }}
            .marathi {{ margin-top: 40px; padding-top: 30px; border-top: 1px solid #eee; }}
            .marathi-greeting {{ font-size: 16px; color: #333; margin-bottom: 15px; }}
            .marathi-text {{ color: #666; font-size: 14px; line-height: 1.6; margin-bottom: 15px; }}
            .footer {{ background: #f8f9fa; padding: 20px 30px; text-align: center; font-size: 12px; color: #999; }}
            .footer a {{ color: #667eea; text-decoration: none; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="email-wrapper">
                <!-- HEADER -->
                <div class="header">
                    <h1>🔐 Login Verification</h1>
                    <p>Campus Guard AI Security</p>
                </div>

                <!-- CONTENT -->
                <div class="content">
                    <!-- ENGLISH SECTION -->
                    <div class="greeting">
                        <span class="greeting-hi">Hi {full_name}!</span> 🔑
                    </div>
                    
                    <div class="instruction">
                        We received a login request for your Campus Guard AI account. Use the code below to complete your login:
                    </div>

                    <div class="otp-box">
                        <div class="otp-label">Your Login Code</div>
                        <div class="otp-code">{otp_display}</div>
                    </div>

                    <div class="security-note">
                        <strong>🔒 Security Reminder:</strong> If you didn't request this code, please ignore this email. 
                        Never share this code with anyone. We will never ask for it.
                    </div>

                    <!-- MARATHI SECTION -->
                    <div class="marathi">
                        <div class="marathi-greeting">
                            <span class="greeting-hi">नमस्कार {full_name}!</span> 🔑
                        </div>
                        
                        <div class="marathi-text">
                            आमने आपल्या Campus Guard AI खाते साठी लॉगिन विनंती प्राप्त केली. आपल्या लॉगिन पूर्ण करण्यासाठी खाली दिलेला कोड वापरा:
                        </div>

                        <div class="marathi-text">
                            <strong>🔒 सुरक्षा सूचना:</strong> आपण हा कोड विनंती केली नसल्यास, कृपया हा ईमेल दुर्लक्ष करा. 
                            हा कोड कोणाशीही सामायिक करू नका. आम्ही त्याचा कधीही विनंती करणार नाही.
                        </div>
                    </div>
                </div>

                <!-- FOOTER -->
                <div class="footer">
                    <p>© 2026 Campus Guard AI. All rights reserved.</p>
                    <p>Questions? Contact support at <a href="mailto:support@campusguard.ai">support@campusguard.ai</a></p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

    return {
        "subject": f"🔐 Login Code for Campus Guard AI - {otp}",
        "html": html
    }


def get_alert_email_template(detected_type: str, subtype: str | None, confidence: float, timestamp: str, location: str | None, frame_url: str | None) -> dict:
    """Return a simple HTML alert email with detection details.

    - `detected_type`: high-level type like 'weapon', 'fire', 'violence'
    - `subtype`: model class label when available (e.g., 'pistol')
    - `timestamp`: UTC timestamp string
    - `location`: optional camera/location string
    - `frame_url`: optional URL linking to the saved frame
    """
    label = (subtype or detected_type).upper()
    subject = f"🚨 ALERT: {label} detected"
    # Keep HTML minimal and mobile-friendly
    html = f"""
        <!doctype html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width,initial-scale=1">
            <style>
                body{{font-family:Segoe UI, Roboto, Arial, sans-serif; background:#f6f8fb; margin:0; padding:20px}}
                .card{{max-width:600px;margin:0 auto;background:#fff;padding:20px;border-radius:8px;box-shadow:0 6px 24px rgba(0,0,0,0.08)}}
                .hdr{{color:#b91c1c;font-weight:700;margin-bottom:8px}}
                .muted{{color:#666;font-size:13px;margin-bottom:12px}}
                .kv{{margin:8px 0;padding:8px;background:#f8fafc;border-radius:6px}}
                a.button{{display:inline-block;margin-top:12px;padding:10px 14px;background:#1f6feb;color:#fff;border-radius:6px;text-decoration:none}}
            </style>
        </head>
        <body>
            <div class="card">
                <div class="hdr">🚨 {label} detected</div>
                <div class="muted">A campus AI camera has detected a possible security event.</div>
                <div class="kv"><strong>Type:</strong> {detected_type}</div>
                <div class="kv"><strong>Class:</strong> {subtype or '—'}</div>
                <div class="kv"><strong>Confidence:</strong> {confidence:.2f}</div>
                <div class="kv"><strong>Time (UTC):</strong> {timestamp}</div>
                <div class="kv"><strong>Location:</strong> {location or 'AI Camera'}</div>
                {f'<a class="button" href="{frame_url}">View captured frame</a>' if frame_url else ''}
                <p style="margin-top:14px;font-size:12px;color:#888">This is an automated security notification from Campus Guard AI.</p>
            </div>
        </body>
        </html>
        """
    return {"subject": subject, "html": html}
