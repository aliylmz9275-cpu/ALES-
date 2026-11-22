"""
telemetry.py — ALES Performans, Güvenilirlik & Telemetri İzleme Modülü (Faz 5).

Bu modül gerçek zamanlı olarak şunları takip eder:
  1) Model Sağlayıcıları Başarı / Başarısızlık Oranları (Groq, NVIDIA, Gemini vb.)
  2) Anlamsal Önbellek (Semantic Cache) İsabet (Hit), Iskalama (Miss) ve Aksiyon Baypas Oranları
  3) GUI / Masaüstü Eylemleri (PyAutoGUI, Playwright, Native Desktop) Başarı Oranları
  4) Yönetici-Yürütücü Görev Başarı Oranları

Veriler %APPDATA%\\ALES\\telemetry.json dosyasına atomik olarak kaydedilir ve UI "METRİKLER"
sekmesinden yüzdelik oranlar olarak canlı izlenir.
"""

import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional

try:
    from config_manager import get_appdata_dir
    _TELEMETRY_FILE = get_appdata_dir() / "telemetry.json"
except Exception:
    _TELEMETRY_FILE = Path("telemetry.json")

_lock = threading.Lock()

_default_state = {
    "api_calls": {},     # {provider: {"success": int, "fail": int, "total_time": float}}
    "cache": {
        "hits": 0,
        "misses": 0,
        "bypasses": 0,   # Aksiyon kelimesi nedeniyle koruma amaçlı atlananlar
    },
    "gui_actions": {
        "success": 0,
        "fail": 0,
        "tools": {}      # {tool_name: {"success": int, "fail": int}}
    },
    "tasks": {
        "success": 0,
        "fail": 0
    },
    "started_at": time.time(),
    "last_updated": time.time()
}

_state: Dict[str, Any] = dict(_default_state)


def _load():
    global _state
    if not _TELEMETRY_FILE.exists():
        _state = dict(_default_state)
        return
    try:
        with open(_TELEMETRY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                _state = data
                _state.setdefault("api_calls", {})
                _state.setdefault("cache", {"hits": 0, "misses": 0, "bypasses": 0})
                _state.setdefault("gui_actions", {"success": 0, "fail": 0, "tools": {}})
                _state.setdefault("tasks", {"success": 0, "fail": 0})
    except Exception as e:
        print(f"[TELEMETRY] Yükleme hatası: {e}")
        _state = dict(_default_state)


def _save():
    try:
        _TELEMETRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _TELEMETRY_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_state, f, ensure_ascii=False, indent=2)
        tmp.replace(_TELEMETRY_FILE)
    except Exception as e:
        print(f"[TELEMETRY] Kaydetme hatası: {e}")


# İlk yükleme
_load()


def record_api_call(provider: str, success: bool, latency_s: float = 0.0):
    """API çağrısının sonucunu ve yanıt süresini kaydeder."""
    prov = (provider or "unknown").strip().title()
    with _lock:
        if prov not in _state["api_calls"]:
            _state["api_calls"][prov] = {"success": 0, "fail": 0, "total_time": 0.0}
        entry = _state["api_calls"][prov]
        if success:
            entry["success"] += 1
        else:
            entry["fail"] += 1
        entry["total_time"] += float(latency_s)
        _state["last_updated"] = time.time()
        _save()


def record_cache(hit: bool = False, miss: bool = False, bypass: bool = False):
    """Anlamsal önbellek sorgu sonucunu kaydeder."""
    with _lock:
        c = _state["cache"]
        if bypass:
            c["bypasses"] = c.get("bypasses", 0) + 1
        elif hit:
            c["hits"] = c.get("hits", 0) + 1
        elif miss:
            c["misses"] = c.get("misses", 0) + 1
        _state["last_updated"] = time.time()
        _save()


