import sys
import os
from pathlib import Path

# Add project root and app directory to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

APP_DIR = ROOT_DIR / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from app.main import app as raw_app

# ASGI Middleware to restore the true incoming request path from Vercel's rewrite headers
class VercelPathMiddleware:
    def __init__(self, asgi_app):
        self.asgi_app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            headers = dict(scope.get("headers", []))
            matched_path = headers.get(b"x-matched-path", b"").decode("utf-8")
            if not matched_path:
                matched_path = headers.get(b"x-invoke-path", b"").decode("utf-8")
            
            if matched_path:
                scope["path"] = matched_path.split("?")[0]
            elif scope.get("path") in ("/api/index.py", "/api/index"):
                scope["path"] = "/"
                
        await self.asgi_app(scope, receive, send)

app = VercelPathMiddleware(raw_app)
