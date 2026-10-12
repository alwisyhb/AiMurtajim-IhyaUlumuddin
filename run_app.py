import os
import sys
import socket
import urllib.request
import webbrowser
import threading
import time

# Ensure UTF-8 output on Windows console
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0

def check_al_mutarjim_running(port: int = 8000) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=0.4) as res:
            return res.status == 200
    except Exception:
        return False

def wait_and_open_browser(port: int):
    # Wait until server is up and accepting connections (check every 50ms)
    for _ in range(50):
        if is_port_in_use(port):
            break
        time.sleep(0.05)
    time.sleep(0.05)
    try:
        if sys.platform == 'win32':
            os.system(f"start http://127.0.0.1:{port}")
        else:
            webbrowser.open(f"http://127.0.0.1:{port}")
    except Exception:
        try:
            webbrowser.open(f"http://127.0.0.1:{port}")
        except Exception:
            pass

def main():
    target_port = 8000

    # 1. Check if Al-Mutarjim is ALREADY running on port 8000
    if check_al_mutarjim_running(target_port):
        print("=" * 70)
        print("  Al-Mutarjim Ihya Ulum al-Din")
        print("  Aplikasi Penerjemah Basa Sunda, Logat Pesantren & Syakal Nahwu-Shorof")
        print("=" * 70)
        print(f"  [OK] Server Al-Mutarjim SUDAH BERJALAN di: http://127.0.0.1:{target_port}")
        print("  Membuka halaman web di browser Anda sekarang...")
        print("=" * 70)
        try:
            if sys.platform == 'win32':
                os.system(f"start http://127.0.0.1:{target_port}")
            else:
                webbrowser.open(f"http://127.0.0.1:{target_port}")
        except Exception:
            try:
                webbrowser.open(f"http://127.0.0.1:{target_port}")
            except Exception:
                pass
        
        print("\n  Aplikasi web sudah aktif dan terbuka di browser.")
        print("  Anda dapat meminimalkan jendela ini.")
        print("  Tekan Enter jika ingin menutup jendela ini...")
        try:
            input()
        except Exception:
            time.sleep(3)
        return

    # 2. If port 8000 is occupied by something else, find next available port
    if is_port_in_use(target_port):
        for candidate in [8001, 8002, 8080, 8888]:
            if not is_port_in_use(candidate):
                target_port = candidate
                break

    print("=" * 70)
    print("  Al-Mutarjim Ihya Ulum al-Din")
    print("  Aplikasi Penerjemah Basa Sunda, Logat Pesantren & Syakal Nahwu-Shorof")
    print("=" * 70)
    print(f"Server berjalan di: http://127.0.0.1:{target_port}")
    print("Membuka browser otomatis...")
    print("Tekan Ctrl+C di terminal ini untuk menghentikan server.")
    print("=" * 70)

    # Launch browser after server starts
    threading.Thread(target=wait_and_open_browser, args=(target_port,), daemon=True).start()

    import uvicorn
    app_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app')
    sys.path.insert(0, app_dir)
    uvicorn.run("main:app", host="127.0.0.1", port=target_port, reload=False, app_dir=app_dir)

if __name__ == "__main__":
    main()
