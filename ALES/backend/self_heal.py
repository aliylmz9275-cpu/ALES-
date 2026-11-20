"""
self_heal.py — Sinirli kendini toparlama. DevDuck/SRAIL ikamesi.

Ali'nin onayladigi sinir, kelimesi kelimesine: "No live self-rewriting or
self-replication." Bu modul o sinira UYAR:

  YAPAR                                  YAPMAZ
  ----------------------------------     -----------------------------------
  Kritik fonksiyonlari try/except ile    Kendi kaynak kodunu okumaz/yazmaz
  sarar, hatayi yutup calismaya devam
  eder (uygulama dusmez)

  Coken arka plan gorevlerini SINIRLI    Isletim sistemi surecini yeniden
  sayida, artan bekleme ile yeniden      baslatmaz / kendini kopyalamaz /
  baslatir                               yeni process spawn etmez

  Cokme oncesi durumu diske yazar ve     LLM'e "kendini duzelt" dedirtip
  acilista geri yukler                   uretilen kodu calistirmaz

NEDEN SUREC YENIDEN BASLATMA YOK: bir surec kendini yeniden baslatirsa,
hatanin kaynagi kalici oldugunda (bozuk config, tutulan port) sonsuz
yeniden-dogum dongusu olur ve kullanici hicbir hata mesaji goremez.
Denetim burada IC gorevlerde; surec seviyesinde karar KULLANICININ.

NEDEN SINIRLI YENIDEN BASLATMA: WINDOW_S icinde MAX_RESTARTS asilirsa gorev
"vazgecildi" isaretlenir ve bir daha denenmez. Sinirsiz yeniden baslatma,
her denemede ayni hatayi tekrar eden ve loglari bogan bir donguye doner —
ki bu "kendini iyilestirme" degil, sessiz arizadir.
"""
import asyncio
import inspect
import json
import os
import threading
import time
import traceback
from functools import wraps
from pathlib import Path

try:
    from config_manager import get_appdata_dir
    _APPDATA = get_appdata_dir()
except Exception:
    _APPDATA = Path(".")

STATE_FILE = _APPDATA / "self_heal.json"
RUNNING_MARKER = _APPDATA / "self_heal.running"

# ─── SINIRLAR ──────────────────────────────────────────────────────────
CHECK_INTERVAL_S = 15.0     # denetci dongusunun periyodu
MAX_RESTARTS = 5            # WINDOW_S icinde bir goreve izin verilen deneme
WINDOW_S = 300.0            # yeniden baslatma penceresi
BACKOFF_BASE_S = 2.0        # 2, 4, 8, 16, 32 ... (MAX_BACKOFF ile kirpilir)
MAX_BACKOFF_S = 60.0
MAX_INCIDENTS = 100         # bellekte tutulan olay sayisi
MAX_CHECKPOINTS = 40

_lock = threading.RLock()
_incidents = []             # [{"t","label","error","type","restarted"}]
_supervisors = []           # canli Supervisor ornekleri (status() icin)
_notify_cb = None
_stats = {"guarded_calls": 0, "caught": 0, "restarts": 0, "given_up": 0,
          "checkpoints_saved": 0, "checkpoints_loaded": 0,
          "unclean_shutdown": None, "last_error": None}


def set_notify(cb) -> None:
    """main.py bir geri cagri baglar: (level, mesaj) -> WS system_log."""
    global _notify_cb
    _notify_cb = cb


def _notify(level: str, msg: str):
    if not callable(_notify_cb):
        return
    try:
        _notify_cb(level, msg)
    except Exception:
        pass          # bildirim hatasi kendini-toparlamayi DUSURMEMELI


