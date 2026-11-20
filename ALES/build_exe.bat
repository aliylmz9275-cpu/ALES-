@echo off
chcp 65001 >nul
title ALES - Tek Dosya EXE
color 0B
setlocal

REM =====================================================================
REM  build_exe.bat -- ALES'i TEK bir .exe olarak paketler.
REM
REM  build.bat'tan FARKI:
REM    build.bat     -> ales-backend.exe + Electron kabugu + NSIS kurulumu
REM                     ("release\ALES Setup 3.0.0.exe")      = IKI parca
REM    build_exe.bat -> "backend-dist\ALES.exe"               = TEK parca
REM                     arayuz exe'nin icinde; cift tiklayinca tarayici acilir
REM  Ikisi birbirine dokunmaz, ikisi de calisir; istedigini kullan.
REM
REM  Sessiz/otomatik derleme:  set ALES_BUILD_NOPAUSE=1 ^& build_exe.bat
REM =====================================================================

cd /d "%~dp0"
if "%ALES_BUILD_NOPAUSE%"=="1" set _NOPAUSE=1

echo.
echo  ============================================
echo    ALES v3.0  --  TEK DOSYA EXE
echo  ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (echo [!] Python bulunamadi. python.org'dan kurun. & if not defined _NOPAUSE pause & exit /b 1)

node --version >nul 2>&1
if errorlevel 1 (echo [!] Node.js bulunamadi ^(arayuzu derlemek icin sart^). & if not defined _NOPAUSE pause & exit /b 1)

echo [1/4] PyInstaller kontrolu...
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 pip install pyinstaller==6.20.0 -q
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (echo [!] PyInstaller kurulamadi. & if not defined _NOPAUSE pause & exit /b 1)

echo [2/4] Arayuz derleniyor  ^(vite -^> dist\^)...
REM NEDEN "cd frontend" ve kokten "npm run build:frontend" DEGIL:
REM bu makinede kok node_modules\.bin icinde .cmd kisayolu YOK (yalnizca
REM uzantisiz POSIX shim'leri var -- npm install muhtemelen bash/WSL
REM altinda yapildi). npm'in Windows'taki varsayilan kabugu cmd.exe ve
REM cmd.exe bir dosyayi ancak PATHEXT uzantilarindan biriyle calistirir,
REM yani uzantisiz "vite" shim'ini GOREMEZ -> "vite taninmiyor" hatasi.
REM frontend\node_modules\.bin\vite.cmd ise mevcut, o yuzden oradan
REM calistiriyoruz. Cikti yeri ayni: vite.config.js outDir '../dist'.
REM
REM Once index.html'i SILIYORUZ: dist\ icinde eski bir derleme duruyor
REM olabilir; silmezsek "dosya var" kontrolu basarisiz derlemeyi de
REM basarili sanip BAYAT arayuzu pakete gomeriz.
if exist "dist\index.html" del /q "dist\index.html"
cd frontend
call npm run build
cd ..
if not exist "dist\index.html" call npm run build:frontend
if not exist "dist\index.html" (echo [!] Arayuz derlenemedi. "cd frontend ^&^& npm install" calistirip tekrar deneyin. & if not defined _NOPAUSE pause & exit /b 1)

echo [3/4] ALES.exe olusturuluyor  ^(birkac dakika surer^)...
python -m PyInstaller ALES.spec --noconfirm --distpath backend-dist --workpath backend\build
if errorlevel 1 (echo [!] PyInstaller basarisiz. & if not defined _NOPAUSE pause & exit /b 1)
if not exist "backend-dist\ALES.exe" (echo [!] ALES.exe olusmadi. & if not defined _NOPAUSE pause & exit /b 1)

echo [4/4] Kalici klasorler exe'nin yanina kopyalaniyor...
REM NEDEN pakete gomulmuyor: --onefile verisi her acilista GECICI bir klasore
REM acilir ve kapanista silinir. skills/ ve plugins/ ise YAZILABILIR ve
REM KALICI olmali (ogrenilen beceriler, kullanicinin ekledigi eklentiler).
REM skills_engine._skills_dir() ve plugin_loader._plugins_dir() zaten
REM exe'nin YANINDAKI klasore bakiyor -- pakete gomulse kullanicinin
REM ekledigi eklentiler gorunmez olurdu.
if exist "backend\skills"  xcopy /E /I /Y "backend\skills"  "backend-dist\skills"  >nul
if exist "backend\plugins" xcopy /E /I /Y "backend\plugins" "backend-dist\plugins" >nul

echo.
echo  ============================================
echo    TAMAM
echo.
echo    Dosya    : backend-dist\ALES.exe
echo    Kullanim : cift tikla; siyah pencere ACILMAZ, tarayici acilir
echo               ^(acilmazsa elle: http://localhost:8000^)
echo    Gunluk   : backend-dist\ALES_log.txt  ^(acilis hatalari burada^)
echo    Durdurma : Gorev Yoneticisi ^> Ayrintilar ^> ALES.exe ^> Gorevi sonlandir
echo               ^(konsol istiyorsan ALES.spec icinde CONSOLE = True^)
echo  ============================================
echo.
if not defined _NOPAUSE explorer backend-dist
if not defined _NOPAUSE pause
endlocal
