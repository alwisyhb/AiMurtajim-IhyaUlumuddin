import sys
import os
import urllib.parse
from pathlib import Path

# Set up project root and app paths
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

APP_DIR = ROOT_DIR / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from app.main import app

# Pure ASGI Middleware to dynamically restore the original request path from Vercel rewrite
class AsgiVercelPathMiddleware:
    def __init__(self, asgi_app):
        self.asgi_app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            query_bytes = scope.get("query_string", b"")
            query_str = query_bytes.decode("utf-8") if query_bytes else ""
            parsed = urllib.parse.parse_qs(query_str)
            
            orig_path = parsed.get("__orig_path__", [""])[0]
            if orig_path:
                if not orig_path.startswith("/"):
                    orig_path = "/" + orig_path
                scope["path"] = orig_path
                
                # Remove __orig_path__ from query string so endpoints receive clean parameters
                del parsed["__orig_path__"]
                new_q = "&".join(
                    f"{urllib.parse.quote(k)}={urllib.parse.quote(v)}"
                    for k, vals in parsed.items()
                    for v in vals
                )
                scope["query_string"] = new_q.encode("utf-8")
            elif scope.get("path") in ("/api/index.py", "/api/index", "/api"):
                scope["path"] = "/"

        await self.asgi_app(scope, receive, send)

# Add middleware directly to the FastAPI instance so app is a valid FastAPI object
app.add_middleware(AsgiVercelPathMiddleware)