# ─── OLAY KAYDI ────────────────────────────────────────────────────────
def record(label: str, exc: BaseException = None, detail: str = "",
           restarted: bool = False) -> dict:
    """Bir arizayi kaydet. Hicbir zaman raise etmez."""
    ev = {
        "t": time.time(),
        "label": str(label)[:120],
        "type": type(exc).__name__ if exc is not None else "Note",
        "error": (str(exc)[:300] if exc is not None else str(detail)[:300]),
        "trace": ("".join(traceback.format_exception_only(type(exc), exc)).strip()[:200]
                  if exc is not None else ""),
        "restarted": bool(restarted),
    }
    with _lock:
        _incidents.append(ev)
        if len(_incidents) > MAX_INCIDENTS:
            del _incidents[:len(_incidents) - MAX_INCIDENTS]
        if exc is not None:
            _stats["caught"] += 1
            _stats["last_error"] = f"{ev['label']}: {ev['type']}: {ev['error']}"[:300]
    return ev


def incidents(limit: int = 25) -> list:
    with _lock:
        return list(_incidents[-max(1, int(limit)):])[::-1]


def clear_incidents() -> int:
    with _lock:
        n = len(_incidents)
        _incidents.clear()
    return n


# ─── GUARD: kritik fonksiyonlari sar ───────────────────────────────────
def guard(label: str = "", fallback=None, notify: bool = False,
          reraise: tuple = (asyncio.CancelledError, KeyboardInterrupt)):
    """Sync veya async fonksiyonu try/except ile sar.

    Hata durumunda `fallback` doner ve olay kaydedilir. `reraise` icindeki
    istisnalar YUTULMAZ — CancelledError'i yutmak asyncio kapanisini kilitler,
    KeyboardInterrupt'i yutmak Ctrl+C'yi olduruyor. Bu ikisi bilincli istisna.

    Kullanim:
        @guard("takvim senkronu", fallback=[])
        def sync_calendar(): ...
    """
    def _deco(fn):
        name = label or getattr(fn, "__name__", "fn")

        if inspect.iscoroutinefunction(fn):
            @wraps(fn)
            async def _aw(*a, **kw):
                with _lock:
                    _stats["guarded_calls"] += 1
                try:
                    return await fn(*a, **kw)
                except reraise:
                    raise
                except Exception as e:
                    record(name, e)
                    if notify:
                        _notify("ERROR", f"{name} hatasi yutuldu: {type(e).__name__}: {e}")
                    return fallback() if callable(fallback) else fallback
            return _aw

        @wraps(fn)
        def _sw(*a, **kw):
            with _lock:
                _stats["guarded_calls"] += 1
            try:
                return fn(*a, **kw)
            except reraise:
                raise
            except Exception as e:
                record(name, e)
                if notify:
                    _notify("ERROR", f"{name} hatasi yutuldu: {type(e).__name__}: {e}")
                return fallback() if callable(fallback) else fallback
        return _sw
    return _deco


def safe_call(fn, *a, label: str = "", fallback=None, **kw):
    """guard'in tek seferlik hali — dekoratorle sarmak istemedigin cagrilar icin."""
    with _lock:
        _stats["guarded_calls"] += 1
    try:
        return fn(*a, **kw)
    except (asyncio.CancelledError, KeyboardInterrupt):
        raise
    except Exception as e:
        record(label or getattr(fn, "__name__", "fn"), e)
        return fallback


# ─── CHECKPOINT: cokme sonrasi durum kurtarma ──────────────────────────
def _load_state() -> dict:
    try:
        if STATE_FILE.exists():
            raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
    except Exception:
        pass
    return {"checkpoints": {}, "last_clean_exit": None, "runs": 0}


def _write_state(d: dict) -> bool:
    """Atomik yazim; ALES'in her yerinde ayni idiom."""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1, default=str),
                       encoding="utf-8")
        os.replace(str(tmp), str(STATE_FILE))
        return True
    except Exception as e:
        with _lock:
            _stats["last_error"] = f"durum yazma: {type(e).__name__}: {e}"
        return False


