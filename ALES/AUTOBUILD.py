"""
AUTOBUILD.py — ALES: test et, derle, paketle. TEK KOMUT, TEK GUNLUK.

NEDEN BATCH DEGIL PYTHON:
  Ilk surum bir .bat dosyasiydi ve ANINDA kapaniyordu. Sebep tam olarak
  suydu: Windows'ta `npm` bir .cmd dosyasidir. Bir .bat icinden baska bir
  .bat'i `call` OLMADAN cagirirsan denetim bir daha GERI DONMEZ — cocuk
  betik ebeveyni degistirir. Yani `npm --version` satiri npm surumunu
  yazdirip butun betigi sonlandiriyordu (gunlukte son satir "11.13.0"idi).
  Python'da boyle bir tuzak yok: her adim subprocess ile calisir ve
  donus kodu elimize gelir.

TASARIM:
  * Her adim gunluge "RESULT=" satiri yazar. Boylece bir bakista hangi
    adimda kaldigi gorulur.
  * TESTLER BASARISIZ OLSA DA DEVAM EDILIR. Amac tek gecişte hem test
    tablosunu hem paketleme sonucunu gormek; testi duzeltip yeniden
    kosmak icin butun paketlemeyi bastan beklemek gerekmesin.
  * Bir URUN dosyasi uretilmediyse (dist/index.html, ales-backend.exe,
    release/ALES.exe) adim BASARISIZ sayilir — donus kodu 0 olsa bile.
    Sebep: electron-builder eksik bir extraResources kaynagini SESSIZCE
    atlar, "file source doesn't exist" yazar ve 0 ile ciker. Donus koduna
    guvenirsek "derlendi" der, kullanici cift tiklayinca "backend
    bulunamadi" alir. Bu yuzden urunu DOSYA olarak dogruluyoruz.
"""
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")
FRONTEND = os.path.join(ROOT, "frontend")
LOG_PATH = os.path.join(ROOT, "autobuild.log")

# ── ALT SUREC ORTAMI: UTF-8 ZORUNLU ────────────────────────────────────
# Windows'ta bir Python alt sureci ciktisi DOSYAYA YONLENDIRILDIGINDE
# stdout kodlamasini cp1252 secer. Uretim kodu ise "❌" (U+274C) isaretini
# HATA PROTOKOLU olarak kullaniyor: agent_jit.py:745 `f"❌ {tool}: {e}"`
# yaziyor, main.py:2435 `startswith(("❌","Hata","HATA"))` ile okuyup araci
# basarisiz sayiyor. cp1252'de bu karakterin karsiligi YOK, dolayisiyla o
# metni YAZDIRAN test UnicodeEncodeError ile coker (olculen: 88 gecti, 1
# kaldi — "agent_jit cizge yurutme").
#
# TESTI ASCII'ye CEVIRMEK YANLIS OLURDU: hata isareti kozmetik degil, iki
# modul arasindaki gercek bir sozlesme. Duzeltilecek yer kodlama, isaret
# degil. Ayrica bu ayar gunlukteki "·" bozulmasini da (cp1252 0xB7 -> UTF-8
# okunusunda "�") ortadan kaldirir, yani gunluk artik gercekten okunur.
_ENV = dict(os.environ)
_ENV["PYTHONIOENCODING"] = "utf-8"
_ENV["PYTHONUTF8"] = "1"

# Adim adi -> baslangic numarasi. --from ile bir adimdan devam edilebilir
# (npm install bir kez basardiysa ikinci kosuda tekrar beklemeye gerek yok).
#
# VARSAYILAN 0, 1 DEGIL. Onceki varsayilan "1"di ve `if step < FIRST`
# kosulu 0. adimi HER KOSUDA atliyordu -- yani arac surumleri hic
# yazilmiyor ve daha kotusu "PyInstaller hazir" (pip install pyinstaller)
# adimi HIC CALISMIYORDU. Olculdu (autobuild.log, 2026-09-08 09:03 kosusu):
# ozette "[0] PyInstaller hazir  SKIPPED". Bu makinede PyInstaller kurulu
# oldugu icin farkedilmedi; PyInstaller'i olmayan bir makinede ise 5. adim
# "python -m PyInstaller" ile patlardi ve sebebi gunlukte gorunmezdi.
FIRST = int(next((a.split("=", 1)[1] for a in sys.argv[1:]
                  if a.startswith("--from=")), "0"))

_log = open(LOG_PATH, "w", encoding="utf-8", errors="replace")
_results = []


