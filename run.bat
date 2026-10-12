@echo off
title Al-Mutarjim Ihya Ulum al-Din
cd /d "%~dp0"

echo ======================================================================
echo   Al-Mutarjim Ihya Ulum al-Din
echo   Penerjemah Basa Sunda, Logat Pesantren dan Syakal Nahwu-Shorof
echo ======================================================================
echo.
echo [1/1] Menjalankan server aplikasi dan membuka browser...
echo (Catatan: Jangan tutup jendela hitam ini selama menggunakan aplikasi)
echo.

python run_app.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ======================================================================
    echo [INFO] Jika terjadi kendala pada Python, pastikan Python sudah terinstal.
    echo Halaman web sudah dibuka di: http://127.0.0.1:8000
    echo ======================================================================
    echo.
    pause
)
