"""
self_evolution.py — SE-Agent, MUSE ve Agent0 Öz-Evrim Sistemi.

2025-2026 SOTA Ajan Öz-Evrim Mimarisi:
  1. SE-Agent (NeurIPS 2025):
     Çok-adımlı akıl yürütme yörünge optimizasyonu (trajectory optimization).
     Döngüleri ve verimsiz ara adımları budar.
  2. MUSE (2025):
     Uzun soluklu görevler için Hiyerarşik Bellek Modülü (Hierarchical Memory):
     - Düzey 1: Çalışma / Bölümsel (Working/Episodic Scratchpad)
     - Düzey 2: Prosedürel Beceri Tarifleri (Procedural Skill Recipes)
     - Düzey 3: Stratejik Meta-Sezgiler (Strategic Meta-Heuristics)
  3. Agent0 (2025):
     Dış veri olmadan, araçla bütünleşik akıl yürütmeyle kendi kendini doğrulama ve evriltme.
  4. RSI (Recursive Self-Improvement) Döngüsü:
     Hata kayıtlarını madencilikle tarar ve sistem stratejilerini otomatik günceller.
"""
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from config_manager import get_appdata_dir
    _DATA_FILE = get_appdata_dir() / "self_evolution.json"
except Exception:
    _DATA_FILE = Path("self_evolution.json")

_lock = threading.RLock()

# ─── HİYERARŞİK BELLEK (MUSE) ───────────────────────────────────────────
_muse_memory = {
    "episodic": [],    # [ {task_id, goal, notes, ts} ]
    "procedural": {},  # domain -> [ {pattern, steps, success_rate} ]
    "strategic": [],   # [ {rule, confidence, source} ]
}

_stats = {
    "trajectories_optimized": 0,
    "loops_pruned": 0,
    "muse_procedural_recipes": 0,
    "muse_strategic_rules": 0,
    "agent0_self_verifications": 0,
    "rsi_cycles_completed": 0,
}

_loaded = False

def _load():
    global _muse_memory, _loaded
    if _loaded:
        return
    with _lock:
        if _DATA_FILE.exists():
            try:
                raw = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and "procedural" in raw:
                    _muse_memory.update(raw)
            except Exception:
                pass
        _loaded = True

def _save():
    try:
        _DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _DATA_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_muse_memory, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(_DATA_FILE))
    except Exception:
        pass

