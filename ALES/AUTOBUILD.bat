@echo off
REM ======================================================================
REM  AUTOBUILD.bat - AUTOBUILD.py icin ince sarmalayici.
REM
REM  ONCEKI SURUM ANINDA KAPANIYORDU. Sebep: Windows'ta `npm` bir .cmd
REM  dosyasidir ve bir .bat icinden `call` OLMADAN cagrilan bir .cmd
REM  denetimi GERI VERMEZ -- cocuk betik ebeveyni degistirir. Step 0'daki
REM  ciplak `npm --version` satiri tam bunu yapiyordu: surumu yaziyor,
REM  sonra butun betik bitiyordu (gunlukteki son satir "11.13.0").
REM
REM  Cozum: butun is mantigi AUTOBUILD.py icinde. Python'da bu tuzak yok.
REM  Buradaki tek `call` da npm degil python oldugu icin zorunlu degil,
REM  ama alistirmak icin duruyor.
REM
REM  PENCERE ARTIK KENDILIGINDEN KAPANMAZ: sonda `pause` var. Bir daha
REM  "acildi kapandi, ne oldugunu goremedim" olmasin.
REM ======================================================================
cd /d "%~dp0"
echo [ALES] AUTOBUILD basliyor. Ayrintili gunluk: autobuild.log
echo.
python "%~dp0AUTOBUILD.py" %*
set "RC=%errorlevel%"
echo.
if "%RC%"=="0" goto :done
echo [ALES] BASARISIZ (kod %RC%). autobuild.log dosyasindaki son
echo        "RESULT=FAIL" satiri hangi adimda kaldigini soyler.
goto :hold
:done
echo [ALES] TAMAM. Teslim: release\ALES.exe
:hold
echo.
pause
