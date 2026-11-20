"""
resource_monitor.py — ALES kaynak izleyici (Faz 3 / Priority 3).

CPU, RAM, GPU ve disk kullanimini periyodik olcer; esikler asilirsa once
KULLANICIYA SORAR ("Bilgisayar yavasliyor, bazi modulleri kapatayim mi?"),
ISRARLI/KRITIK asimda ise otomatik olarak dusuk-tuketim moduna gecer
(headless, TTS duraklat, Shadowbroker duraklat, WebSocket kapat).

── ONEMLI TASARIM KARARI: "scope" ──────────────────────────────────────
Istenen esikler CPU %20 / RAM %30 / GPU %10. Bu degerler SISTEM GENELI
olarak yorumlanirsa Windows 11 bos haldeyken bile RAM %30'un uzerindedir —
yani ALES kalici olarak kisitli modda takilir. Bu yuzden esikler
VARSAYILAN OLARAK ALES'IN KENDI kullanimina (kendi surec agaci) uygulanir:
"ALES bilgisayari %20 CPU'dan fazla mesgul etmesin" okumasi tek anlamli
okumadir. config.json -> "resource_scope": "system" ile sistem geneline
cevrilebilir. Her iki metrik de her zaman OLCULUR ve raporlanir.

── Bagimliliklar ───────────────────────────────────────────────────────
psutil zorunlu (requirements.txt'de mevcut). GPU icin sirasiyla:
pynvml -> yoksa `nvidia-smi` alt sureci -> yoksa None (GPU esigi atlanir).
Hicbiri yoksa modul yine calisir; sadece gpu=None doner.

Bu modul TEK BASINA calisir: hicbir ALES modulunu import etmez ve dogrudan
bir sey kapatmaz. Kapatma/duraklatma islerini main.py'nin kaydettigi
CALLBACK'ler yapar (register_action / register_alert). Boylece test
edilebilir kalir ve dairesel import olmaz.
"""

import os
import shutil
import subprocess
import threading
import time

try:
    import psutil
except Exception:                                    # pragma: no cover
    psutil = None

# ─── Varsayilanlar (config.json ile override edilir) ──────────────────
DEFAULT_THRESHOLDS = {"cpu": 20.0, "ram": 30.0, "gpu": 10.0}
DEFAULT_INTERVAL_S = 1.0        # istenildigi gibi saniyede bir ornekleme
GPU_EVERY_N = 5                 # nvidia-smi pahali -> her 5. turda olc
SUSTAINED_SAMPLES = 5           # esik ust uste kac ornek asilirsa "israrli"
CRITICAL_FACTOR = 2.0           # esigin 2 kati -> aninda otomatik dusur
_EMA_ALPHA = 0.4                # olcum gurultusunu yumusat

_gpu_backend = None             # "pynvml" | "smi" | None  (ilk olcumde belirlenir
_gpu_cache = None
_gpu_tick = 0


# ═════════════════════════════════════════════════════════════════════
# OLCUM
# ═════════════════════════════════════════════════════════════════════
def _gpu_via_pynvml():
    try:
        import pynvml
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        util = pynvml.nvmlDeviceGetUtilizationRates(h)
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        return {
            "util_pct": float(util.gpu),
            "mem_used_mb": round(mem.used / 1048576, 1),
            "mem_total_mb": round(mem.total / 1048576, 1),
            "mem_pct": round(mem.used / mem.total * 100, 1) if mem.total else 0.0,
        }
    except Exception:
        return None


def _gpu_via_smi():
    """nvidia-smi ile SIFIR ek bagimlilik. Surekli spawn etmemek icin
    cagiran taraf GPU_EVERY_N ile seyreltir."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        line = (out.stdout or "").strip().splitlines()[0]
        util, used, total = [p.strip() for p in line.split(",")[:3]]
        used_f, total_f = float(used), float(total)
        return {
            "util_pct": float(util),
            "mem_used_mb": used_f,
            "mem_total_mb": total_f,
            "mem_pct": round(used_f / total_f * 100, 1) if total_f else 0.0,
        }
    except Exception:
        return None


def read_gpu(force: bool = False):
    """GPU olcumu (pynvml -> nvidia-smi -> None). Sonuc onbelleklenir."""
    global _gpu_backend, _gpu_cache, _gpu_tick
    _gpu_tick += 1
    if not force and _gpu_cache is not None and (_gpu_tick % GPU_EVERY_N) != 1:
        return _gpu_cache
    if _gpu_backend in (None, "pynvml"):
        g = _gpu_via_pynvml()
        if g is not None:
            _gpu_backend, _gpu_cache = "pynvml", g
            return g
    g = _gpu_via_smi()
    _gpu_backend = "smi" if g is not None else None
    _gpu_cache = g
    return g


def _self_tree():
    """ALES'in kendi sureci + cocuklari (uvicorn worker, TTS, tarayici vb.)."""
    if psutil is None:
        return []
    try:
        me = psutil.Process(os.getpid())
        return [me] + me.children(recursive=True)
    except Exception:
        return []


