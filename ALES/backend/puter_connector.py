"""
puter_connector.py — Big ALES: API ANAHTARI OLMADAN buyuk model erisimi.

═══════════════════════════════════════════════════════════════════════
MIMARI KARARIN GEREKCESI — LUTFEN SILMEDEN ONCE OKU
═══════════════════════════════════════════════════════════════════════
Puter'in "User Pays" modeli TARAYICI TARAFLIDIR. Somut olarak:
  * SDK bir <script src="https://js.puter.com/v2/"> etiketiyle yuklenir.
  * Kimlik dogrulama puter.com'a acilan bir OTURUM ACMA PENCERESIDIR;
    ortaya cikan oturum jetonu o kaynagin (origin) tarayici deposunda
    yasar.
  * Ucreti kullanici kendi Puter hesabindan oder — bu yuzden gelistirici
    anahtari YOKTUR ve olamaz.

Yani Python'dan dogrudan cagrilabilecek, belgelenmis, anahtarsiz bir
sunucu-sunucu ucu YOK. Boyle bir ucu VARMIS GIBI HTTP istegi yazmak
calismayan bir ozellik uretirdi; bu projenin durustluk kurali bunu
yasakliyor (olculmemis yetenek rapor edilmez).

DOGRU COZUM — ve bu gercekten calisir: ALES bir Electron uygulamasi,
yani ARAYUZ KATMANI ZATEN GERCEK BIR TARAYICI. puter.js'in ait oldugu
yer orasi. Bu modul de sunucu tarafinda su isi yapar:

    call_puter_model(prompt, model_id)
        -> istegi acik WebSocket uzerinden arayuze gonderir
        -> arayuz puter.ai.chat() cagirir (gerekiyorsa once oturum acar)
        -> sonuc ayni WebSocket'ten geri gelir

Boylece Ali'nin istedigi arayuz (backend'de bir puter_connector ve bir
call_puter_model fonksiyonu) AYNEN var; tasima katmani ise ISE YARAYAN
tek yol. Arayuz bagli degilse fonksiyon SESSIZ KALMAZ, ne yapilmasi
gerektigini soyleyen net bir hata dondurur.

GUVENLIK: jeton saklama
  * Windows'ta DPAPI (CryptProtectData) ile sifrelenir. Anahtar isletim
    sisteminde, KULLANICI hesabina bagli; dosya baska bir kullaniciya ya
    da baska bir makineye kopyalanirsa COZULEMEZ. Ek bagimlilik yok.
  * Dosya izinleri daraltilir: Windows'ta icacls ile kalitim kesilir ve
    yalnizca sahibe tam yetki verilir; POSIX'te 0600.
  * Windows disinda DPAPI yok. O durumda jeton sifrelenmis gibi
    GOSTERILMEZ: dosyaya enc="none" yazilir ve gunluge duz metin oldugu
    soylenir. Yanlis guvenlik hissi vermek, guvenligin kendisinden daha
    tehlikelidir.
"""
import asyncio
import base64
import json
import os
import platform
import subprocess
import sys
import time
import uuid
from pathlib import Path

try:
    from config_manager import APPDATA
except Exception:                                    # tek basina calisirken
    _b = os.environ.get("APPDATA") or os.path.expanduser("~")
    APPDATA = Path(_b) / "ALES"
    APPDATA.mkdir(parents=True, exist_ok=True)

SESSION_FILE = APPDATA / "puter_session.enc"

# Ali'nin belirttigi modeller. Beyaz liste BILINCLI: arayuze rastgele bir
# model adi gonderilmesi, Puter hesabinda beklenmeyen ucret dogurabilir.
ALLOWED_MODELS = (
    "nousresearch/hermes-3-llama-3.1-405b",
    "nousresearch/hermes-3-llama-3.1-70b",
    "nousresearch/hermes-4-70b",
)
DEFAULT_MODEL = ALLOWED_MODELS[0]

# Orkestrator sistem istemi — Ali'nin metni, HARFI HARFINE.
ORCHESTRATOR_SYSTEM = ("You are a helpful orchestrator. Rewrite user "
                       "requests clearly and legally for execution.")

_IS_WINDOWS = platform.system() == "Windows"