def record_gui_action(tool: str, success: bool):
    """Masaüstü/GUI eyleminin sonucunu kaydeder."""
    t_name = (tool or "gui_action").strip().lower()
    with _lock:
        g = _state["gui_actions"]
        if success:
            g["success"] = g.get("success", 0) + 1
        else:
            g["fail"] = g.get("fail", 0) + 1

        tools = g.setdefault("tools", {})
        if t_name not in tools:
            tools[t_name] = {"success": 0, "fail": 0}
        if success:
            tools[t_name]["success"] += 1
        else:
            tools[t_name]["fail"] += 1

        _state["last_updated"] = time.time()
        _save()


def record_task(success: bool):
    """Yönetici görev sonucunu kaydeder."""
    with _lock:
        t = _state["tasks"]
        if success:
            t["success"] = t.get("success", 0) + 1
        else:
            t["fail"] = t.get("fail", 0) + 1
        _state["last_updated"] = time.time()
        _save()


def get_metrics() -> Dict[str, Any]:
    """Özet yüzdelikleri ve istatistikleri UI için hesaplar."""
    with _lock:
        api_summary = {}
        total_api_success = 0
        total_api_calls = 0

        for prov, data in _state.get("api_calls", {}).items():
            succ = data.get("success", 0)
            fail = data.get("fail", 0)
            total = succ + fail
            rate = round((succ / total * 100.0), 1) if total > 0 else 0.0
            avg_lat = round(data.get("total_time", 0.0) / total, 2) if total > 0 else 0.0
            api_summary[prov] = {
                "success": succ,
                "fail": fail,
                "total": total,
                "rate_pct": rate,
                "avg_latency_s": avg_lat,
            }
            total_api_success += succ
            total_api_calls += total

        # Cache metrikleri
        c = _state.get("cache", {})
        c_hits = c.get("hits", 0)
        c_misses = c.get("misses", 0)
        c_bypasses = c.get("bypasses", 0)
        c_evaluated = c_hits + c_misses
        c_hit_rate = round((c_hits / c_evaluated * 100.0), 1) if c_evaluated > 0 else 0.0

        # GUI metrikleri
        g = _state.get("gui_actions", {})
        g_succ = g.get("success", 0)
        g_fail = g.get("fail", 0)
        g_total = g_succ + g_fail
        g_rate = round((g_succ / g_total * 100.0), 1) if g_total > 0 else 100.0

        # Görev metrikleri
        t = _state.get("tasks", {})
        t_succ = t.get("success", 0)
        t_fail = t.get("fail", 0)
        t_total = t_succ + t_fail
        t_rate = round((t_succ / t_total * 100.0), 1) if t_total > 0 else 100.0

        overall_api_rate = round((total_api_success / total_api_calls * 100.0), 1) if total_api_calls > 0 else 100.0

        return {
            "api": api_summary,
            "cache": {
                "hits": c_hits,
                "misses": c_misses,
                "bypasses": c_bypasses,
                "evaluated": c_evaluated,
                "total_queries": c_evaluated + c_bypasses,
                "hit_rate_pct": c_hit_rate
            },
            "gui": {
                "success": g_succ,
                "fail": g_fail,
                "total": g_total,
                "rate_pct": g_rate,
                "tools": g.get("tools", {})
            },
            "tasks": {
                "success": t_succ,
                "fail": t_fail,
                "total": t_total,
                "rate_pct": t_rate
            },
            "summary": {
                "total_api_calls": total_api_calls,
                "overall_api_rate_pct": overall_api_rate,
                "cache_hit_rate_pct": c_hit_rate,
                "gui_success_rate_pct": g_rate,
                "task_success_rate_pct": t_rate,
            },
            "last_updated": _state.get("last_updated", time.time())
        }


def reset_metrics():
    """Tüm sayaçları sıfırlar."""
    global _state
    with _lock:
        _state = {
            "api_calls": {},
            "cache": {"hits": 0, "misses": 0, "bypasses": 0},
            "gui_actions": {"success": 0, "fail": 0, "tools": {}},
            "tasks": {"success": 0, "fail": 0},
            "started_at": time.time(),
            "last_updated": time.time()
        }
        _save()