def say(msg):
    """Hem konsola hem gunluge. Konsol kod sayfasi ASCII disini
    kaldiramayabilir, o yuzden yazdirilan metinler ASCII."""
    line = str(msg)
    try:
        print(line, flush=True)
    except Exception:
        pass
    _log.write(line + "\n")
    _log.flush()


def run(step, title, cmd, cwd=None, produces=None, fatal=True,
        timeout=3600):
    """Tek adim. `produces` verilmisse o dosya GERCEKTEN olusmali."""
    if step < FIRST:
        say("")
        say("[STEP %d] %s -- ATLANDI (--from=%d)" % (step, title, FIRST))
        _results.append((step, title, "SKIPPED"))
        return True

    say("")
    say("=" * 68)
    say("[STEP %d] %s" % (step, title))
    say("  cmd: %s" % cmd)
    say("  cwd: %s" % (cwd or ROOT))
    say("=" * 68)
    _log.flush()

    t0 = time.time()
    try:
        # shell=True: npm/npx .cmd sarmalayicilari ancak boyle cozulur.
        # stdout ve stderr AYNI akisa: hata izleri adimin ciktisiyla
        # ayni yerde dursun, sirasi bozulmasin.
        p = subprocess.run(cmd, shell=True, cwd=cwd or ROOT,
                           stdout=_log, stderr=subprocess.STDOUT,
                           env=_ENV, timeout=timeout)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        say("[STEP %d] ZAMAN ASIMI (%ds)" % (step, timeout))
        rc = -9
    except Exception as e:
        say("[STEP %d] CALISTIRILAMADI: %s: %s" % (step, type(e).__name__, e))
        rc = -8
    _log.flush()
    dt = round(time.time() - t0, 1)

    made = True
    if produces:
        made = os.path.exists(produces)
        say("  urun: %s -> %s" % (produces, "VAR" if made else "YOK"))

    okay = (rc == 0) and made
    verdict = "OK" if okay else "FAIL"
    say("[STEP %d] RESULT=%s exit=%s sure=%ss" % (step, verdict, rc, dt))
    _results.append((step, title, "%s (exit=%s)" % (verdict, rc)))

    if not okay and fatal:
        say("[STEP %d] BU ADIM ZORUNLU — duruluyor." % step)
        return False
    return True


