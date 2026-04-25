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

## Suggested GitHub Topics

fastapi, react, typescript, mongodb, computer-vision, ai, security-monitoring, campus-security, surveillance, incident-response

## License

MIT License is recommended for open collaboration.

---

If you want, I can also give you:
1. a short recruiter-style README version, and  
2. a polished README with badges, screenshots, and API endpoint table.