def save_checkpoint(key: str, data) -> bool:
    """Kucuk bir durum parcasini diske yaz (JSON'a cevrilebilir olmali).

    NOT: burada tutulacak sey "hangi ise kaldim" bilgisidir; API anahtari,
    parola veya kullanici verisi DEGIL. Dosya sifrelenmemis JSON'dir.
    """
    d = _load_state()
    cps = d.setdefault("checkpoints", {})
    cps[str(key)] = {"t": time.time(), "data": data}
    if len(cps) > MAX_CHECKPOINTS:
        for k, _ in sorted(cps.items(), key=lambda kv: kv[1].get("t", 0))[:10]:
            cps.pop(k, None)
    ok = _write_state(d)
    if ok:
        with _lock:
            _stats["checkpoints_saved"] += 1
    return ok


def load_checkpoint(key: str, default=None):
    d = _load_state()
    cp = (d.get("checkpoints") or {}).get(str(key))
    if not cp:
        return default
    with _lock:
        _stats["checkpoints_loaded"] += 1
    return cp.get("data", default)


def drop_checkpoint(key: str) -> bool:
    d = _load_state()
    if (d.get("checkpoints") or {}).pop(str(key), None) is None:
        return False
    return _write_state(d)


def list_checkpoints() -> list:
    d = _load_state()
    return sorted(
        [{"key": k, "age_s": round(time.time() - (v.get("t") or 0), 1)}
         for k, v in (d.get("checkpoints") or {}).items()],
        key=lambda c: c["age_s"])


# ─── ACILIS / KAPANIS ISARETI ──────────────────────────────────────────
def mark_start() -> dict:
    """Acilista cagir. Onceki kapanisin TEMIZ olup olmadigini soyler.

    Mekanik: acilista bir "running" dosyasi yaziyoruz, duzgun kapanista
    siliyoruz. Acilista dosya HALA duruyorsa onceki surec cokmus demektir
    ve checkpoint'ler kurtarilmaya deger.
    """
    unclean = False
    prev = None
    try:
        if RUNNING_MARKER.exists():
            unclean = True
            try:
                prev = json.loads(RUNNING_MARKER.read_text(encoding="utf-8"))
            except Exception:
                prev = None
    except Exception:
        pass
    try:
        RUNNING_MARKER.parent.mkdir(parents=True, exist_ok=True)
        RUNNING_MARKER.write_text(
            json.dumps({"pid": os.getpid(), "started": time.time()}),
            encoding="utf-8")
    except Exception:
        pass
    d = _load_state()
    d["runs"] = int(d.get("runs") or 0) + 1
    d["last_start"] = time.time()
    _write_state(d)
    with _lock:
        _stats["unclean_shutdown"] = unclean
    if unclean:
        record("acilis", detail="onceki surec temiz kapanmadi")
    return {"unclean_shutdown": unclean, "previous": prev,
            "checkpoints": [c["key"] for c in list_checkpoints()],
            "runs": d.get("runs")}


def mark_clean_exit() -> bool:
    """Kapanista cagir; "running" isaretini kaldirir."""
    d = _load_state()
    d["last_clean_exit"] = time.time()
    _write_state(d)
    try:
        if RUNNING_MARKER.exists():
            RUNNING_MARKER.unlink()
        return True
    except Exception:
        return False


