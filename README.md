# AI Campus Security Monitoring System

AI-powered campus surveillance platform for real-time threat detection, incident response, and coordinated admin and guard workflows.

## Overview

This project helps campuses monitor safety events using computer vision and a full-stack dashboard.  
It detects and manages incidents such as:

- Weapon detection
- Violence detection
- Fire detection
- Suspicious or anomaly activity

The system includes authentication, live alerts, reporting, guard status management, and multilingual assistant support.

## 📸 System Workflow & Project Results

Here is the end-to-end operational flow of the AI Campus Security Dashboard:

### 1. Secure Access (Landing Page)
Role-based portal for Administrators and Guards featuring OTP-based WhatsApp authentication.
<img width="600" alt="Landing_Page" src="https://github.com/user-attachments/assets/c38f8057-f1db-4314-acc3-887217af271e" />

### 2. The Command Center (Live Object Detection)
The Admin dashboard where YOLOv8m detections (weapons, fire, violence) arrive as pending alerts for rapid visual verification.
<img width="600" alt="Object Detection   Real Time Alert Notification" src="https://github.com/user-attachments/assets/dbc4f4ac-b49a-4714-ae26-c2c36b2a5930" />

### 3. Guard Operations (Field Dashboard)
A distraction-free interface where on-duty guards view confirmed threats and manage their language preferences (English, Hindi, Marathi).
<img width="600" alt="Gaurd_Dasbord   Multi-language" src="https://github.com/user-attachments/assets/d43af973-eb93-4a93-9211-53c1f559ee6a" />

### 4. Automated Field Dispatch (WhatsApp Alerts)
Critical threats are instantly pushed to the guard's phone via WhatsApp, complete with a strict escalation loop and live GPS sharing capabilities.
<img width="300" alt="Threat alert   Responding" src="https://github.com/user-attachments/assets/d8fbca71-b295-40ab-8265-978f67bb786c" />

## Key Features

- Real-time AI-based threat detection from camera streams
- Admin and guard role-based access workflows
- OTP-based authentication and secure login
- Incident review, confirmation, and reporting flow
- WhatsApp and email notification support
- Optional chatbot support using Gemini
- Multilingual experience: English, Hindi, Marathi

## Tech Stack

- Backend: FastAPI, Python, MongoDB Motor, OpenCV, Ultralytics
- Frontend: React, TypeScript, Vite
- Database: MongoDB
- Integrations: WAHA WhatsApp API, SMTP email, Gemini API optional

## Project Structure

    AI Campus Security Monitoring System/
    ├── Backend/
    │   ├── main.py
    │   ├── database.py
    │   ├── requirements.txt
    │   ├── routers/
    │   ├── Models/
    │   └── utils/
    ├── Frontend/
    │   ├── src/
    │   ├── package.json
    │   └── vite.config.ts
    ├── package.json
    └── test_gemini.py

## Prerequisites

- Python 3.10 or higher
- Node.js 18 or higher
- MongoDB running locally or remotely
- Optional WAHA service for WhatsApp workflows
- Optional Gemini API key for chatbot features

## Environment Setup

1. Keep local runtime variables in .env
2. Never commit .env to GitHub
3. Create Backend/.env.example with placeholder values for contributors

Typical required variables:

- MONGO_URL
- DB_NAME
- SECRET_KEY
- MAIL_USERNAME
- MAIL_PASSWORD
- WAHA_API_URL
- WAHA_API_KEY
- GEMINI_API_KEY optional

## Run Backend

1. Install dependencies

    pip install -r requirements.txt

2. Start API server

    uvicorn Backend.main:app --reload --host 0.0.0.0 --port 8000

Backend URL: http://127.0.0.1:8000

## Run Frontend

1. Move to frontend folder

    cd Frontend

2. Install dependencies

    npm install

3. Start development server

    npm run dev

## Security and Publishing Notes

Before publishing this repository:

- Add and verify root .gitignore
- Ensure .env is ignored
- Exclude runtime data folders
- Exclude local model files if large or private
- Do not upload sessions, captures, exports, or secrets

## License

MIT License is recommended for open collaboration.

