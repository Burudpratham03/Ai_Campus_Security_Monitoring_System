import uvicorn
import os
import sys
import asyncio
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse

# Add current directory to path for imports
current_dir = Path(__file__).parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

# Try to import from the Backend package first, then fallback only when package
# path resolution itself is the problem. Do not hide real dependency errors.
try:
    from Backend.database import connect_to_mongo, close_mongo_connection, DatabaseUnavailableError
    from Backend.routers import auth, camera, reports, guard_duty, role_auth, whatsapp, admin_notifications
except ModuleNotFoundError as e:
    missing = str(getattr(e, "name", "") or "")
    package_path_missing = missing in {
        "Backend",
        "Backend.database",
        "Backend.routers",
    }
    if not package_path_missing:
        print(f"[ERROR] Failed to import required modules: {e}")
        raise

    try:
        from database import connect_to_mongo, close_mongo_connection, DatabaseUnavailableError
        from routers import auth, camera, reports, guard_duty, role_auth, whatsapp, admin_notifications
    except ImportError as inner:
        print(f"[ERROR] Failed to import required modules: {inner}")
        raise

# Chatbot router is optional so core backend can run without Gemini dependencies.
chat = None
try:
    from Backend.routers import chat as _chat
    chat = _chat
except ModuleNotFoundError as e:
    if str(getattr(e, "name", "") or "") not in {"google", "google.generativeai"}:
        raise
    print("[WARN] Chat router disabled: install google-generativeai to enable chatbot endpoints.")
except ImportError:
    try:
        from routers import chat as _chat
        chat = _chat
    except ModuleNotFoundError as e:
        if str(getattr(e, "name", "") or "") not in {"google", "google.generativeai"}:
            raise
        print(
            "[WARN] Chat router disabled: install google-generativeai to enable chatbot endpoints.")


app = FastAPI(title="AI Campus Security System")
_db_connected = False

# Allow all local development origins so the frontend can run on any port (5173, 5174, etc.)
# In production this should be tightened to specific domains.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # permit any origin during dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    global _db_connected
    try:
        await connect_to_mongo()
        _db_connected = True
    except Exception as exc:
        _db_connected = False
        allow_without_db = str(
            os.getenv("ALLOW_START_WITHOUT_DB", "true")
        ).strip().lower() in {"1", "true", "yes", "on"}
        print(f"[DB][WARN] Mongo startup failed: {exc}")
        if not allow_without_db:
            raise
        print("[DB][WARN] Continuing startup without database because ALLOW_START_WITHOUT_DB is enabled.")
    try:
        camera._set_app_loop(asyncio.get_running_loop())
    except Exception:
        pass


@app.on_event("shutdown")
async def shutdown_event():
    await close_mongo_connection()


app.include_router(auth.router)
app.include_router(role_auth.router)
app.include_router(camera.router)
app.include_router(reports.router)
if chat is not None:
    app.include_router(chat.router)
app.include_router(guard_duty.router)
app.include_router(whatsapp.router)
app.include_router(admin_notifications.router)


@app.exception_handler(DatabaseUnavailableError)
async def database_unavailable_handler(request: Request, _: DatabaseUnavailableError):
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Database is unavailable. Check MongoDB connectivity and TLS settings.",
            "path": request.url.path,
        },
    )


@app.get("/file/{file_path:path}")
async def serve_file(file_path: str):
    """Serve captured frame files from the captures directory."""
    # Construct the full file path and sanitize it
    base_path = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.normpath(
        os.path.join(base_path, "captures", file_path))

    # Security check: ensure the path is within the captures directory
    if not full_path.startswith(os.path.normpath(os.path.join(base_path, "captures"))):
        return {"error": "Unauthorized path"}

    # Check if file exists
    if os.path.isfile(full_path):
        return FileResponse(full_path, media_type="image/jpeg")

    return {"error": "File not found"}


@app.get("/")
async def root():
    return {
        "status": "System Online",
        "database": "connected" if _db_connected else "disconnected",
    }


if __name__ == "__main__":
    # When running this file directly, use the Backend package path
    uvicorn.run("Backend.main:app", host="0.0.0.0", port=8000, reload=True)
