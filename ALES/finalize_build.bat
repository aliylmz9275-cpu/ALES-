@echo off
REM ═════════════════════════════════════════════════════════════════
REM  ALES — FINAL BUILD: derle, dogrula, test et, arayuzu kur, EXE yap
REM
REM  Bu dosya, tek cift tiklamayla su sirayi yurutur:
REM     1. sozdizimi (py_compile)
REM     2. backend'i BASLAT (arka planda, ayri pencere)
REM     3. modul + panel sozlesmesi + canli uclar (verify_phases.py)
REM     4. davranis testleri (test_new_modules.py)
REM     5. backend'i DURDUR      <-- ATLANAMAZ, asagida nedeni var
REM     6. arayuz derlemesi (vite)
REM     7. ALES.exe paketleme
REM     8. EXE'yi calistir, gunlugu oku, durdur
REM
REM  5. ADIM NEDEN ZORUNLU: hem "python main.py" hem ALES.exe 8000
REM  portuna baglaniyor. Dev backend acik kalirsa EXE portu tutamaz,
REM  hemen kapanir ve saglam bir EXE bozuk gorunur. Sirayla acilirlar.
REM
REM  Her adim BIR SONRAKINE gecmeden once hata kontrolu yapar; ilk
REM  "*** " satiri nerede durdugunu soyler.
REM ═════════════════════════════════════════════════════════════════
setlocal
cd /d "%~dp0"
set LOG=%~dp0finalize_build_log.txt
echo ALES finalize_build  %DATE% %TIME% > "%LOG%"

echo.
echo ================= 1/8  Sozdizimi (py_compile) =================
cd backend
python -m py_compile main.py config_manager.py tool_router.py ^
 evo_cua_bridge.py openclaw_bridge.py auto_model_discovery.py ^
 batch_inference.py token_optimizer.py speculative_cache.py ^
 contextual_experience_replay.py self_evolution.py reflection_agent.py ^
 darwin_godel.py adaptive_timeouts.py versioned_config.py ^
 mixture_of_agents.py agent_jit.py native_desktop.py self_heal.py ^
 runtime_state.py code_act_executor.py predictive.py fast_path.py ^
 verify_phases.py test_new_modules.py
if errorlevel 1 (
  echo *** DERLEME HATASI - yukaridaki satir dosya ve satir numarasini soyler.
  echo *** Sonraki adimlar anlamsiz; once bunu duzelt.
  goto :end
)
echo     OK - 25 dosya derlendi.

echo.
echo ================= 2/8  Backend baslatiliyor ===================
REM Ayri pencerede, kendi gunlugune yazarak. Pencere basligi ONEMLI:
REM 5. adimda SADECE bu sureci durdurmak icin baslikla filtreliyoruz
REM (taskkill /IM python.exe kullanicinin baska Python islerini de
REM oldururdu - yapilmaz).
start "ALES_DEV_BACKEND" /min cmd /c "python main.py > ..\backend_run_log.txt 2>&1"
echo     Baslatildi. Uvicorn + 40'tan fazla modul yukleniyor, bekleniyor...
REM 3 saniye YETMEZ: bu surec long_term_memory (sqlite), playwright,
REM model_registry ve tum Faz 2-6 modullerini yukluyor. Erken sorarsak
REM saglam bir backend "kapali" gorunur.
timeout /t 12 /nobreak >nul
python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/modes',timeout=20); print('     Backend ayakta.')" 2>nul
if errorlevel 1 (
  echo     Henuz cevap yok, 15 saniye daha bekleniyor...
  timeout /t 15 /nobreak >nul
  python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/modes',timeout=20); print('     Backend ayakta.')" 2>nul
  if errorlevel 1 (
    echo *** Backend acilmadi. Sebep: %~dp0backend_run_log.txt
    echo *** En sik neden: 8000 portu baska bir surecte dolu.
    goto :stopbackend
  )
)

echo.
echo ========= 3/8  Modul sozlesmesi + .env + canli uclar =========
python verify_phases.py
if errorlevel 1 echo     *** verify_phases.py basarisiz kontrol bildirdi (yukari bak).

echo.
echo ============ 4/8  Davranis testleri (44+ kontrol) ============
python test_new_modules.py
if errorlevel 1 echo     *** test_new_modules.py basarisiz test bildirdi (OZET bolumune bak).