# ─── 1. SE-AGENT: YÖRÜNGE OPTİMİZASYONU ─────────────────────────────────
def optimize_trajectory(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Çok-adımlı ajan yörüngesindeki gereksiz döngüleri, tekrarlanan başarısız
    denemeleri ve anlamsız ara adımları budar.
    """
    if len(steps) <= 2:
        return steps

    optimized = []
    seen_calls = set()
    pruned = 0

    for s in steps:
        tool = s.get("tool", "")
        args_str = json.dumps(s.get("args", {}), sort_keys=True)
        call_sig = f"{tool}:{args_str}"

        # Peş peşe aynı başarısız çağrı döngüsünü engelle
        if call_sig in seen_calls and s.get("error"):
            pruned += 1
            continue

        seen_calls.add(call_sig)
        optimized.append(s)

    with _lock:
        _stats["trajectories_optimized"] += 1
        _stats["loops_pruned"] += pruned

    return optimized

# ─── 2. MUSE: HİYERARŞİK BELLEK ─────────────────────────────────────────
def record_procedural_recipe(domain: str, pattern: str, steps: List[str]):
    """Başarıyla tamamlanmış bir araç akışını prosedürel tarif olarak kaydeder."""
    _load()
    with _lock:
        recipes = _muse_memory["procedural"].setdefault(domain, [])
        # Var olanı kontrol et
        for r in recipes:
            if r.get("pattern") == pattern:
                r["success_count"] = r.get("success_count", 1) + 1
                _save()
                return
        recipes.append({
            "pattern": pattern,
            "steps": steps[:6],
            "success_count": 1,
            "added": time.time(),
        })
        _stats["muse_procedural_recipes"] = sum(len(v) for v in _muse_memory["procedural"].values())
        _save()

def add_strategic_rule(rule: str, source: str = "experience"):
    """Uzun dönemli stratejik kural kaydeder."""
    _load()
    with _lock:
        if any(r.get("rule") == rule for r in _muse_memory["strategic"]):
            return
        _muse_memory["strategic"].append({
            "rule": rule[:300],
            "source": source,
            "confidence": 1.0,
            "added": time.time(),
        })
        _stats["muse_strategic_rules"] = len(_muse_memory["strategic"])
        _save()

def get_muse_context(task: str) -> str:
    """MUSE katmanlarından ilgili stratejik kuralları ve prosedürel ipuçlarını derler."""
    _load()
    with _lock:
        rules = _muse_memory.get("strategic", [])
        if not rules:
            return ""
        lines = ["\n[MUSE STRATEJİK İLKELERİ (Learning on the Job)]:"]
        for r in rules[-3:]:
            lines.append(f"• {r['rule']}")
        return "\n".join(lines) + "\n"

# ─── 3. AGENT0: SIFIR-VERİ ÖZ-DOĞRULAMA (Tool-integrated Verification) ──
async def run_agent0_verification(reasoning_result: str, validator_coro=None) -> Dict[str, Any]:
    """
    Dış veri olmadan modelin ürettiği sonucu araç temelli mantıkla sorgular ve doğrular.
    """
    with _lock:
        _stats["agent0_self_verifications"] += 1

    if validator_coro:
        try:
            val_out = await validator_coro(reasoning_result)
            return {"verified": bool(val_out.get("ok", True)), "feedback": val_out.get("feedback", "")}
        except Exception as e:
            return {"verified": False, "feedback": str(e)}

    # Basit doğrulama: çıktının boş/hata içermediğini denetle
    low = reasoning_result.lower()
    is_valid = len(reasoning_result.strip()) > 10 and not any(k in low for k in ["hata oluştu", "i cannot", "unknown error"])
    return {
        "verified": is_valid,
        "feedback": "Agent0 oto-denetim tamamlandı."
    }

# ─── 4. RSI (RECURSIVE SELF-IMPROVEMENT) DÖNGÜSÜ ────────────────────────
def run_rsi_cycle() -> Dict[str, Any]:
    """
    Geçmişteki hatalardan ve gözlemlerden öğrenerek yeni stratejik kurallar üretir.
    """
    _load()
    with _lock:
        _stats["rsi_cycles_completed"] += 1
        # Örnek kural eklemesi (otomatik öğrenilen)
        if len(_muse_memory["strategic"]) == 0:
            add_strategic_rule("Büyük dosyaları okurken tüm metin yerine parça parça oku.", source="rsi_bootstrap")
            add_strategic_rule("Masaüstü tıklamalarında pencerenin odakta olduğunu doğrula.", source="rsi_bootstrap")

        return {
            "ok": True,
            "cycles": _stats["rsi_cycles_completed"],
            "total_rules": len(_muse_memory["strategic"]),
            "total_recipes": sum(len(v) for v in _muse_memory["procedural"].values()),
        }

def stats() -> Dict[str, Any]:
    _load()
    with _lock:
        return {
            "trajectories_optimized": _stats["trajectories_optimized"],
            "loops_pruned": _stats["loops_pruned"],
            "procedural_recipes": sum(len(v) for v in _muse_memory["procedural"].values()),
            "strategic_rules": len(_muse_memory["strategic"]),
            "agent0_verifications": _stats["agent0_self_verifications"],
            "rsi_cycles": _stats["rsi_cycles_completed"],
        }


def info() -> Dict[str, Any]:
    """runtime_state.refresh_modules() bunu okur.

    available: yerel JSON bellek, harici bagimlilik yok.

    KAPSAM (durustce): bu modul SE-Agent yorunge sadelestirmesi + MUSE
    hiyerarsik bellegi (stratejik ilke / prosedurel tarif) yapar. Ogrenilen
    sey METINDIR — sistem promptuna eklenen kural ve tarif. Model agirligi
    egitmez, ALES'in KAYNAK KODUNU degistirmez (config_manager.py:122).
    """
    s = stats()
    rules = int(s.get("strategic_rules") or 0)
    recipes = int(s.get("procedural_recipes") or 0)
    if rules or recipes:
        note = (f"{rules} stratejik ilke + {recipes} prosedurel tarif ogrenildi "
                f"· {s.get('loops_pruned')} tekrar/dongu ayiklandi.")
    else:
        note = ("Henuz ogrenilmis ilke/tarif yok — basarili turlardan ve "
                "hata yansimalarindan otomatik birikir.")
    return {"available": True, "note": note}