def sample(force_gpu: bool = False) -> dict:
    """Anlik olcum. Hem ALES'in kendi kullanimi hem sistem geneli."""
    snap = {"time": time.time(), "psutil": psutil is not None}
    if psutil is None:
        snap.update({"self": {}, "system": {}, "gpu": read_gpu(force_gpu)})
        return snap

    ncpu = psutil.cpu_count() or 1
    total_ram = psutil.virtual_memory().total or 1

    self_cpu = 0.0
    self_rss = 0
    tree = _self_tree()
    for p in tree:
        try:
            # cpu_percent(None): son cagridan bu yana; ilk turda 0 dondurur.
            self_cpu += p.cpu_percent(None)
            self_rss += p.memory_info().rss
        except Exception:
            continue

    vm = psutil.virtual_memory()
    try:
        disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
        disk_pct = disk.percent
    except Exception:
        disk_pct = 0.0

    snap["self"] = {
        # tek-cekirdek yuzdelerini toplayip cekirdek sayisina bolerek
        # sistemle karsilastirilabilir bir "makinenin yuzde kaci" degeri
        "cpu": round(min(100.0, self_cpu / ncpu), 1),
        "ram": round(self_rss / total_ram * 100, 1),
        "ram_mb": round(self_rss / 1048576, 1),
        "procs": len(tree),
    }
    snap["system"] = {
        "cpu": round(psutil.cpu_percent(None), 1),
        "ram": round(vm.percent, 1),
        "ram_used_mb": round(vm.used / 1048576, 1),
        "ram_total_mb": round(vm.total / 1048576, 1),
        "disk": round(disk_pct, 1),
    }
    snap["gpu"] = read_gpu(force_gpu)
    return snap

# ═════════════════════════════════════════════════════════════════════
# ESIK DEGERLENDIRME
# ═════════════════════════════════════════════════════════════════════
def _cfg():
    """config.json'dan esik/kapsam/aralik oku (yoksa varsayilan)."""
    try:
        from config_manager import load_config
        cfg = load_config() or {}
    except Exception:
        cfg = {}
    th = dict(DEFAULT_THRESHOLDS)
    for k, v in (cfg.get("resource_thresholds") or {}).items():
        if k in th:
            try: th[k] = float(v)
            except Exception: pass
    scope = (cfg.get("resource_scope") or "self").lower()
    if scope not in ("self", "system"):
        scope = "self"
    try:
        interval = max(0.25, float(cfg.get("resource_interval_s", DEFAULT_INTERVAL_S)))
    except Exception:
        interval = DEFAULT_INTERVAL_S
    return th, scope, interval, bool(cfg.get("resource_guard", True))


def evaluate(snap: dict, thresholds: dict = None, scope: str = "self") -> dict:
    """Olcumu esiklerle karsilastir. Doner: {breached:[...], critical:bool,
    values:{cpu,ram,gpu}}. GPU olculemezse GPU esigi ATLANIR (uydurmayiz)."""
    th = thresholds or DEFAULT_THRESHOLDS
    src = snap.get(scope) or {}
    gpu = snap.get("gpu") or {}
    values = {
        "cpu": src.get("cpu"),
        "ram": src.get("ram"),
        # GPU her zaman cihaz geneli olculur (surec bazli GPU olcumu
        # tasinabilir degil) — scope'tan bagimsiz.
        "gpu": gpu.get("util_pct") if gpu else None,
    }
    breached, critical = [], False
    for key, val in values.items():
        limit = th.get(key)
        if val is None or limit is None:
            continue
        if val > limit:
            breached.append({"metric": key, "value": val, "limit": limit})
            if val > limit * CRITICAL_FACTOR:
                critical = True
    return {"breached": breached, "critical": critical, "values": values, "scope": scope}