say("=" * 68)
say("ALES AUTOBUILD")
say("root : %s" % ROOT)
say("start: %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
say("=" * 68)

# ── 0: araclar ─────────────────────────────────────────────────────────
run(0, "arac surumleri", "python --version && node --version && "
    "npm --version && python -m pip --version", fatal=False)

# PyInstaller yoksa kur. Zaten varsa pip "already satisfied" der ve hizli
# doner; bu yuzden kosullu dallanmaya gerek yok.
run(0, "PyInstaller hazir", "python -m pip install --disable-pip-version-check "
    "--quiet pyinstaller && python -m PyInstaller --version", fatal=True)

# ── 1: sozdizimi ───────────────────────────────────────────────────────
# ROOT'tan calisiyoruz ve HEM backend HEM kok betikleri derliyoruz.
# py_compile yalnizca AYRISTIRIR (import CALISTIRMAZ), o yuzden calisma
# klasoru onemsiz ve kardes modul cozumlemesi gerekmez.
#
# NEDEN BU LISTE UZADI: eski liste bu oturumda DEGISTIRILEN dosyalarin
# hicbirini icermiyordu (model_registry, model_router, repair_model_chain,
# smoke_test_exe). Sozdizimi kapisi tam olarak en son dokunulan dosyalari
# atliyordu: repair_model_chain.py'deki bir yazim hatasi 1. adimi GECER,
# 7. adimda — kirk dakikalik paketlemeden SONRA — patlardi. Bir sozdizimi
# hatasini bulmanin dogru yeri saniyeler suren bu adimdir.
ok = run(1, "py_compile (sozdizimi)",
         "python -m py_compile "
         "backend/main.py backend/agent_jit.py backend/predictive.py "
         "backend/speculative_cache.py backend/test_new_modules.py "
         "backend/model_registry.py backend/model_router.py "
         "backend/repair_model_chain.py backend/config_manager.py "
         "backend/puter_connector.py "
         "backend/security_shield.py backend/freelance_bridge.py "
         "backend/file_organizer.py backend/report_generator.py "
         "backend/email_assistant.py "
         "smoke_test_exe.py AUTOBUILD.py", cwd=ROOT)
if not ok:
    sys.exit(1)

# ── 1b: JS sozdizimi ───────────────────────────────────────────────────
# NEDEN AYRI BIR KAPI VAR: electron-main.js ve preload.js HICBIR adimda
# ayristirilmiyor. vite yalnizca frontend/src'i derler; public/sw.js'i
# oldugu gibi kopyalar (ayristirmaz); electron-builder ise bu iki dosyayi
# yalnizca pakete koyar, okumaz. Yani buradaki tek bir yazim hatasi 1-7.
# adimlarin HEPSINI gecer ve ancak 8. adimda -- kirk dakikalik paketlemeden
# SONRA, "pencere acilmadi" seklinde -- ortaya cikar. Ayni sozdizimi
# hatasini node --check saniyeler icinde soyler.
#
# fatal=False BILINCLI: bu oturumun amaci elle mudahale olmadan bir EXE
# uretmek. Yeni eklenen bir kapinin arac kaynakli bir kaprisi (BOM, PATH,
# node surumu) saglam bir paketi engellememeli. Hata RESULT= satirinda ve
# ozette gorunur, sonucu da 8. adim zaten yakalar.
run(1, "node --check (JS sozdizimi)",
    "node --check electron-main.js && node --check preload.js && "
    "node --check frontend/public/sw.js",
    cwd=ROOT, fatal=False, timeout=300)

# ── 2: testler ─────────────────────────────────────────────────────────
# fatal=False: test kirmizi olsa da paketlemeye devam. Sonuc gunlukte.
run(2, "test_new_modules.py", "python test_new_modules.py", cwd=BACKEND,
    fatal=False, timeout=900)

# ── 3: frontend ────────────────────────────────────────────────────────
# Eski index.html'i onceden siliyoruz: vite sessizce basarisiz olursa
# "dist var" diye yanlis sonuca varmayalim (bayat dist tuzagi).
_idx = os.path.join(ROOT, "dist", "index.html")
if os.path.exists(_idx):
    try:
        os.remove(_idx)
    except Exception as e:
        say("[STEP 3] eski index.html silinemedi: %s" % e)

ok = run(3, "frontend build (vite)", "npm run build", cwd=FRONTEND,
         produces=_idx, timeout=1200)
if not ok:
    sys.exit(3)

# ── 4: kok node_modules ────────────────────────────────────────────────
# TESHIS (2026-09-08, sayarak dogrulandi): kok node_modules "yarim kurulmus"
# DEGIL, butun .js dosyalari SILINMIS. Olculen:
#     kok      node_modules:    2 .js  /  719 .js.map  /  801 .d.ts
#     frontend node_modules: 3984 .js  / 2018 .js.map   (SAGLAM)
# Yani harita, tip ve json dosyalari yerinde, CALISABILIR javascript yok:
# @electron/get/dist/cjs/ icinde index.d.ts + index.js.map var ama index.js
# YOK; electron-builder/out/cli/ icinde cli.js YOK; electron/dist icinde
# yalnizca bos bir locales/ klasoru var. Bu bir kurulum hatasi imzasi degil,
# kurulum SONRASI silme imzasi (virus tarayici karantinasi / temizlik araci).
#
# ONEMLI SONUC — "npm install" BU ARIZAYI ASLA ONARMAZ:
# her paketin package.json'i dogru surumle yerinde duruyor, bu yuzden npm
# agaci "karsilanmis" sayar, hicbir dosyayi YENIDEN INDIRMEZ ve dogrudan
# postinstall betiklerine gecer. Onceki kosuda tam bu oldu: electron'un
# install.js'i silinmis @electron/get'i require etti ve MODULE_NOT_FOUND
# aldi. Yani onceki basarisizlik bir ag/izin sorunu degildi; npm zaten
# onarmayi denemiyordu. Agaci SILMEK zorunlu.
#
# Neden Python'dan siliyoruz, npm ci'nin kendi silmesine birakmiyoruz:
# onceki kosu "EBUSY: resource busy or locked, rmdir node_modules\esbuild"
# ile iki kez dustu — bir surec agaci kilitliyor. npm bu durumda yeniden
# denemez, biz deniyoruz.
_NM = os.path.join(ROOT, "node_modules")
_cli = os.path.join(_NM, "electron-builder", "out", "cli", "cli.js")
_get = os.path.join(_NM, "@electron", "get", "dist", "cjs", "index.js")
_eexe = os.path.join(_NM, "electron", "dist", "electron.exe")


def _kill_tree_lockers():
    """node_modules'u kilitleyen surecleri kapat.

    GUVENLIK SINIRI — node.exe'yi ADINA GORE OLDURMEK YASAK: bu betigi
    baslatan gelistirme araclari da node uzerinde kosuyor, ad bazli bir
    taskkill kendi oturumumuzu da oldururdu. Bu yuzden node/electron
    yalnizca CALISTIRILABILIRI BU PROJENIN ICINDE ise oldurulur. esbuild
    tek islevli bir derleme yardimcisi, onu adiyla kapatmak guvenli.
    """
    root_l = ROOT.lower()
    killed = []
    try:
        import psutil
    except Exception as e:
        say("  [4a] psutil yok (%s) -- yalnizca esbuild.exe kapatilacak" % e)
        try:
            subprocess.run("taskkill /F /IM esbuild.exe", shell=True,
                           stdout=_log, stderr=subprocess.STDOUT, timeout=60)
        except Exception:
            pass
        return killed

    for p in psutil.process_iter(["name", "exe"]):
        try:
            nm = (p.info.get("name") or "").lower()
            exe = (p.info.get("exe") or "").lower()
            if nm == "esbuild.exe":
                pass                      # tek islevli yardimci: her zaman
            elif nm in ("node.exe", "electron.exe") and exe.startswith(root_l):
                pass                      # bu projenin kendi ikilisi
            else:
                continue                  # DOKUNMA
            p.kill()
            killed.append("%s(pid=%s)" % (nm, p.pid))
        except Exception:
            continue
    if killed:
        say("  [4a] kilit tutan surecler kapatildi: %s" % ", ".join(killed))
        time.sleep(1.5)                   # dosya tanimlayicilari kapansin
    else:
        say("  [4a] kilit tutan surec bulunmadi")
    return killed


def _nuke(path):
    """Salt-okunur / kilitli dosyalari da kaldir; olmuyorsa YANA CEK."""
    import stat

    def _onerr(fn, p, exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            fn(p)
        except Exception:
            pass

    for attempt in (1, 2, 3):
        if not os.path.exists(path):
            return True
        try:
            shutil.rmtree(path, onerror=_onerr)
        except Exception as e:
            say("  [4b] silme denemesi %d: %s" % (attempt, e))
        if not os.path.exists(path):
            say("  [4b] eski agac silindi (deneme %d)" % attempt)
            return True
        time.sleep(2)

    # Silinemedi: adini degistir. npm bos bir node_modules ile temiz
    # baslayabilir; artik kimsenin okumadigi kalinti sonra silinir.
    aside = path + ".broken-" + time.strftime("%Y%m%d-%H%M%S")
    try:
        os.rename(path, aside)
        say("  [4b] silinemedi, YANA CEKILDI -> %s" % aside)
        return True
    except Exception as e:
        say("  [4b] yana cekilemedi de: %s" % e)
        return False


if FIRST <= 4:
    _healthy = all(os.path.exists(f) for f in (_cli, _get, _eexe))
    say("")
    say("[STEP 4] kok node_modules saglik denetimi")
    for lbl, f in (("electron-builder cli.js", _cli),
                   ("@electron/get index.js", _get),
                   ("electron.exe", _eexe)):
        say("  %-26s %s" % (lbl, "VAR" if os.path.exists(f) else "YOK"))
    if _healthy:
        say("  -> agac saglam, temizlik gerekmiyor")
    else:
        say("  -> agac SOYULMUS: npm ustune kuramaz, once silinecek")
        _kill_tree_lockers()
        _nuke(_NM)

# npm ci: package-lock.json'dan BIREBIR kurar (kok dizinde var, 201 KB).
# Soyulmus agacin tekrarlamamasi icin dogru komut bu; `npm install`
# mevcut agaci "yeter" sayabilir, `npm ci` sayamaz.
_npm = ("npm ci --no-audit --no-fund"
        if os.path.exists(os.path.join(ROOT, "package-lock.json"))
        else "npm install --no-audit --no-fund")
ok = run(4, "npm kurulum (kok)", _npm, produces=_cli, timeout=2400)

if not ok:
    # npm ci lockfile ile package.json arasinda uyusmazlik gorurse hata
    # verir; o durumda install tek gecerli yol. Bunu SESSIZCE degil,
    # gunluge yazarak deniyoruz.
    say("[STEP 4] npm ci basarisiz -- 'npm install' ile tekrar deneniyor")
    ok = run(4, "npm install (yedek yol)", "npm install --no-audit --no-fund",
             produces=_cli, timeout=2400)
if not ok:
    sys.exit(4)

# Kurulum "0" dondurse bile electron ikilisi inmemis olabilir (postinstall
# ayri bir indirme yapar ve agdan dolayi sessizce eksik kalabilir). Bunu
# 6. adimda "paket uretilmedi" olarak gormek yerine BURADA soyluyoruz.
for lbl, f in (("@electron/get index.js", _get), ("electron.exe", _eexe)):
    say("  kurulum sonrasi %-24s %s"
        % (lbl, "VAR" if os.path.exists(f) else "YOK <-- 6. adim bunu ister"))

# ── 5: backend exe ─────────────────────────────────────────────────────
# Spec kullaniyoruz, bayrak listesi DEGIL: bayrak yolu Faz 2-6 modullerinin
# hicbirini tasimiyordu (importlib ile ADLA yuklendikleri icin statik
# analizde gorunmezler). Spec os.listdir ile hepsini tarar.
_bexe = os.path.join(ROOT, "backend-dist", "ales-backend.exe")
ok = run(5, "PyInstaller backend (ales-backend.spec)",
         'python -m PyInstaller ales-backend.spec --noconfirm '
         '--distpath "%s" --workpath "%s"'
         % (os.path.join(ROOT, "backend-dist"),
            os.path.join(BACKEND, "build")),
         cwd=BACKEND, produces=_bexe, timeout=2400)
if not ok:
    sys.exit(5)

# ── 6: electron paketleme ──────────────────────────────────────────────
# NEDEN "--win portable" ve sadece "--win" DEGIL:
# package.json'da iki hedef var (portable + nsis). Ali'nin istedigi TEK
# cift-tiklanabilir exe = portable. nsis'i de kurmanin iki zarari var:
#   1. electron-builder NSIS ikililerini ilk kullanimda GitHub'dan indirir.
#      Indirme basarisiz olursa butun komut sifir disi doner — hem de
#      ALES.exe COKTAN uretildikten SONRA. O zaman bu adim saglam bir
#      urunu "FAIL" diye isaretler.
#   2. Bosa gecen sure: ayni uygulama iki kez paketlenir.
# package.json'a DOKUNMUYORUZ: hedefi komut satirindan kisitliyoruz,
# boylece Ali isterse `npm run build:exe` ile kurulum surumunu de alabilir.
_rexe = os.path.join(ROOT, "release", "ALES.exe")
ok = run(6, "electron-builder --win portable",
         "npx --no-install electron-builder --win portable",
         produces=_rexe, timeout=2400)

# ── 7: model zinciri onarimi ────────────────────────────────────────────
# NEDEN PAKETLEMEDEN SONRA: bu adim KODU degil, %APPDATA%\ALES\
# model_cache.json'daki CALISMA VERISINI onarir — exe'nin icine girmez,
# dolayisiyla sirasi paketlemeyi etkilemez. Ama 8. adimin (sohbet testi)
# anlamli olmasi icin ONDAN once olmali.
#
# Onardigi ariza: 2026-08-26'da ALES kendi koydugu iki yedek yuzunden
# sohbeti kalici olarak oldurmustu (cerebras/gemma-4-31b -> 402,
# groq/allam-2-7b -> arac cagirmiyor). fatal=False: ag/kota sorunu
# paketlemeyi gecersiz kilmaz, yalnizca sohbet testi kirmizi olur.
run(7, "model zinciri onarimi", "python repair_model_chain.py",
    cwd=BACKEND, fatal=False, timeout=600)

# ── 8: paketlenmis uygulamayi GERCEKTEN dene ────────────────────────────
# "electron-builder 0 dondu" ile "uygulama calisiyor" ayni sey DEGIL.
# Tek kanit calistirip cevabina bakmak. fatal=False: kirmizi bir asama
# rapora girsin, betik yine ozeti yazsin.
run(8, "paketlenmis exe duman testi", "python smoke_test_exe.py",
    fatal=False, timeout=1200)

# ── 9: ozet ────────────────────────────────────────────────────────────
say("")
say("=" * 68)
say("OZET")
say("=" * 68)
for step, title, verdict in _results:
    say("  [%d] %-38s %s" % (step, title, verdict))
say("")
for label, path in (("dist/index.html", _idx),
                    ("backend-dist/ales-backend.exe", _bexe),
                    ("release/ALES.exe", _rexe)):
    if os.path.exists(path):
        say("  %-32s %d bayt" % (label, os.path.getsize(path)))
    else:
        say("  %-32s YOK" % label)
say("")
say("finished: %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
_log.close()
sys.exit(0 if os.path.exists(_rexe) else 6)