# ─── DENETCI (Supervisor) ──────────────────────────────────────────────
class Supervisor:
    """Adlandirilmis asyncio gorevlerini denetler ve SINIRLI yeniden baslatir.

    registry: main.py'nin `_workers` sozlugu. Yeni gorev buraya YAZILIR,
    boylece mevcut `_worker_alive()` / `/system/status` dogru sonuc verir.
    ESKIDEN buraya yazmayan bir denetci, gorevi yeniden baslatir ama
    /system/status "durmus" demeye devam ederdi — sessiz sapma.
    """

    def __init__(self, registry: dict = None, interval_s: float = None,
                 notify=None):
        self.registry = registry if registry is not None else {}
        self.interval = float(interval_s or CHECK_INTERVAL_S)
        self.notify = notify
        self._specs = {}      # name -> {"factory","critical","restarts":[t],
                              #          "given_up":bool,"next_try":float,"last_error":str}
        self._task = None
        with _lock:
            if self not in _supervisors:
                _supervisors.append(self)

    # ── kayit ──
    def add(self, name: str, factory, critical: bool = False,
            adopt=None) -> dict:
        """Bir goreve denetim ekle.

        factory: cagirildiginda YENI bir coroutine dondurmeli
                 (ornek: lambda: run_scheduler(cb)).
        adopt:   zaten olusturulmus bir Task varsa onu benimse (yeniden
                 baslatmadan). main.py gorevleri startup'ta kendisi
                 olusturuyor; onlari ikinci kez baslatmiyoruz.
        """
        if not callable(factory):
            return {"ok": False, "error": "factory cagirilabilir olmali"}
        self._specs[name] = {"factory": factory, "critical": bool(critical),
                             "restarts": [], "given_up": False,
                             "next_try": 0.0, "last_error": None,
                             "started": time.time()}
        if adopt is not None:
            self.registry[name] = adopt
        return {"ok": True, "name": name}

    def remove(self, name: str) -> bool:
        return self._specs.pop(name, None) is not None

    # ── canlilik ──
    def _alive(self, name: str) -> bool:
        t = self.registry.get(name)
        if t is None:
            return False
        # Kaynak izleyici bir THREAD/bayrak (asyncio task degil) — .done() yok.
        if not hasattr(t, "done"):
            if hasattr(t, "is_alive"):
                try:
                    return bool(t.is_alive())
                except Exception:
                    return False
            return bool(t)
        return not t.done()

    def _task_error(self, name: str) -> str:
        t = self.registry.get(name)
        if t is None or not hasattr(t, "done") or not t.done():
            return ""
        try:
            if t.cancelled():
                return "cancelled"
            e = t.exception()
            return f"{type(e).__name__}: {e}"[:200] if e else "temiz bitti"
        except Exception:
            return "durum okunamadi"

    # ── yeniden baslatma ──
    def _may_restart(self, spec: dict) -> bool:
        now = time.time()
        spec["restarts"] = [t for t in spec["restarts"] if now - t < WINDOW_S]
        return len(spec["restarts"]) < MAX_RESTARTS

    def _backoff(self, spec: dict) -> float:
        n = len(spec["restarts"])
        return min(MAX_BACKOFF_S, BACKOFF_BASE_S ** max(1, n))

    async def restart(self, name: str, force: bool = False) -> dict:
        """Gorevi yeniden baslat. force=True vazgecilmis gorevi de dener
        (kullanici UI'dan acikca istediginde)."""
        spec = self._specs.get(name)
        if not spec:
            return {"ok": False, "error": f"denetimde degil: {name}"}
        if spec["given_up"] and not force:
            return {"ok": False, "error": "vazgecildi; force gerekli",
                    "given_up": True}
        old = self.registry.get(name)
        if hasattr(old, "cancel") and hasattr(old, "done") and not old.done():
            try:
                old.cancel()
            except Exception:
                pass
        try:
            coro = spec["factory"]()
            self.registry[name] = asyncio.ensure_future(coro)
        except Exception as e:
            spec["last_error"] = f"{type(e).__name__}: {e}"[:200]
            record(f"supervisor:{name}", e)
            return {"ok": False, "error": spec["last_error"]}
        spec["restarts"].append(time.time())
        if force:
            spec["given_up"] = False
        spec["next_try"] = 0.0
        with _lock:
            _stats["restarts"] += 1
        record(f"supervisor:{name}", detail="yeniden baslatildi", restarted=True)
        _notify("WARN", f"'{name}' gorevi yeniden baslatildi "
                        f"({len(spec['restarts'])}/{MAX_RESTARTS})")
        return {"ok": True, "name": name,
                "restarts_in_window": len(spec["restarts"])}

    # ── denetci dongusu ──
    async def _loop(self):
        while True:
            try:
                await asyncio.sleep(self.interval)
                now = time.time()
                for name, spec in list(self._specs.items()):
                    if self._alive(name) or spec["given_up"]:
                        continue
                    if now < spec.get("next_try", 0.0):
                        continue
                    err = self._task_error(name)
                    if err == "cancelled":
                        # Bilincli iptal — kapanis veya kullanici. Yeniden
                        # baslatmak kapanisi engeller.
                        continue
                    spec["last_error"] = err or "durdu"
                    if not self._may_restart(spec):
                        spec["given_up"] = True
                        with _lock:
                            _stats["given_up"] += 1
                        record(f"supervisor:{name}",
                               detail=f"vazgecildi ({MAX_RESTARTS} deneme): {err}")
                        _notify("ERROR",
                                f"'{name}' gorevi {MAX_RESTARTS} denemede "
                                f"duzelmedi, vazgecildi. Sebep: {err or 'bilinmiyor'}")
                        continue
                    spec["next_try"] = now + self._backoff(spec)
                    await self.restart(name)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                record("supervisor:loop", e)

    async def start(self) -> dict:
        if self._task is not None and not self._task.done():
            return {"ok": True, "already": True}
        self._task = asyncio.ensure_future(self._loop())
        return {"ok": True, "watching": list(self._specs.keys()),
                "interval_s": self.interval}

    async def stop(self) -> dict:
        t, self._task = self._task, None
        if t is not None and not t.done():
            t.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(t), timeout=1.0)
            except Exception:
                pass
        return {"ok": True}

    def status(self) -> dict:
        now = time.time()
        items = []
        for name, spec in self._specs.items():
            items.append({
                "name": name,
                "alive": self._alive(name),
                "critical": spec["critical"],
                "given_up": spec["given_up"],
                "restarts_in_window": len([t for t in spec["restarts"]
                                           if now - t < WINDOW_S]),
                "max_restarts": MAX_RESTARTS,
                "last_error": spec.get("last_error"),
                "next_try_in_s": (round(spec["next_try"] - now, 1)
                                  if spec.get("next_try", 0) > now else 0),
            })
        return {
            "running": bool(self._task is not None and not self._task.done()),
            "interval_s": self.interval,
            "workers": sorted(items, key=lambda w: (w["alive"], w["name"])),
            "degraded": [w["name"] for w in items
                         if not w["alive"] and not w["given_up"]],
            "given_up": [w["name"] for w in items if w["given_up"]],
        }


