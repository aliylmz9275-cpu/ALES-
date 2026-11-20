@echo off
chcp 65001 >nul
title ALES - Build (tek dosya ALES.exe)
color 0B

REM ═════════════════════════════════════════════════════════════════════
REM  ALES — MASAUSTU EXE BUILD  (cift tiklanabilir baslatici)
REM
REM  CIKTI: release\ALES.exe   (tasinabilir/portable, TEK dosya)
REM         cift tiklanir, Python/Node GEREKTIRMEZ, konsol penceresi YOK,
REM         tarayici acilmaz — arayuz Electron'un kendi penceresinde.
REM
REM  ── BU DOSYA ARTIK ISI KENDI YAPMIYOR, AUTOBUILD.py'YE DEVREDIYOR ──
REM  Butun adimlar (araclar, sozdizimi, testler, vite, npm, PyInstaller,
REM  electron-builder, model zinciri, duman testi) AUTOBUILD.py icinde.
REM  Burada yalnizca "cift tikla ve bitir" kolayligi var.
REM
REM  NEDEN DEVREDILDI — bu dosyanin ELLE tuttugu surumu uc yerde
REM  AUTOBUILD.py'den DAHA ZAYIFTI ve ucu de sessiz ariza uretiyordu:
REM
REM  1) "npm install" KOK AGACI ONARAMAZ. Olculdu (2026-09-08): kok
REM     node_modules icinde 2 .js / 719 .js.map / 801 .d.ts var — yani
REM     package.json'lar YERINDE ama calisabilir javascript SILINMIS
REM     (virus tarayici karantinasi imzasi). npm agaci "karsilanmis"
REM     sayar, hicbir dosyayi yeniden indirmez, dogrudan postinstall'a
REM     gecer ve electron'un install.js'i silinmis @electron/get'i
REM     require edip MODULE_NOT_FOUND alir. AUTOBUILD.py once agacin
REM     sagligini UC DOSYAYLA olcuyor, bozuksa siliyor ve `npm ci`
REM     kullaniyor (package-lock.json'dan birebir).
REM
REM  2) "electron-builder --win" IKI hedef kurar (portable + nsis).
REM     NSIS ikilileri ilk kullanimda GitHub'dan indirilir; indirme
REM     dususe gecerse komut sifir disi doner — hem de release\ALES.exe
REM     COKTAN uretildikten SONRA. Eski surum o noktada "*** HATA:
REM     electron-builder" yazip exit /b 1 yapiyordu, yani SAGLAM bir
REM     paketi basarisiz ilan edip dogrulamaya hic gecmiyordu.
REM     AUTOBUILD.py "--win portable" ile yalnizca istenen hedefi kurar.
REM
REM  3) DOGRULAMA YOKTU. "electron-builder 0 dondu" ile "uygulama
REM     calisiyor" ayni sey degil. AUTOBUILD.py sonunda smoke_test_exe.py
REM     kosuyor: exe'yi GERCEKTEN calistirip 8000 portunu, /status'u,
REM     sohbeti, Big ALES ucunu ve masaustu penceresini olcuyor. Ayrica
REM     release\win-unpacked\resources\dist\index.html dosyasinin VAR
REM     oldugunu dogruluyor — puter.js "Unsupported Protocol file://"
REM     duzeltmesi tam olarak o kopyaya bagli, o dosya yoksa pencerede
REM     arayuz yerine 503 JSON cikiyor.
REM
REM  Eski adim adim surum git gecmisinde duruyor; oradaki dort tarihi
REM  duzeltme (spec ile derleme, kosulsuz --collect-all=cerebras,
REM  frontend'den vite cagrisi, portable hedefin one alinmasi) AUTOBUILD.py
REM  ve backend\ales-backend.spec icine TASINDI, kaybolmadi.
REM ═════════════════════════════════════════════════════════════════════

setlocal
cd /d "%~dp0"

echo.
echo  ====================================
echo    ALES - MASAUSTU EXE BUILD
echo  ====================================
echo.

REM Python bu baslaticinin TEK sarti. Node/npm/PyInstaller kontrolleri
REM AUTOBUILD.py'nin 0. adiminda, gunluge yazilarak yapiliyor.
python --version >nul 2>&1
if errorlevel 1 (
  echo  [!] Python bulunamadi.
  echo.
  echo      Bu betik yalnizca BUILD icin Python ister. Uretilen
  echo      release\ALES.exe'nin calismasi icin Python GEREKMEZ.
  echo      python.org'dan kurup "Add python.exe to PATH" secenegini
  echo      isaretle, sonra bu dosyayi yeniden cift tikla.
  echo.
  pause
  exit /b 1
)

echo  Butun adimlar AUTOBUILD.py icinde calisiyor.
echo  Ayrintili gunluk: autobuild.log
echo  Sure: ilk kosuda 10-45 dakika (npm + PyInstaller).
echo.

REM AUTOBUILD.py bir .py dosyasi, .cmd DEGIL -- yani buradaki `call`
REM tuzagi (bir .bat'in baska bir .bat'i call olmadan cagirmasi ve
REM denetimi bir daha geri almamasi) burada YOK. Eski AUTOBUILD.bat tam
REM bu yuzden "acilip aninda kapaniyordu": `npm --version` satiri npm'in
REM .cmd'sine atlayip betigi sonlandiriyordu.
REM
REM %* ile argumanlar aynen geciyor: yarida kalan bir kosuyu
REM   build.bat --from=4
REM ile 4. adimdan devam ettirebilirsin.
python AUTOBUILD.py %*
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
  echo  ====================================
  echo    BUILD TAMAMLANMADI  ^(cikis kodu %RC%^)
  echo  ====================================
  echo.
  echo  autobuild.log dosyasini ac ve "RESULT=FAIL" satirini ara:
  echo  hangi adimda kaldigi orada yaziyor.
  echo.
  if exist "autobuild.log" notepad autobuild.log
  pause
  exit /b %RC%
)

if not exist "release\ALES.exe" (
  echo  ====================================
  echo    UYARI: release\ALES.exe YOK
  echo  ====================================
  echo.
  echo  AUTOBUILD.py 0 dondurdu ama urun dosyasi yerinde degil.
  echo  release klasorunun icerigi:
  if exist "release" (dir /b release) else (echo  ^(release klasoru hic olusmamis^))
  echo.
  pause
  exit /b 6
)

echo  ====================================
echo    TAMAM
echo    Tek dosya : release\ALES.exe
echo  ====================================
echo.
echo  ALES.exe cift tiklanir. Python/Node gerekmez, konsol penceresi
echo  gorunmez, tarayici acilmaz. Ilk acilis 20-40 saniye surebilir:
echo  arka uc exe'si kendini gecici klasore acar.
echo.
echo  Duman testi sonuclari autobuild.log sonunda ("8) ..." bolumu).
echo.
explorer release
pause
