"""
versioned_config.py — Versiyonlu Yapılandırma ve Anında Geri Alma (Instant Rollback).

Amacı:
  - config.json, model eşlemeleri, sistem promptları veya beceri listelerinde yapılan
    her değişikliği otomatik olarak zaman damgası ve sebep ile versiyonlar.
  - Tek tıkla herhangi bir önceki versiyona geri alma (1-click rollback) imkanı sunar.
"""
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from config_manager import get_appdata_dir
    _HISTORY_FILE = get_appdata_dir() / "config_versions.json"
except Exception:
    _HISTORY_FILE = Path("config_versions.json")

MAX_VERSIONS = 50

_lock = threading.RLock()
_versions: List[Dict[str, Any]] = []
_loaded = False

def _load():
    global _versions, _loaded
    if _loaded:
        return
    with _lock:
        if _HISTORY_FILE.exists():
            try:
                raw = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    _versions = raw
            except Exception:
                _versions = []
        _loaded = True

def _save():
    try:
        _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _HISTORY_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_versions, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(_HISTORY_FILE))
    except Exception:
        pass

def record_version(category: str, data: Dict[str, Any], reason: str = "") -> str:
    """
    Mevcut yapılandırma durumunun bir anlık görüntüsünü (snapshot) kaydeder.
    """
    _load()
    raw_str = json.dumps(data, sort_keys=True)
    v_hash = hashlib.sha1(raw_str.encode("utf-8")).hexdigest()[:8]
    vid = f"v_{category}_{int(time.time())}_{v_hash}"

    entry = {
        "version_id": vid,
        "category": category,
        "timestamp": time.time(),
        "time_str": time.strftime("%Y-%m-%d %H:%M:%S"),
        "reason": reason or "Otomatik yapılandırma güncellemesi",
        "data": data,
    }

    with _lock:
        # En son versiyon ile birebir aynıysa gereksiz çoğaltma yapma
        if _versions and _versions[-1].get("category") == category:
            last_data_str = json.dumps(_versions[-1].get("data", {}), sort_keys=True)
            if last_data_str == raw_str:
                return _versions[-1]["version_id"]

        _versions.append(entry)
        if len(_versions) > MAX_VERSIONS:
            _versions.pop(0)
        _save()

    return vid

def list_versions(category: Optional[str] = None, limit: int = 25) -> List[Dict[str, Any]]:
    """Kayıtlı versiyonların özet listesini getirir."""
    _load()
    with _lock:
        items = _versions
        if category:
            items = [v for v in items if v.get("category") == category]
        out = []
        for v in reversed(items[-limit:]):
            out.append({
                "version_id": v["version_id"],
                "category": v.get("category", ""),
                "timestamp": v.get("timestamp", 0),
                "time_str": v.get("time_str", ""),
                "reason": v.get("reason", ""),
                "keys_count": len(v.get("data", {})),
            })
        return out

def get_version(version_id: str) -> Optional[Dict[str, Any]]:
    _load()
    with _lock:
        for v in _versions:
            if v["version_id"] == version_id:
                return dict(v)
        return None

def rollback_to_version(version_id: str, apply_fn=None) -> Dict[str, Any]:
    """
    Belirtilen versiyonu yükler ve yapılandırmaya uygular.
    """
    v = get_version(version_id)
    if not v:
        return {"ok": False, "error": f"Versiyon bulunamadı: {version_id}"}

    data = v["data"]
    if apply_fn and callable(apply_fn):
        try:
            apply_fn(data)
        except Exception as e:
            return {"ok": False, "error": f"Uygulama hatası: {e}"}

    # Geri alma işlemini de yeni bir versiyon olarak kaydet
    record_version(v.get("category", "config"), data, reason=f"Geri alma: {version_id} uygulandı")

    return {
        "ok": True,
        "restored_version": version_id,
        "category": v.get("category"),
        "timestamp": v.get("timestamp"),
    }


def stats() -> Dict[str, Any]:
    _load()
    with _lock:
        cats: Dict[str, int] = {}
        for v in _versions:
            c = v.get("category", "config")
            cats[c] = cats.get(c, 0) + 1
        return {"total_versions": len(_versions), "max_versions": MAX_VERSIONS,
                "by_category": cats,
                "latest": (_versions[-1].get("timestamp") if _versions else None)}


def info() -> Dict[str, Any]:
    """runtime_state.refresh_modules() bunu okur.

    available: yerel JSON gecmis dosyasi, harici bagimlilik yok.

    KAPSAM: burada tutulan sey yapilandirma VERISININ anlik goruntusudur —
    kod surumu degil. Geri alma da config'i eski haline yazar, dosyalari
    degistirmez. En fazla MAX_VERSIONS surum saklanir, eskisi dusurulur.
    """
    s = stats()
    n = int(s.get("total_versions") or 0)
    if n:
        cats = ", ".join(f"{k}:{v}" for k, v in (s.get("by_category") or {}).items())
        note = f"{n}/{s.get('max_versions')} surum saklaniyor ({cats})."
    else:
        note = ("Henuz surum kaydi yok — her yapilandirma kaydinda otomatik "
                "anlik goruntu alinir, panelden geri alinabilir.")
    return {"available": True, "note": note}