# ─── DEVRE KESİCİ (CIRCUIT BREAKER) ────────────────────────────────────
# Arka arkaya hata veren sağlayıcıya geçici olarak istek göndermeyi durdurur.
# Soğuma süresi (cooldown) dolunca 'half-open' denemesi yapar.
class CircuitBreaker:
    STATE_CLOSED = "CLOSED"        # Normal akış
    STATE_OPEN = "OPEN"            # Devre açık (istekler engellenir)
    STATE_HALF_OPEN = "HALF_OPEN"  # Test aşaması

    def __init__(self, name: str, failure_threshold: int = 4, cooldown_s: float = 45.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_s = cooldown_s
        self.state = self.STATE_CLOSED
        self.consecutive_failures = 0
        self.last_failure_time = 0.0
        self.total_trips = 0

    def can_attempt(self) -> bool:
        now = time.time()
        if self.state == self.STATE_CLOSED:
            return True
        elif self.state == self.STATE_OPEN:
            if now - self.last_failure_time >= self.cooldown_s:
                self.state = self.STATE_HALF_OPEN
                return True
            return False
        elif self.state == self.STATE_HALF_OPEN:
            return True
        return False

    def record_success(self):
        self.consecutive_failures = 0
        self.state = self.STATE_CLOSED

    def record_failure(self, err_msg: str = ""):
        self.consecutive_failures += 1
        self.last_failure_time = time.time()
        if self.consecutive_failures >= self.failure_threshold:
            if self.state != self.STATE_OPEN:
                self.state = self.STATE_OPEN
                self.total_trips += 1
                record(f"circuit_breaker:{self.name}", detail=f"Devre açıldı (cooldown {self.cooldown_s}s): {err_msg}")
                _notify("WARN", f"'{self.name}' sağlayıcısı peş peşe {self.consecutive_failures} hata verdi, devre {self.cooldown_s}s askıya alındı.")

    def status(self) -> dict:
        now = time.time()
        cooldown_left = max(0.0, round(self.cooldown_s - (now - self.last_failure_time), 1)) if self.state == self.STATE_OPEN else 0.0
        return {
            "name": self.name,
            "state": self.state,
            "consecutive_failures": self.consecutive_failures,
            "cooldown_left_s": cooldown_left,
            "total_trips": self.total_trips,
            "allowed_now": self.can_attempt(),
        }


_circuit_breakers: dict = {}

def get_circuit_breaker(name: str) -> CircuitBreaker:
    with _lock:
        if name not in _circuit_breakers:
            _circuit_breakers[name] = CircuitBreaker(name)
        return _circuit_breakers[name]

def can_call_provider(provider: str) -> bool:
    return get_circuit_breaker(provider).can_attempt()

def report_provider_success(provider: str):
    get_circuit_breaker(provider).record_success()

def report_provider_failure(provider: str, err: str = ""):
    get_circuit_breaker(provider).record_failure(err)

def circuit_breakers_status() -> dict:
    with _lock:
        return {name: cb.status() for name, cb in _circuit_breakers.items()}


# ─── DURUM / ISTATISTIK ────────────────────────────────────────────────
def status() -> dict:
    """Tum denetciler + olay ozeti. /selfheal/status bunu doner."""
    sups = []
    with _lock:
        live = list(_supervisors)
    for s in live:
        try:
            sups.append(s.status())
        except Exception:
            pass
    d = _load_state()
    with _lock:
        st = dict(_stats)
    return {
        "supervisors": sups,
        "stats": st,
        "circuit_breakers": circuit_breakers_status(),
        "incidents": incidents(15),
        "checkpoints": list_checkpoints(),
        "runs": d.get("runs"),
        "last_clean_exit": d.get("last_clean_exit"),
        "limits": {"max_restarts": MAX_RESTARTS, "window_s": WINDOW_S,
                   "check_interval_s": CHECK_INTERVAL_S,
                   "max_backoff_s": MAX_BACKOFF_S},
        "policy": ("Sadece ic gorevler yeniden baslatilir. Surec yeniden "
                   "baslatma, kendi kodunu degistirme ve kendini cogaltma "
                   "KAPALIDIR (tasarim geregi, ayar degil)."),
    }


def stats() -> dict:
    with _lock:
        s = dict(_stats)
    s["incidents"] = len(_incidents)
    s["supervisors"] = len(_supervisors)
    s["circuit_breakers"] = len(_circuit_breakers)
    return s


def reset_stats() -> dict:
    with _lock:
        _stats.update({"guarded_calls": 0, "caught": 0, "restarts": 0,
                       "given_up": 0, "checkpoints_saved": 0,
                       "checkpoints_loaded": 0, "last_error": None})
    return stats()


def info() -> dict:
    return {
        "self_rewriting": False,
        "self_replication": False,
        "process_restart": False,
        "in_process_task_restart": True,
        "bounded": True,
        "circuit_breakers": True,
        "max_restarts": MAX_RESTARTS,
        "window_s": WINDOW_S,
        "state_file": str(STATE_FILE),
    }

