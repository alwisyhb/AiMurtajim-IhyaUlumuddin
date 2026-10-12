import sys
import os
import traceback
from pathlib import Path

# Add project root and app directory to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

APP_DIR = ROOT_DIR / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

try:
    from app.main import app
except Exception:
    err_tb = traceback.format_exc()
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    app = FastAPI()
    @app.get("/{full_path:path}")
    def err_page(full_path: str = ""):
        return HTMLResponse(f"<h2>Server Initialization Error:</h2><pre>{err_tb}</pre>", status_code=500)
