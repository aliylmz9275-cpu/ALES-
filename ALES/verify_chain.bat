@echo off
REM ─────────────────────────────────────────────────────────────────
REM  ALES — model zinciri + arac cagrisi DOGRULAMA
REM
REM  Ne yapar: ONCE dosyalari derler (sozdizimi kontrolu), SONRA
REM  calisan backend'in /diag/chain ucunu cagirip sonucu yazar.
REM
REM  Backend'in AYAKTA olmasi gerekir (yeni zaman asimlari ve cikti
REM  tavanlari icin ALES'i bir kez YENIDEN BASLAT — degerler surec
REM  basinda okunuyor).
REM ─────────────────────────────────────────────────────────────────
setlocal
cd /d "%~dp0backend"

echo === 1/3  Sozdizimi kontrolu (py_compile) ===
python -m py_compile config_manager.py model_router.py main.py diag_chain.py
if errorlevel 1 (
  echo.
  echo *** DERLEME HATASI - yukaridaki satir dosya ve satir numarasini soyler.
  goto :end
)
echo     OK - dort dosya da derlendi.
echo.

echo === 2/3  Saglayici ulasilabilirligi (GET /test-models) ===
python -c "import json,urllib.request as u; print(json.dumps(json.load(u.urlopen('http://127.0.0.1:8000/test-models?timeout=20',timeout=180)),ensure_ascii=False,indent=2))" 2>nul
if errorlevel 1 echo     Backend'e ulasilamadi - ALES calisiyor mu? (http://127.0.0.1:8000)
echo.

echo === 3/3  UCTAN UCA: zincir aciliyor mu + arac cagriliyor mu ===
python -c "import json,urllib.request as u; print(json.dumps(json.load(u.urlopen('http://127.0.0.1:8000/diag/chain',timeout=300)),ensure_ascii=False,indent=2))" 2>nul
if errorlevel 1 (
  echo     Backend'e ulasilamadi VEYA /diag/chain yok.
  echo     /diag/chain yeni eklendi - ALES'i YENIDEN BASLATMAK gerekir.
  echo.
  echo     Backend olmadan calisan bagimsiz teshis:
  echo         python diag_chain.py
)

:end
echo.
echo Bakilacak alan: verdict.all_pass = true  ve  tool_call_test.tool_calls
echo icinde "google_search" gorunmeli.
pause
