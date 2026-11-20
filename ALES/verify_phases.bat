@echo off
REM ─────────────────────────────────────────────────────────────────
REM  ALES — FAZ 2-6 DOGRULAMA (FINAL BUILD)
REM
REM  Neden var: bu makinede kabuk erisimi kesintili oldugu icin Faz
REM  2-6'da yazilan hicbir satir DERLENEMEDI. Bu dosya, tek cift
REM  tiklamayla o dogrulamayi yapar.
REM
REM  Sira ONEMLI: once sozdizimi (backend hic ayakta olmasa da
REM  calisir), sonra modul yuklenmesi + panel anahtar sozlesmesi,
REM  en sonda canli uclar.
REM ─────────────────────────────────────────────────────────────────
setlocal
cd /d "%~dp0backend"

echo === 1/2  Sozdizimi kontrolu (py_compile) - 23 dosya ===
python -m py_compile main.py config_manager.py tool_router.py ^
 evo_cua_bridge.py openclaw_bridge.py auto_model_discovery.py ^
 batch_inference.py token_optimizer.py speculative_cache.py ^
 contextual_experience_replay.py self_evolution.py reflection_agent.py ^
 darwin_godel.py adaptive_timeouts.py versioned_config.py ^
 mixture_of_agents.py agent_jit.py native_desktop.py self_heal.py ^
 runtime_state.py code_act_executor.py predictive.py fast_path.py ^
 verify_phases.py
if errorlevel 1 (
  echo.
  echo *** DERLEME HATASI - yukaridaki satir dosya ve satir numarasini soyler.
  echo *** Buradan sonrasi anlamsiz; once bunu duzelt.
  goto :end
)
echo     OK - 23 dosyanin tamami derlendi.
echo.

echo === 2/2  Modul + panel sozlesmesi + .env + canli uclar ===
REM py_compile yalnizca SOZDIZIMINI dogrular. verify_phases.py modulleri
REM gercekten yukler, her birinin modul duzeyi stats()/status() cagrisini
REM dener ve YENI PANELLERIN OKUDUGU ANAHTARLARIN var oldugunu denetler.
REM Eksik anahtar hicbir hata uretmez, arayuzde bos satir olarak gorunur -
REM bu yuzden ayrica kontrol ediliyor.
python verify_phases.py
if errorlevel 1 (
  echo.
  echo *** Yukarida en az bir basarisiz kontrol var.
)

:end
echo.
echo Sonra sirasiyla:
echo     cd frontend  ^&^&  npm run build          ^(5 yeni panel^)
echo     cd backend   ^&^&  python test_new_modules.py   ^(davranis testi^)
echo     build_exe.bat                             ^(backend-dist\ALES.exe^)
pause
