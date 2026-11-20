"""
adaptive_timeouts.py — Dinamik ve İstatistiki Zaman Aşımı Yöneticisi (Adaptive Timeouts).

Sabit (hardcoded) zaman aşımları yerine, her sağlayıcının ve katmanın gerçek yanıt
sürelerini (EWMA - Üssel Ağırlıklı Hareketli Ortalama ve varyans) izler.
Formül: timeout = min(tavan, max(taban, ortalama + 2.5 * standart_sapma))
Böylece yoğun ağ koşullarında erken zaman aşımı yaşanmaz; hızlı bağlantılarda
ise gereksiz saniyelerce beklenmez.
"""
import json
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from config_manager import get_appdata_dir
    _FILE = get_appdata_dir() / "adaptive_timeouts.json"
except Exception:
    _FILE = Path("adaptive_timeouts.json")

# Katman bazlı taban ve tavan süreleri (saniye)
BOUNDS = {
    "fast":         {"min": 3.0,  "max": 25.0,  "default": 12.0},
    "fallback":     {"min": 5.0,  "max": 35.0,  "default": 20.0},
    "vision":       {"min": 6.0,  "max": 45.0,  "default": 25.0},
    "code":         {"min": 8.0,  "max": 60.0,  "default": 45.0},
    "unrestricted": {"min": 10.0, "max": 75.0,  "default": 60.0},
    "heavy":        {"min": 20.0, "max": 120.0, "default": 90.0},
}

_lock = threading.RLock()
_data: Dict[str, Dict[str, float]] = {}
_loaded = False

def _load():
    global _data, _loaded
    if _loaded:
        return
    with _lock:
        if _FILE.exists():
            try:
                _data = json.loads(_FILE.read_text(encoding="utf-8"))
            except Exception:
                _data = {}
        _loaded = True

def _save():
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(_FILE))
    except Exception:
        pass

def record_latency(layer_or_provider: str, elapsed_s: float, success: bool = True):
    """Bir model çağrısının yanıt süresini kaydeder ve istatistikleri günceller."""
    _load()
    k = str(layer_or_provider).lower()
    t = max(0.05, float(elapsed_s))
    alpha = 0.20  # Son çağrının ağırlığı

    with _lock:
        st = _data.setdefault(k, {
            "avg": t,
            "var": 0.5,
            "samples": 0,
            "successes": 0,
            "failures": 0,
            "last_t": t,
            "updated": time.time(),
        })

        st["samples"] += 1
        if success:
            st["successes"] += 1
        else:
            st["failures"] += 1

        # EWMA Ortalama ve Varyans güncellemesi
        diff = t - st["avg"]
        st["avg"] = round(st["avg"] + alpha * diff, 3)
        st["var"] = round(st["var"] + alpha * (diff ** 2 - st["var"]), 3)
        st["last_t"] = round(t, 3)
        st["updated"] = time.time()
        _save()

def get_timeout(layer_or_provider: str, fallback: Optional[float] = None) -> float:
    """
    Katman veya sağlayıcı için anlık dinamik zaman aşımını hesaplar.
    """
    _load()
    k = str(layer_or_provider).lower()
    bounds = BOUNDS.get(k, {"min": 4.0, "max": 60.0, "default": fallback or 15.0})

    with _lock:
        st = _data.get(k)
        if not st or st.get("samples", 0) < 3:
            return float(bounds.get("default", fallback or 15.0))

        avg = st["avg"]
        std = math.sqrt(max(0.01, st["var"]))
        # 2.5 sigma güven aralığı
        calculated = avg + 2.5 * std

        return float(min(bounds["max"], max(bounds["min"], round(calculated, 1))))

def get_stats() -> Dict[str, Any]:
    _load()
    with _lock:
        out = {}
        for k, v in _data.items():
            std = round(math.sqrt(max(0.01, v.get("var", 0))), 2)
            out[k] = {
                "avg_s": v.get("avg", 0),
                "std_s": std,
                "dynamic_timeout_s": get_timeout(k),
                "samples": v.get("samples", 0),
                "success_rate": round(v.get("successes", 0) / max(1, v.get("samples", 1)), 2),
                "last_s": v.get("last_t", 0),
            }
        return out

def reset_stats():
    global _data
    with _lock:
        _data = {}
        _save()


def info() -> Dict[str, Any]:
    """runtime_state.refresh_modules() bunu okur.

    available: yerel JSON, harici bagimlilik yok.

    Bu modul GERCEKTEN canli yolda: model_router her katman cagrisinda
    get_timeout(katman) sorar ve sonucu record() ile geri yazar
    (model_router.py:57-59, 98-99, 317-345, 362-365). Yani buradaki
    ortalamalar gozlem degil, o anda uygulanan zaman asimidir.
    """
    s = get_stats()
    if not s:
        note = ("Henuz olcum yok — ilk cagrilarda varsayilan sinirlar kullanilir, "
                "sonra her katman icin ogrenilir.")
    else:
        top = sorted(s.items(), key=lambda kv: -(kv[1].get("samples") or 0))[:3]
        note = (f"{len(s)} katman ogrenildi · " + " · ".join(
            f"{k}: {v.get('dynamic_timeout_s')}s ({v.get('samples')} ornek)"
            for k, v in top))
    return {"available": True, "note": note}
