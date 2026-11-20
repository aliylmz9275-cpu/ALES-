@echo off
title ALES - Baslatiliyor...
color 0B

echo.
echo  ██████████████████████████████████
echo  █                                █
echo  █         A L E S  v2.0          █
echo  █   Advanced Logic Exec System   █
echo  █                                █
echo  ██████████████████████████████████
echo.

:: Backend klasörüne git
cd /d "%~dp0backend"

:: .env var mı kontrol et
if not exist ".env" (
    echo [!] .env dosyasi bulunamadi!
    echo [!] .env.example dosyasini kopyalayip .env yap ve key gir.
    pause
    exit
)

:: Python var mı kontrol et
python --version >nul 2>&1
if errorlevel 1 (
    echo [!] Python bulunamadi! python.org'dan yukle.
    pause
    exit
)

:: Paketleri yükle
echo [*] Gerekli paketler kontrol ediliyor...
pip install -r requirements.txt -q

:: Frontend klasörüne git ve bağımlılıkları yükle
cd /d "%~dp0frontend"
if not exist "node_modules" (
    echo [*] Frontend paketleri yukleniyor...
    call npm install
)

:: Backend'i arka planda başlat
echo [*] ALES backend baslatiliyor...
cd /d "%~dp0backend"
start /min cmd /c "python main.py"

:: Birkaç saniye bekle
timeout /t 3 /nobreak >nul

:: Frontend'i başlat
echo [*] ALES arayuz baslatiliyor...
cd /d "%~dp0frontend"
start /min cmd /c "npm run dev"

:: Birkaç saniye bekle
timeout /t 3 /nobreak >nul

:: Tarayıcıda aç
echo [*] Tarayici aciliyor...
start http://localhost:5173

echo.
echo  [OK] ALES calisiyor!
echo  [OK] Tarayici: http://localhost:5173
echo  [OK] Backend:  http://localhost:8000
echo  [OK] Telefon:  Ayni wifi'deysen http://BILGISAYAR_IP:5173
echo.
echo  Kapatmak icin bu pencereyi kapat.
pause