# ═══════════════════════════════════════════════════════════════════
# 1. JETON SAKLAMA (sifreli + izinleri daraltilmis)
# ═══════════════════════════════════════════════════════════════════
def _dpapi(data: bytes, protect: bool) -> bytes:
    """Windows DPAPI ile sifrele/coz. Basarisiz olursa Exception.

    Neden ctypes: `cryptography` paketi requirements'ta YOK ve tek bir
    ozellik icin ~10 MB'lik bir bagimlilik + PyInstaller'da ek ikili
    yuku getirirdi. DPAPI isletim sisteminde hazir duruyor.
    """
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _mk(b):
        buf = ctypes.create_string_buffer(b, len(b))
        return BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    src, _keep = _mk(data)
    out = BLOB()
    fn = (ctypes.windll.crypt32.CryptProtectData if protect
          else ctypes.windll.crypt32.CryptUnprotectData)
    # 0x01 = CRYPTPROTECT_UI_FORBIDDEN: arka planda calisiyoruz, DPAPI
    # kullaniciya pencere acmaya kalkmasin (acsa donmeyen bir cagri olurdu).
    ok = fn(ctypes.byref(src), None, None, None, None, 0x01, ctypes.byref(out))
    if not ok:
        raise OSError("DPAPI %s basarisiz (hata %d)"
                      % ("koruma" if protect else "cozme",
                         ctypes.GetLastError()))
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _restrict_permissions(path: Path):
    """Dosyayi yalnizca sahibinin okuyabilecegi hale getir."""
    try:
        os.chmod(path, 0o600)                       # POSIX; Windows'ta kismi
    except Exception:
        pass
    if not _IS_WINDOWS:
        return
    # Windows'ta gercek koruma ACL'dir: kalitimi kes (/inheritance:r) ve
    # SADECE mevcut kullaniciya tam yetki ver (/grant:r). Boylece
    # "Users" grubu uzerinden gelen okuma hakki kalkar.
    user = os.environ.get("USERNAME")
    if not user:
        return
    try:
        subprocess.run(
            ["icacls", str(path), "/inheritance:r",
             "/grant:r", "%s:F" % user],
            capture_output=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        print("[PUTER] ACL daraltilamadi (%s) -- dosya yine 0600" % e)


def save_session(session: dict) -> bool:
    """Puter oturum verisini sifreleyip diske yaz. Basari/basarisizlik."""
    if not isinstance(session, dict):
        return False
    raw = json.dumps(session, ensure_ascii=False).encode("utf-8")
    enc, blob = "none", raw
    if _IS_WINDOWS:
        try:
            blob = _dpapi(raw, protect=True)
            enc = "dpapi"
        except Exception as e:
            print("[PUTER] DPAPI kullanilamadi (%s) -- jeton SIFRELENMEDI" % e)
    else:
        print("[PUTER] DPAPI yalnizca Windows'ta var -- jeton SIFRELENMEDI, "
              "dosya izinleri 0600 ile korunuyor")
    try:
        SESSION_FILE.write_text(json.dumps({
            "enc": enc,
            "saved_at": time.time(),
            "data": base64.b64encode(blob).decode("ascii"),
        }), encoding="utf-8")
        _restrict_permissions(SESSION_FILE)
        return True
    except Exception as e:
        print("[PUTER] oturum yazilamadi: %s" % e)
        return False


def load_session() -> dict:
    """Kayitli oturumu coz. Yoksa/bozuksa {} (fail-open)."""
    if not SESSION_FILE.exists():
        return {}
    try:
        wrap = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        blob = base64.b64decode(wrap.get("data") or "")
        if wrap.get("enc") == "dpapi":
            blob = _dpapi(blob, protect=False)
        return json.loads(blob.decode("utf-8")) or {}
    except Exception as e:
        # Cozulemedi: dosya baska kullanici/makineden gelmis olabilir.
        # Cokmek yerine oturumu yok sayiyoruz; arayuz yeniden giris ister.
        print("[PUTER] oturum okunamadi (%s) -- yeniden giris gerekecek" % e)
        return {}


def clear_session() -> bool:
    try:
        if SESSION_FILE.exists():
            SESSION_FILE.unlink()
        # Cikis = yeniden deneme hakki: devre kesici sayaci sifirlanir,
        # yoksa kullanici giris yapmaya karar verdiginde yol hala kapali
        # gorunurdu.
        reset_breaker()
        return True
    except Exception:
        return False


def has_session() -> bool:
    s = load_session()
    return bool(s.get("signed_in") or s.get("username") or s.get("token"))


def session_info() -> dict:
    """UI icin: gizli alan SIZDIRMADAN oturum durumu."""
    s = load_session()
    enc = "none"
    try:
        if SESSION_FILE.exists():
            enc = (json.loads(SESSION_FILE.read_text(encoding="utf-8"))
                   .get("enc") or "none")
    except Exception:
        pass
    return {
        "signed_in": bool(s.get("signed_in") or s.get("username")),
        "username": s.get("username") or None,
        "encryption": enc,                # dpapi | none
        "file": str(SESSION_FILE),
        "stored": SESSION_FILE.exists(),
        "models": list(ALLOWED_MODELS),
    }


# ═══════════════════════════════════════════════════════════════════
# 2. ARAYUZ KOPRUSU
# ═══════════════════════════════════════════════════════════════════
# Bekleyen istekler: request_id -> Future. Arayuzden "puter_result"
# geldiginde main.py bunu cozer (bkz. resolve()).
_pending = {}
# Bekleyen ISLERIN icerigi: request_id -> {"model","prompt","system"}.
#
# NEDEN AYRI BIR SOZLUK: Electron paketlenmis halde arayuzu file:// ile
# aciyor (electron-main.js: mainWindow.loadFile). file:// bir "opaque
# origin"dur: puter.js'in giris akisi puter.com'a acilan bir pencere ve
# postMessage uzerine kuruludur, orada kaynak "null" gorunur ve jetonun
# yasayacagi bir depo da yoktur. Yani cagriyi DOGRUDAN o sayfadan yapmak
# guvenilir DEGIL.
#
# Cozum: kopru sayfasi (main.py > GET /puter-bridge) backend'in KENDI
# http kaynagindan (http://127.0.0.1:8000) servis edilir — gercek bir
# origin. O sayfa isi buradan cekip (GET /puter-bridge/job/<rid>) puter.js
# ile cagirir ve sonucu POST /puter-bridge/result ile geri verir.
# Boylece jeton da 127.0.0.1:8000 kaynaginda kalici olur.
_jobs = {}
# WebSocket listesini main.py saglar. Modul main'i IMPORT ETMEZ: import
# dongusu olurdu (main.py bu modulu yukluyor). Kayit yontemi ters yonde.
_ws_source = None


def register_ws_source(fn):
    """main.py cagirir: fn() -> bagli WebSocket listesi."""
    global _ws_source
    _ws_source = fn


def resolve(request_id: str, payload: dict):
    """Arayuzden gelen sonucu bekleyen cagriya teslim et."""
    _jobs.pop(request_id, None)
    fut = _pending.pop(request_id, None)
    if fut and not fut.done():
        try:
            fut.set_result(payload or {})
        except Exception:
            pass
        return True
    return False


def get_job(request_id: str) -> dict:
    """Kopru sayfasi isini buradan ceker. Bilinmeyen id -> {} (sizdirmaz)."""
    j = _jobs.get(request_id)
    return dict(j) if isinstance(j, dict) else {}


def _clients() -> list:
    try:
        return list(_ws_source() or []) if _ws_source else []
    except Exception:
        return []


class PuterError(RuntimeError):
    """Puter yolu kullanilamadi. Mesaj kullaniciya gosterilebilir.

    counts=False: bu hata devre kesiciyi ETKILEMEZ. Ayrim onemli — bos
    istem ya da beyaz liste disi model CAGIRANIN hatasidir, Puter'in
    erisilebilirligiyle ilgisi yoktur; bunlari sayarsak yolu haksiz yere
    kapatirdik.
    """

    def __init__(self, msg, counts=True):
        super().__init__(msg)
        self.counts = counts


# ─── DEVRE KESICI ──────────────────────────────────────────────────
# NEDEN GEREKLI: kullanici Puter'a hic giris yapmazsa (ki yapmak zorunda
# degil) her istek zaman asimini BEKLER. Varsayilan 60s ile bu, "Big ALES
# acik ama giris yok" durumunda HER MESAJIN bir dakika gecikmesi anlamina
# gelir. Sohbet olmez (fail-open calisir) ama kullanilamaz hale gelir.
# Bu yuzden ust uste basarisizliktan sonra yol KISA DEVRE yapar: cagri
# aninda hata dondurur, zincir gecikmesiz devam eder. Giris yapildigi
# (has_session) ya da bir cagri basardigi anda sayac sifirlanir.
_fail_streak = 0
_FAIL_LIMIT = 2
_last_error = ""


def breaker_state() -> dict:
    """UI/tani icin: yol acik mi, neden kapali."""
    return {"fail_streak": _fail_streak, "limit": _FAIL_LIMIT,
            "open": _fail_streak >= _FAIL_LIMIT and not has_session(),
            "last_error": _last_error or None}


def reset_breaker():
    global _fail_streak, _last_error
    _fail_streak = 0
    _last_error = ""


async def call_puter_model(prompt: str, model_id: str = DEFAULT_MODEL,
                           system: str = None, timeout: float = 60.0) -> str:
    """Puter uzerinden model cagir ve METNI dondur. ANAHTAR GEREKMEZ.

    Oturum yoksa arayuz Puter'in kendi giris penceresini acar (gecis:
    "login redirection"); kullanici bir kez giris yapar, jeton bu modul
    tarafindan sifreli saklanir.

    Hata durumunda PuterError atar — cagiran taraf (model_router) bunu
    yakalayip NORMAL zincirle devam eder, yani sohbet asla olmez.

    Ust uste basarisizliktan sonra devre kesici devreye girer ve cagri
    BEKLEMEDEN hata doner (bkz. breaker_state): giris yapilmamis bir
    kurulumda her mesajin bir dakika beklemesini onler.
    """
    global _fail_streak, _last_error
    if _fail_streak >= _FAIL_LIMIT and not has_session():
        raise PuterError(
            "Big ALES gecici olarak devre disi (%d ardisik basarisizlik; son "
            "hata: %s). Ayarlar > Big ALES'ten Puter girisini tamamlayin."
            % (_fail_streak, _last_error or "-"), counts=False)
    try:
        out = await _do_call(prompt, model_id, system, timeout)
    except PuterError as e:
        if getattr(e, "counts", True):
            _fail_streak += 1
            _last_error = str(e)
        raise
    reset_breaker()
    return out


async def _do_call(prompt: str, model_id: str, system, timeout: float) -> str:
    """call_puter_model'in govdesi (devre kesici olmadan)."""
    text = (prompt or "").strip()
    if not text:
        raise PuterError("bos istem", counts=False)
    if model_id not in ALLOWED_MODELS:
        # Sessizce degistirmiyoruz: hangi modelin kullanildigi para demek.
        raise PuterError("izin verilmeyen model: %s (gecerli: %s)"
                         % (model_id, ", ".join(ALLOWED_MODELS)), counts=False)

    clients = _clients()
    if not clients:
        raise PuterError(
            "Big ALES arayuz penceresini gerektiriyor (Puter girisi tarayici "
            "tarafindadir). ALES penceresi acikken tekrar deneyin.")

    rid = uuid.uuid4().hex
    loop = asyncio.get_event_loop()
    fut = loop.create_future()
    _pending[rid] = fut
    _jobs[rid] = {"model": model_id, "prompt": text,
                  "system": system or ORCHESTRATOR_SYSTEM}

    # "bridge": arayuz file:// uzerinde calisiyorsa (paketlenmis Electron)
    # cagriyi kendi yapmak yerine BU adresi bir pencerede acar; sayfa
    # backend'in http kaynagindan gelir, yani puter.js normal bir origin
    # gorur. Ayrintili gerekce _jobs tanimindaki notta.
    msg = {"type": "puter_call", "request_id": rid, "model": model_id,
           "prompt": text, "system": system or ORCHESTRATOR_SYSTEM,
           "bridge": "/puter-bridge?rid=%s" % rid,
           "session": load_session() or None}
    sent = 0
    for ws in clients:
        try:
            await ws.send_json(msg)
            sent += 1
        except Exception:
            continue
    if not sent:
        _pending.pop(rid, None)
        _jobs.pop(rid, None)
        raise PuterError("arayuze istek gonderilemedi (baglanti kapandi)")

    try:
        res = await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError:
        raise PuterError(
            "Puter yaniti %.0fs icinde gelmedi (giris penceresi acildiysa "
            "girisi tamamlayip tekrar deneyin)" % timeout)
    finally:
        _pending.pop(rid, None)
        _jobs.pop(rid, None)

    # Arayuz yeni/yenilenmis oturum bildirdiyse sakla (sifreli).
    sess = res.get("session")
    if isinstance(sess, dict) and sess:
        save_session(sess)

    if not res.get("ok"):
        raise PuterError(res.get("error") or "Puter cagrisi basarisiz")
    out = (res.get("text") or "").strip()
    if not out:
        raise PuterError("Puter bos yanit dondurdu")
    return out


async def rewrite_request(user_text: str, model_id: str = DEFAULT_MODEL,
                          timeout: float = 60.0) -> str:
    """Orkestrator gecisi: istegi net ve yasal bicimde yeniden yaz.

    Sistem istemi Ali'nin verdigi metnin AYNISI (ORCHESTRATOR_SYSTEM).
    """
    return await call_puter_model(user_text, model_id=model_id,
                                  system=ORCHESTRATOR_SYSTEM,
                                  timeout=timeout)


# ═══════════════════════════════════════════════════════════════════
# 3. KOPRU SAYFASI (gercek http kaynagi)
# ═══════════════════════════════════════════════════════════════════
# Sabit metin — icine hicbir sey ENJEKTE EDILMIYOR: sayfa istek kimligini
# location.search'ten, isin kendisini de /puter-bridge/job/<rid> ucundan
# okur. Boylece istem metni URL'ye ya da HTML'e gomulmez (hem uzunluk hem
# kacis sorunu ortadan kalkar).
BRIDGE_HTML = """<!doctype html>
<html lang="tr"><head><meta charset="utf-8"><title>ALES - Puter</title>
<script src="https://js.puter.com/v2/"></script>
<style>
 html,body{margin:0;height:100%;background:#0b0b0b;color:#ddd;
   font:13px/1.6 ui-monospace,Consolas,monospace;display:flex;
   align-items:center;justify-content:center}
 .box{max-width:520px;padding:22px 26px;border:1px solid #222;border-radius:10px}
 h1{font-size:13px;letter-spacing:.14em;color:#8ab;margin:0 0 10px}
 #s{white-space:pre-wrap}
 .n{color:#777;font-size:11px;margin-top:14px}
</style></head><body>
<div class="box">
  <h1>BIG ALES - PUTER</h1>
  <div id="s">Puter hazirlaniyor...</div>
  <div class="n">API anahtari istenmez. Ucret kendi Puter hesabinizdan
  karsilanir. Giris yalnizca bir kez yapilir.</div>
</div>
<script>
const rid = new URLSearchParams(location.search).get('rid') || ''
const el = document.getElementById('s')
const say = (t) => { el.textContent = t }
async function post(body) {
  try {
    await fetch('/puter-bridge/result', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(Object.assign({rid: rid}, body))})
  } catch (e) {}
}
;(async () => {
  try {
    if (!rid) { say('Gecersiz istek: rid yok.'); return }
    let job = null
    try {
      const r = await fetch('/puter-bridge/job/' + encodeURIComponent(rid))
      job = await r.json()
    } catch (e) { job = null }
    if (!job || !job.prompt) {
      say('Is bulunamadi (zaman asimi olabilir). Pencereyi kapatabilirsiniz.')
      await post({ok:false, error:'kopru: is bulunamadi'}); return
    }
    if (!window.puter || !window.puter.ai || !window.puter.ai.chat) {
      say('Puter SDK yuklenemedi. Internet baglantisi gerekiyor.')
      await post({ok:false, error:'Puter SDK yuklenemedi (cevrimdisi olabilir)'})
      return
    }
    let username = null
    try {
      const signed = window.puter.auth && window.puter.auth.isSignedIn
        ? await Promise.resolve(window.puter.auth.isSignedIn()) : false
      if (!signed) { say('Puter girisi bekleniyor...'); await window.puter.auth.signIn() }
      const u = window.puter.auth && window.puter.auth.getUser
        ? await window.puter.auth.getUser() : null
      username = (u && u.username) || null
    } catch (e) {
      say('Giris tamamlanmadi.')
      await post({ok:false, error:'Puter girisi tamamlanmadi: ' + (e && e.message || e)})
      return
    }
    say('Model cagriliyor: ' + job.model)
    const opts = {model: job.model}
    if (job.system) opts.system = job.system
    const res = await window.puter.ai.chat(job.prompt, opts)
    let t = (typeof res === 'string') ? res
      : (res && res.message && res.message.content) || (res && res.text)
        || (res && res.content) || ''
    const flat = Array.isArray(t)
      ? t.map(p => (typeof p === 'string' ? p : (p && p.text) || '')).join('')
      : String(t || '')
    await post({ok: !!flat.trim(), text: flat,
      error: flat.trim() ? null : 'Puter bos yanit dondurdu',
      session: {signed_in: true, username: username}})
    say(flat.trim() ? 'Bitti. Pencere kapaniyor...' : 'Puter bos yanit dondurdu.')
    setTimeout(() => { try { window.close() } catch (e) {} }, 1400)
  } catch (e) {
    say('Hata: ' + (e && e.message || e))
    await post({ok:false, error:String(e && e.message || e)})
  }
})()
</script></body></html>
"""


if __name__ == "__main__":                            # elle hizli denetim
    print("oturum dosyasi :", SESSION_FILE)
    print("durum          :", json.dumps(session_info(), ensure_ascii=False,
                                         indent=2))
    if _IS_WINDOWS:
        try:
            probe = _dpapi(b"ales-dpapi-denetimi", True)
            back = _dpapi(probe, False)
            print("DPAPI          :", "CALISIYOR"
                  if back == b"ales-dpapi-denetimi" else "TUTARSIZ")
        except Exception as e:
            print("DPAPI          : KULLANILAMIYOR (%s)" % e)
    sys.exit(0)
