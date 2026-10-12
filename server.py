import os
import sys
from pathlib import Path
import gradio as gr
from fastapi.staticfiles import StaticFiles

# Tambahkan direktori root ke sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.main import app as fastapi_app, static_dir

# 1. Inisialisasi Gradio Blocks
with gr.Blocks(title="Al-Mutarjim Ihya' 'Ulum al-Din") as demo:
    pass

# 2. Masukkan seluruh rute FastAPI (termasuk '/' dan seluruh '/api/*') ke server utama
for r in reversed(fastapi_app.routes):
    demo.app.routes.insert(0, r)

# 3. Pasang direktori static
try:
    demo.app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
except Exception:
    pass

# 4. Jalankan aplikasi pada port 7860 untuk Hugging Face Spaces
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    demo.launch(server_name="0.0.0.0", server_port=port)
