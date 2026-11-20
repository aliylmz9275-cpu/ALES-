"""
smoke_test_exe.py — paketlenmis ALES'i GERCEKTEN dener.

Ali'nin 5. maddesi: ".exe'yi baslat, masaustu penceresi acildigini (tarayici
YOK, konsol YOK), backend'in ayaga kalktigini ve sohbet/araclarin
calistigini dogrula." Bu betik tam bunu yapar ve OLCTUGU seyi yazar:
olcemedigi hicbir sey icin "calisiyor" demez.

NEDEN AYRI BIR BETIK: "electron-builder 0 dondu" ile "uygulama calisiyor"
ayni sey DEGIL. electron-builder eksik bir extraResources kaynagini SESSIZCE
atlar (statOrNull -> null, "file source doesn't exist" yazar, 0 ile ciker).
Yani exe uretilmis olabilir ama icinde backend olmayabilir; kullanici cift
tiklayinca bos pencere gorur. Tek kanit: calistirip cevabina bakmak.

ASAMALAR
  1. Urun dosyalari VAR mi (dosya olarak, boyutuyla)
  2. 8000 portu bos mu
  3. backend-dist\\ales-backend.exe tek basina ayaga kalkiyor mu (/status)
  4. Sohbet gercekten cevap veriyor mu (WebSocket /ws) — 2026-09-05'te
     olen sey buydu, o yuzden asil kontrol bu
  5. Arac cagirma calisiyor mu
  6. release\\ALES.exe masaustu penceresi aciyor mu; KONSOL penceresi
     aciyor mu (acmamali)

KULLANIM:
    python smoke_test_exe.py              # hepsi
    python smoke_test_exe.py --no-gui     # 6. asamayi atla (pencere acmaz)

Cikis kodu: basarisiz asama sayisi (0 = hepsi gecti).
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND_EXE = os.path.join(ROOT, "backend-dist", "ales-backend.exe")
RELEASE_EXE = os.path.join(ROOT, "release", "ALES.exe")
INDEX_HTML = os.path.join(ROOT, "dist", "index.html")
BASE = "http://127.0.0.1:8000"
NO_GUI = "--no-gui" in sys.argv[1:]

PASS, FAIL = [], []


def ok(name, detail=""):
    PASS.append(name)
    print(f"  [OK]   {name}" + (f"  -- {detail}" if detail else ""), flush=True)


def bad(name, why):
    FAIL.append((name, why))
    print(f"  [FAIL] {name}\n         -> {why}", flush=True)


def section(t):
    print(f"\n{'='*70}\n{t}\n{'='*70}", flush=True)


def port_busy(port=8000) -> bool:
    with socket.socket() as s:
        s.settimeout(0.6)
        return s.connect_ex(("127.0.0.1", port)) == 0


# ── 1: urun dosyalari ────────────────────────────────────────────────
section("1) URUN DOSYALARI")
for label, path, min_bytes in (
        ("dist/index.html", INDEX_HTML, 500),
        ("backend-dist/ales-backend.exe", BACKEND_EXE, 20_000_000),
        ("release/ALES.exe", RELEASE_EXE, 50_000_000)):
    if not os.path.exists(path):
        bad(label, "dosya YOK")
        continue
    sz = os.path.getsize(path)
    if sz < min_bytes:
        bad(label, f"dosya var ama sadece {sz} bayt (beklenen > {min_bytes}) "
                   f"— icerik eksik olabilir")
    else:
        ok(label, f"{sz:,} bayt")

# Paketin ICINDEKI iki kaynak: arayuz artik file:// ile DEGIL,
# http://localhost:8000 uzerinden yukleniyor (electron-main.js: loadURL) —
# cunku puter.js file:// kaynaginda "Unsupported Protocol" veriyor. Bunun
# calismasi backend'in derlenmis arayuzu BULMASINA bagli, o da dist/'in
# exe'nin yanina kopyalanmis olmasina. electron-builder eksik bir
# extraResources kaynagini SESSIZCE atlayip 0 ile ciktigi icin bu iki
# dosyanin varligi ayrica olculmek ZORUNDA: yoksa kullanici pencerede
# arayuz yerine JSON hata metni gorur.
_UNP = os.path.join(ROOT, "release", "win-unpacked", "resources")
if os.path.isdir(_UNP):
    for label, rel, min_bytes in (
            ("paket icinde resources/dist/index.html",
             os.path.join("dist", "index.html"), 500),
            ("paket icinde resources/ales-backend.exe",
             "ales-backend.exe", 20_000_000)):
        p = os.path.join(_UNP, rel)
        if not os.path.exists(p):
            bad(label, "YOK — electron-builder bu extraResources girdisini "
                       "atladi (sessizce atlar). Paket calismaz.")
        else:
            ok(label, f"{os.path.getsize(p):,} bayt")
else:
    bad("release/win-unpacked/resources", "klasor YOK — electron paketleme "
        "adimi hic tamamlanmamis olabilir")

if not os.path.exists(BACKEND_EXE):
    print("\nbackend exe olmadan calisma testi yapilamaz. Duruluyor.")
    print(f"\nGECTI: {len(PASS)}  KALDI: {len(FAIL)}")
    sys.exit(len(FAIL) or 1)

# ── 2: port ──────────────────────────────────────────────────────────
section("2) 8000 PORTU")
if port_busy():
    bad("port bos", "8000 portu MESGUL — baska bir ALES/uvicorn zaten "
                    "calisiyor. Onu kapatmadan bu test anlamli degil "
                    "(hangi surumun cevap verdigini bilemeyiz).")
    print(f"\nGECTI: {len(PASS)}  KALDI: {len(FAIL)}")
    sys.exit(len(FAIL))
ok("port bos", "8000 dinlenmiyor")

# ── 3: backend ayaga kalkiyor mu ─────────────────────────────────────
section("3) BACKEND EXE TEK BASINA")
print(f"  baslatiliyor: {BACKEND_EXE}")
print("  (onefile arsivi ilk acilista gecici klasore aciliyor — 30-90s "
      "normal)", flush=True)
proc = subprocess.Popen([BACKEND_EXE], cwd=os.path.dirname(BACKEND_EXE),
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

import httpx

status_json = None
t0 = time.time()
while time.time() - t0 < 150:
    if proc.poll() is not None:
        break
    try:
        r = httpx.get(BASE + "/status", timeout=3.0)
        if r.status_code == 200:
            status_json = r.json()
            break
    except Exception:
        pass
    time.sleep(1.5)

boot_s = round(time.time() - t0, 1)
if proc.poll() is not None:
    bad("backend ayaga kalkti", f"islem {boot_s}s icinde KENDI KAPANDI "
                               f"(exit={proc.returncode}). "
                               f"backend-dist/ALES_log.txt bakilmali.")
elif status_json is None:
    bad("backend ayaga kalkti", f"{boot_s}s icinde /status cevap vermedi")
else:
    ok("backend ayaga kalkti", f"{boot_s}s icinde /status 200")

if status_json is not None:
    # Modul sayilari: "kac modul acik" iddiasini OLCEREK soyluyoruz.
    for ep, label in (("/jit/graphs", "JIT cizge sayaclari"),
                      ("/spec-cache/stats", "SpecCache istatistigi")):
        try:
            r = httpx.get(BASE + ep, timeout=8.0)
            if r.status_code == 200:
                d = r.json()
                keys = ", ".join(list(d)[:6]) if isinstance(d, dict) else str(d)[:80]
                ok(f"{ep} cevap veriyor", keys)
            else:
                bad(f"{ep} cevap veriyor", f"HTTP {r.status_code}")
        except Exception as e:
            bad(f"{ep} cevap veriyor", f"{type(e).__name__}: {e}")

    # ── BIG ALES: "secilebilir mi" iddiasini OLCEREK dogruluyoruz ──────
    # Ali'nin 3. gorevi bunu istiyor. Iki ayri sey var ve ikisi de gerekli:
    #   (a) mod /modes listesinde GORUNUYOR mu -> arayuzdeki mod cubugu
    #       dogrudan bu listeden ciziliyor, yani gorunmuyorsa secilemez;
    #   (b) /big-ales ucu cevap veriyor mu -> Ayarlar panelindeki dugme
    #       bu uctan besleniyor.
    # NOT: gercek bir Puter CAGRISI burada TEST EDILEMEZ — Puter girisi
    # tarayici penceresinde elle yapilan bir adim. Bu yuzden "Big ALES
    # calisiyor" demiyoruz; "secilebilir ve ucu ayakta" diyoruz. Olculmeyen
    # seyi olculmus gibi yazmak bu projede yasak.
    try:
        r = httpx.get(BASE + "/modes", timeout=8.0)
        ids = [m.get("id") for m in (r.json().get("modes") or [])]
        if "big_ales" in ids:
            ok("Big ALES modu secilebilir", "/modes listesinde var (%d mod)"
               % len(ids))
        else:
            bad("Big ALES modu secilebilir", "listede yok: %s" % ids)
    except Exception as e:
        bad("Big ALES modu secilebilir", f"{type(e).__name__}: {e}")
    try:
        r = httpx.get(BASE + "/big-ales", timeout=8.0)
        d = r.json() if r.status_code == 200 else {}
        if r.status_code == 200 and d.get("available"):
            ok("Big ALES ucu ayakta",
               "model=%s · oturum=%s · sifreleme=%s"
               % ((d.get("config") or {}).get("model"),
                  "acik" if (d.get("session") or {}).get("signed_in") else "yok",
                  (d.get("session") or {}).get("encryption")))
        else:
            bad("Big ALES ucu ayakta",
                "HTTP %s / available=%s" % (r.status_code, d.get("available")))
    except Exception as e:
        bad("Big ALES ucu ayakta", f"{type(e).__name__}: {e}")
    # Kopru sayfasi: paketlenmis uygulamada Puter girisinin GERCEKTEN
    # yapilabilecegi tek yer (arayuz file:// uzerinde, orada olmaz).
    # Sayfanin AYAKTA ve SDK etiketini TASIYOR olmasi olculebilir; girisin
    # kendisi elle yapilan bir adim oldugu icin o iddia edilmiyor.
    try:
        r = httpx.get(BASE + "/puter-bridge", timeout=8.0)
        body = r.text if r.status_code == 200 else ""
        if r.status_code == 200 and "js.puter.com" in body:
            ok("Puter kopru sayfasi ayakta", "%d bayt · SDK etiketi var"
               % len(body))
        else:
            bad("Puter kopru sayfasi ayakta",
                "HTTP %s / SDK etiketi %s" % (r.status_code,
                                              "var" if "js.puter.com" in body
                                              else "YOK"))
    except Exception as e:
        bad("Puter kopru sayfasi ayakta", f"{type(e).__name__}: {e}")


# ── 4 + 5: sohbet ve arac ────────────────────────────────────────────
async def chat_once(text: str, wait_s: float = 150.0) -> dict:
    """Bir mesaj gonder, sonucu topla.

    Doner: {"reply":..., "errors":[...], "tools":[...], "tokens": n}
    """
    import websockets
    out = {"reply": "", "errors": [], "tools": [], "tokens": 0}
    async with websockets.connect(BASE.replace("http", "ws") + "/ws",
                                  open_timeout=20,
                                  max_size=8 * 1024 * 1024) as ws:
        first = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
        if first.get("setup_needed"):
            out["errors"].append("setup_needed: hicbir saglayici anahtari yok")
            return out
        await ws.send(json.dumps({"type": "message", "content": text}))
        deadline = time.time() + wait_s
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(),
                                             timeout=max(1.0, deadline - time.time()))
            except asyncio.TimeoutError:
                break
            try:
                m = json.loads(raw)
            except Exception:
                continue
            t = m.get("type")
            if t == "token":
                out["tokens"] += 1
            elif t == "tool_use":
                nm = m.get("name") or m.get("content") or "?"
                out["tools"].append(str(nm)[:40])
            elif t == "error":
                out["errors"].append(str(m.get("content"))[:400])
            elif t == "message":
                out["reply"] = str(m.get("content") or "")
                break                      # nihai cevap geldi
    return out


if status_json is not None:
    # ── ACIL DURUM YOLU ────────────────────────────────────────────────
    # main.py:2294-2301'de bir son care var: birincil zincirin TAMAMI
    # dustugunde Gemini/SambaNova/OpenRouter'a DUZ METIN olarak soruluyor
    # ve cevaba "bu turda arac/otomasyon kullanilamadi" notu ekleniyor.
    # O yol ARAC ARAYUZU VERMEZ, dolayisiyla model arac cagirmayi
    # ISTESE BILE yapamaz; JSON'u metin olarak yazar ve ALES onu (dogru
    # sekilde) calistirmaz.
    #
    # 2026-09-08 09:11 kosusunda tam bu oldu ve bu betik onu "model arac
    # cagirmayi secmedi" diye yazdi -- YANLIS TESHIS. Sonuc ayni (arac
    # dogrulanamadi) ama sebep bambaska: kod degil, saglayici hesabi.
    # Yanlis teshis en pahali cikti, o yuzden artik ayirt ediliyor.
    _EMERG = "Ana model zinciri eri"

    section("4) SOHBET (WebSocket /ws)")
    emergency = False
    try:
        res = asyncio.run(chat_once("Merhaba. Tek cumleyle kendini tanit."))
        emergency = _EMERG in (res["reply"] or "")
        if res["errors"]:
            bad("sohbet cevap veriyor", " | ".join(res["errors"])[:600])
        elif res["reply"].strip() and emergency:
            # Cevap GELDI ama birincil zincirden degil. "OK" demek
            # zincirin saglam oldugu izlenimi verirdi.
            bad("sohbet birincil zincirden cevap veriyor",
                "cevap ACIL DURUM yolundan geldi (duz metin, aracsiz). "
                "Birincil zincir (fast/fallback) olu — repair_model_chain.py "
                "ciktisina bak: kota/odeme/anahtar sorunu. "
                f"ilk 80: {res['reply'][:80]!r}")
        elif res["reply"].strip():
            ok("sohbet cevap veriyor",
               f"{len(res['reply'])} karakter · {res['tokens']} akis parcasi · "
               f"ilk 80: {res['reply'][:80]!r}")
        else:
            bad("sohbet cevap veriyor",
                f"bos cevap (akis parcasi: {res['tokens']}, hata yok) — "
                f"model baglandi ama metin uretmedi")
    except Exception as e:
        bad("sohbet cevap veriyor", f"{type(e).__name__}: {e}")

    section("5) ARAC CAGIRMA")
    try:
        res2 = asyncio.run(chat_once(
            "Su anda acik olan pencerelerin listesini al ve ilk ucunu yaz."))
        if res2["tools"]:
            ok("arac cagrildi", ", ".join(res2["tools"][:5]))
        elif res2["errors"]:
            bad("arac cagrildi", " | ".join(res2["errors"])[:400])
        elif _EMERG in (res2["reply"] or ""):
            # DOGRU TESHIS: model secim yapmadi, secme SANSI olmadi.
            bad("arac cagrildi",
                "arac dogrulanamadi cunku cevap ACIL DURUM yolundan geldi: "
                "o yol modele arac arayuzu VERMEZ (main.py:2294) ve bunu "
                "cevabin sonunda kendisi de yaziyor. Kod arizasi DEGIL; "
                "birincil zincir ayaga kalkmadan bu asama olculemez.")
        elif res2["reply"].strip():
            # Model arac cagirmayi SECMEDI. Bu bir cokme degil; uydurmadan
            # oldugu gibi yaziyoruz.
            bad("arac cagrildi",
                "model arac cagirmayi secmedi (cevap verdi ama tool_use "
                f"olayi gelmedi): {res2['reply'][:120]!r}")
        else:
            bad("arac cagrildi", "ne arac ne cevap geldi")
    except Exception as e:
        bad("arac cagrildi", f"{type(e).__name__}: {e}")

# ── backend'i kapat ──────────────────────────────────────────────────
# PyInstaller --onefile KRITIK AYRINTI: calistirdigimiz exe yalnizca bir
# "bootloader". Arsivi gecici bir klasore actiktan sonra gercek sunucuyu
# AYRI BIR SUREC olarak baslatir. proc.terminate() yalnizca bootloader'i
# oldurur, TORUNU OLDURMEZ -- sunucu 8000 portunu tutmaya devam eder.
#
# OLCULDU (2026-09-08 09:11 kosusu, autobuild.log): terminate() sonrasi
# 20 saniye beklendi, port bosalmadi ve 6. asama "8000 portu bosaldi" ile
# DUSTU. Yani masaustu penceresi/konsol testi -- Ali'nin asil sarti -- o
# kosuda HIC calismadi ve bunu bir urun arizasi sandik. Ariza testte.
#
# Cozum: sureç AGACINI oldur (taskkill /T). Agac da yetmezse ADA GORE
# kapat: bu betik zaten yalnizca ales-backend.exe'yi olcuyor ve calisan
# ikinci bir kopyanin varligi testi anlamsiz kilar.
print("\n  backend kapatiliyor...", flush=True)


def _kill_tree(p):
    """Bootloader + torunlari. Windows'ta tek guvenilir yol taskkill /T."""
    if p.poll() is None:
        try:
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=30)
        except Exception:
            pass
        try:
            p.wait(timeout=25)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    # Agac kirilmis olabilir (bootloader once cikarsa torun "yetim" kalir
    # ve /T onu bulamaz). Port hala doluysa ada gore kapat.
    for _ in range(15):
        if not port_busy():
            return True
        time.sleep(1.0)
    print("  port hala dolu -> ales-backend.exe ada gore kapatiliyor",
          flush=True)
    try:
        subprocess.run(["taskkill", "/IM", "ales-backend.exe", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=30)
    except Exception:
        pass
    for _ in range(20):
        if not port_busy():
            return True
        time.sleep(1.0)
    return False


if not _kill_tree(proc):
    bad("backend kapatildi",
        "8000 portu hala dinleniyor — surec agaci kapatilamadi. Sonraki "
        "asama (masaustu penceresi) guvenilir olmaz.")
else:
    ok("backend kapatildi", "8000 portu bosaldi")

# ── 6: paketlenmis masaustu uygulamasi ───────────────────────────────
if NO_GUI:
    print("\n(--no-gui: 6. asama atlandi)")
elif not os.path.exists(RELEASE_EXE):
    section("6) MASAUSTU PENCERESI")
    bad("release/ALES.exe calisti", "dosya YOK — electron paketleme adimina bak")
else:
    section("6) MASAUSTU PENCERESI (release/ALES.exe)")
    if port_busy():
        bad("8000 portu bosaldi",
            "backend hala dinliyor; Electron kendi backend'ini baslatirken "
            "10048 (port dolu) alacak. Test guvenilir olmaz.")
    else:
        import ctypes
        from ctypes import wintypes

        gui = subprocess.Popen([RELEASE_EXE], cwd=ROOT)
        print("  pencere bekleniyor (portable exe kendini aciyor, 60s'e "
              "kadar normal)...", flush=True)

        u32 = ctypes.windll.user32
        EnumWindows = u32.EnumWindows
        EnumWindows.argtypes = [ctypes.WINFUNCTYPE(
            ctypes.c_bool, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]

        def visible_windows():
            """Gorunur ust duzey pencereler: (baslik, sinif)."""
            found = []

            @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            def cb(hwnd, _l):
                if not u32.IsWindowVisible(hwnd):
                    return True
                n = u32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(n + 1)
                u32.GetWindowTextW(hwnd, buf, n + 1)
                cls = ctypes.create_unicode_buffer(256)
                u32.GetClassNameW(hwnd, cls, 256)
                found.append((buf.value, cls.value))
                return True

            EnumWindows(cb, 0)
            return found

        win, t0 = None, time.time()
        while time.time() - t0 < 90:
            if gui.poll() is not None:
                break
            for title, cls in visible_windows():
                if "ALES" in title.upper() and "Chrome_Widget" not in cls:
                    win = (title, cls)
                    break
            if win:
                break
            time.sleep(1.5)

        el = round(time.time() - t0, 1)
        if gui.poll() is not None:
            bad("masaustu penceresi acildi",
                f"islem {el}s icinde kendi kapandi (exit={gui.returncode})")
        elif win:
            ok("masaustu penceresi acildi",
               f"{el}s · baslik={win[0]!r} sinif={win[1]!r}")
        else:
            bad("masaustu penceresi acildi",
                f"{el}s icinde basliginda 'ALES' olan gorunur pencere "
                f"bulunamadi")

        # KONSOL PENCERESI OLMAMALI (Ali'nin acik sarti).
        consoles = [t for t, c in visible_windows()
                    if c in ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS")]
        if consoles:
            bad("konsol penceresi yok",
                f"gorunur konsol penceresi VAR: {consoles[:3]}")
        else:
            ok("konsol penceresi yok", "gorunur ConsoleWindowClass penceresi yok")

        # Backend gercekten ayaga kalkti mi (Electron kendi alt islemi olarak)?
        up = False
        for _ in range(60):
            if port_busy():
                up = True
                break
            time.sleep(1.5)
        if up:
            ok("Electron backend'i baslatti", "8000 portu dinleniyor")
        else:
            bad("Electron backend'i baslatti",
                "90s icinde 8000 portu dinlenmedi — extraResources icindeki "
                "ales-backend.exe eksik olabilir (electron-builder eksik "
                "kaynagi SESSIZCE atlar)")

        print("\n  masaustu uygulamasi kapatiliyor...", flush=True)
        # AYNI TUZAK: portable exe de bir sarmalayici. Kendini gecici klasore
        # acip gercek Electron'u baslatiyor, o da ales-backend.exe'yi
        # baslatiyor. terminate() yalnizca sarmalayiciyi oldurur; geride
        # 8000 portunu tutan bir backend ve gorunmez bir pencere kalir.
        # Agaci oldur, sonra kalanlari ada gore temizle.
        try:
            subprocess.run(["taskkill", "/PID", str(gui.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=30)
            gui.wait(timeout=20)
        except Exception:
            try:
                gui.kill()
            except Exception:
                pass
        for _im in ("ALES.exe", "ales-backend.exe"):
            try:
                subprocess.run(["taskkill", "/IM", _im, "/F"],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=30)
            except Exception:
                pass

# ── ozet ─────────────────────────────────────────────────────────────
section("OZET")
print(f"  GECTI : {len(PASS)}")
print(f"  KALDI : {len(FAIL)}")
if FAIL:
    print("\n  Basarisiz olanlar:")
    for n, w in FAIL:
        print(f"    - {n}: {w}")
sys.exit(len(FAIL))