# ═════════════════════════════════════════════════════════════════════
# IZLEYICI (arka plan thread) + CALLBACK KAYDI
# ═════════════════════════════════════════════════════════════════════
class ResourceMonitor:
    """Saniyede bir olcer; esik asiminda kayitli callback'leri cagirir.

    on_alert(report)   -> kullaniciya SOR ("modulleri kapatayim mi?")
    on_degrade(report) -> ISRARLI/KRITIK asim: otomatik dusuk-tuketim modu
    on_restore(report) -> kaynaklar rahatladi: eski haline don
    """

    def __init__(self):
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.last = {}
        self.degraded = False
        self._breach_streak = 0
        self._calm_streak = 0
        self._alerted = False
        self._ema = {}
        self._cbs = {"alert": [], "degrade": [], "restore": []}
        self.history = []              # son ~120 olcum (UI grafigi icin)

    # — callback kaydi —
    def register(self, event: str, fn):
        if event in self._cbs and callable(fn):
            self._cbs[event].append(fn)
        return self

    def _fire(self, event: str, report: dict):
        for fn in self._cbs.get(event, []):
            try:
                fn(report)
            except Exception as e:                       # callback ALES'i dusurmesin
                print(f"[RESOURCE] {event} callback hatasi: {e}")

    def _smooth(self, values: dict) -> dict:
        """EMA ile yumusat — tek bir ani zirve yuzunden UI kapatmayalim."""
        out = {}
        for k, v in values.items():
            if v is None:
                out[k] = None
                continue
            prev = self._ema.get(k)
            out[k] = v if prev is None else round(prev + _EMA_ALPHA * (v - prev), 1)
            self._ema[k] = out[k]
        return out

    def tick(self) -> dict:
        """Tek bir olcum+degerlendirme turu (test edilebilir olsun diye ayri)."""
        th, scope, _interval, guard_on = _cfg()
        snap = sample()
        report = evaluate(snap, th, scope)
        report["values"] = self._smooth(report["values"])
        # yumusatilmis degerlerle esikleri tekrar kontrol et
        report["breached"] = [
            {"metric": k, "value": v, "limit": th[k]}
            for k, v in report["values"].items()
            if v is not None and th.get(k) is not None and v > th[k]
        ]
        report["critical"] = any(
            b["value"] > b["limit"] * CRITICAL_FACTOR for b in report["breached"]
        )
        report["thresholds"] = th
        report["snapshot"] = snap
        report["degraded"] = self.degraded

        with self._lock:
            self.last = report
            self.history.append({
                "t": snap["time"],
                "cpu": report["values"].get("cpu"),
                "ram": report["values"].get("ram"),
                "gpu": report["values"].get("gpu"),
            })
            if len(self.history) > 120:
                self.history = self.history[-120:]

        if not guard_on:
            return report

        if report["breached"]:
            self._breach_streak += 1
            self._calm_streak = 0
            # 1) ilk asimda: SOR (item 8) — otomatik kapatma yok
            if not self._alerted and not self.degraded:
                self._alerted = True
                self._fire("alert", report)
            # 2) israrli ya da kritik asim: OTOMATIK dusur (item 1)
            if not self.degraded and (report["critical"] or self._breach_streak >= SUSTAINED_SAMPLES):
                self.degraded = True
                report["degraded"] = True
                report["reason"] = "critical" if report["critical"] else "sustained"
                self._fire("degrade", report)
        else:
            self._breach_streak = 0
            self._calm_streak += 1
            # histerezis: hemen geri donme, birkac sakin ornek bekle
            if self.degraded and self._calm_streak >= SUSTAINED_SAMPLES * 2:
                self.degraded = False
                self._alerted = False
                report["degraded"] = False
                self._fire("restore", report)
            elif self._calm_streak >= SUSTAINED_SAMPLES * 2:
                self._alerted = False
        return report

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:
                print(f"[RESOURCE] olcum hatasi: {e}")
            _th, _sc, interval, _g = _cfg()
            self._stop.wait(interval)

    def start(self):
        if psutil is None:
            print("[RESOURCE] psutil yok — kaynak izleme devre disi.")
            return self
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="ales-resmon", daemon=True)
        self._thread.start()
        print("[RESOURCE] Kaynak izleyici basladi.")
        return self

    def stop(self):
        self._stop.set()
        return self

    def status(self) -> dict:
        with self._lock:
            last = dict(self.last)
            hist = list(self.history)
        th, scope, interval, guard_on = _cfg()
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "guard": guard_on,
            "degraded": self.degraded,
            "scope": scope,
            "interval_s": interval,
            "thresholds": th,
            "values": last.get("values", {}),
            "breached": last.get("breached", []),
            "snapshot": last.get("snapshot", {}),
            "gpu_backend": _gpu_backend,
            "history": hist,
            "psutil": psutil is not None,
        }


# tekil ornek (main.py bunu kullanir)
monitor = ResourceMonitor()