:stopbackend
echo.
echo ============= 5/8  Backend durduruluyor (port 8000) ==========
taskkill /FI "WINDOWTITLE eq ALES_DEV_BACKEND*" /T /F >nul 2>&1
if errorlevel 1 (
  echo     Baslikla bulunamadi; port 8000'i tutan sureci ariyorum...
  for /f "tokens=5" %%P in ('netstat -ano ^| findstr "LISTENING" ^| findstr ":8000"') do taskkill /PID %%P /F >nul 2>&1
)
timeout /t 3 /nobreak >nul
echo     Port serbest (EXE testi icin sart).

echo.
echo ================= 6/8  Arayuz derlemesi (vite) ===============
cd /d "%~dp0"
REM Once eski ciktiyi siliyoruz: silmezsek basarisiz bir derlemeden
REM sonra BAYAT arayuz pakete gomulur ve fark edilmez.
if exist "dist\index.html" del /q "dist\index.html"
cd frontend
call npm run build
cd /d "%~dp0"
if not exist "dist\index.html" (
  echo *** Arayuz derlenemedi. Hata metni YUKARIDA; su uc sebep disinda
  echo *** bir sey pek gorulmez:
  echo ***   1^) JSX sozdizimi  -^> vite dosya:satir:kolon soyler, oraya bak
  echo ***   2^) eksik paket    -^> cd frontend ^&^& npm install
  echo ***   3^) "Failed to resolve ./manifest.json from index.html"
  echo ***      -^> frontend\index.html icinde ./manifest.json ve
  echo ***         ./icon-192.png dosyalari frontend\public\ altinda.
  echo ***         Cozum: o iki href'i /manifest.json ve /icon-192.png
  echo ***         yap ^(bas taksim^). DIKKAT: vite.config.js base './'
  echo ***         oldugu icin bu degisiklik yalnizca ALES.exe/tarayici
  echo ***         icin gecerlidir; Electron file:// kabugunda ikonu
  echo ***         bulamaz hale gelir ^(islev kaybi yok, yalnizca ikon^).
  goto :end
)
echo     OK - dist\index.html olustu.

echo.
echo ================= 7/8  ALES.exe paketleme ====================
set ALES_BUILD_NOPAUSE=1
call build_exe.bat
if not exist "backend-dist\ALES.exe" (
  echo *** ALES.exe olusmadi. PyInstaller ciktisini yukarida oku.
  goto :end
)
echo     OK - backend-dist\ALES.exe olustu.

echo.
echo ================= 8/8  EXE acilis denemesi ===================
REM 5 saniye YETMEZ: --onefile paketi her acilista kendini gecici bir
REM klasore ACAR (ilk acilis 20-40 sn surebilir). Erken oldururuz ve
REM calisan bir EXE "bozuk" gorunur. Bu yuzden once /modes ucunu
REM yokluyoruz, sonra durduruyoruz.
if exist "backend-dist\ALES_log.txt" del /q "backend-dist\ALES_log.txt"
start "ALES_EXE_TEST" backend-dist\ALES.exe
timeout /t 30 /nobreak >nul
python -c "import json,urllib.request as u; d=json.load(u.urlopen('http://127.0.0.1:8000/modes',timeout=25)); print('     EXE CALISIYOR - /modes cevap verdi')" 2>nul
if errorlevel 1 (
  echo     Henuz cevap yok, 30 saniye daha ^(ilk acilis yavastir^)...
  timeout /t 30 /nobreak >nul
  python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/modes',timeout=25); print('     EXE CALISIYOR - /modes cevap verdi')" 2>nul
  if errorlevel 1 echo     *** EXE cevap vermedi. Gunluk: backend-dist\ALES_log.txt
)
echo.
echo     --- backend-dist\ALES_log.txt (son satirlar) ---
if exist "backend-dist\ALES_log.txt" (
  python -c "import io;p=r'backend-dist\ALES_log.txt';L=io.open(p,encoding='utf-8',errors='replace').read().splitlines();[print('     '+x) for x in L[-25:]]"
) else (
  echo     ^(gunluk dosyasi olusmadi^)
)
taskkill /IM ALES.exe /F >nul 2>&1
echo     EXE durduruldu.

:end
echo.
echo ============================================================
echo  BITTI. Yukaridaki "*** " satirlari basarisiz adimlardir.
echo  Hicbiri yoksa: derleme, testler, arayuz ve EXE tamam.
echo.
echo  GEMINI ANAHTARI: elindeki deger bir OAuth belirteci
echo  ^(AQ... / ya29... ile baslar^) ve Gemini REST API'sinde
echo  CALISMAZ. aistudio.google.com/apikey adresinden "AIza..."
echo  ile baslayan bir anahtar al, backend\.env icine yaz:
echo      GEMINI_API_KEY=AIza...
echo  Sonra verify_phases.bat: 7/7 anahtar cozulmeli.
echo ============================================================
pause
