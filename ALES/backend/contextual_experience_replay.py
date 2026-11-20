"""
contextual_experience_replay.py — Contextual Experience Replay (CER) Eğitimsiz Öz-İyileştirme.

Referans:
  - "Contextual Experience Replay for Self-Improvement of Language Agents" (2026).
  - WebArena ve VisualWebArena üzerinde SOTA başarı sağlayan bağlam içi deneyim tekrarı.

Prensip:
  Model ağırlıklarını güncellemeden (training-free), ajanın kendi başarı ve hatalarından
  çıkardığı yüksek kaliteli etkileşim yörüngelerini (trajectories) kaydeder ve
  benzer yeni görevlerde bu deneyimleri bağlam penceresine enjekte ederek başarı oranını artırır.
"""
import difflib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from config_manager import get_appdata_dir
    _CER_FILE = get_appdata_dir() / "cer_experiences.json"
except Exception:
    _CER_FILE = Path("cer_experiences.json")

MAX_EXPERIENCES = 150

_lock = threading.RLock()
_experiences: List[Dict[str, Any]] = []
_loaded = False

_stats = {
    "experiences_recorded": 0,
    "success_trajectories": 0,
    "failure_reflections": 0,
    "replays_injected": 0,
}

def _load_data():
    global _experiences, _loaded
    if _loaded:
        return
    with _lock:
        if _CER_FILE.exists():
            try:
                raw = json.loads(_CER_FILE.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    _experiences = raw
            except Exception:
                _experiences = []
        _loaded = True

def _save_data():
    try:
        _CER_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CER_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_experiences, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(_CER_FILE))
    except Exception:
        pass

def record_experience(task: str, trajectory: List[Dict[str, Any]], success: bool,
                      reflection: str = "", tags: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Tamamlanan bir görevin etkileşim yörüngesini ve sonucunu kaydeder.
    """
    _load_data()
    entry = {
        "id": f"exp_{int(time.time() * 1000)}",
        "task": task[:500],
        "trajectory": trajectory[:8],   # En kritik ilk 8 adım
        "success": bool(success),
        "reflection": reflection[:500],
        "tags": list(tags or []),
        "timestamp": time.time(),
    }

    with _lock:
        _experiences.append(entry)
        if len(_experiences) > MAX_EXPERIENCES:
            # En eski veya başarısız olanları temizle
            _experiences.pop(0)

        _stats["experiences_recorded"] += 1
        if success:
            _stats["success_trajectories"] += 1
        else:
            _stats["failure_reflections"] += 1

        _save_data()

    return entry

def retrieve_relevant_experiences(query: str, k: int = 2) -> List[Dict[str, Any]]:
    """
    Mevcut sorguya anlamsal veya metinsel olarak en çok benzeyen geçmiş deneyimleri çeker.
    """
    _load_data()
    if not query or not _experiences:
        return []

    q_low = query.strip().lower()
    scored = []

    with _lock:
        for exp in _experiences:
            task_low = exp["task"].lower()
            sim = difflib.SequenceMatcher(None, q_low[:300], task_low[:300]).ratio()
            # Başarılı deneyimlere öncelik puanı ver
            if exp["success"]:
                sim += 0.15
            scored.append((sim, exp))

    scored.sort(key=lambda x: x[0], reverse=True)
    # Eşik değer: en az 0.3 benzerlik
    results = [exp for score, exp in scored[:k] if score >= 0.3]
    if results:
        with _lock:
            _stats["replays_injected"] += len(results)
    return results

def format_cer_prompt_injection(query: str) -> str:
    """
    Yeni model istemine eklenecek CER bağlam yönergesi üretir.
    """
    replays = retrieve_relevant_experiences(query, k=2)
    if not replays:
        return ""

    lines = ["\n[GEÇMİŞ DENEYİM VE DERSLER (Contextual Experience Replay)]:"]
    for i, r in enumerate(replays, 1):
        status_text = "BAŞARILI YÖRÜNGE" if r["success"] else "DÜZELTİLMİŞ HATA"
        lines.append(f"Deneyim #{i} ({status_text}) — Görev: \"{r['task']}\"")
        if r["trajectory"]:
            steps = " -> ".join([step.get("action", step.get("tool", "adım")) for step in r["trajectory"][:4]])
            lines.append(f"  İzlenen adımlar: {steps}")
        if r["reflection"]:
            lines.append(f"  Çıkarılan ders: {r['reflection']}")

    lines.append("Lütfen benzer görevde bu deneyimleri ve başarılı kalıpları göz önünde bulundur.\n")
    return "\n".join(lines)

def stats() -> Dict[str, Any]:
    _load_data()
    with _lock:
        return {
            "total_experiences": len(_experiences),
            "max_experiences": MAX_EXPERIENCES,
            "recorded": _stats["experiences_recorded"],
            "successes": _stats["success_trajectories"],
            "reflections": _stats["failure_reflections"],
            "replays_injected": _stats["replays_injected"],
        }

def list_experiences(limit: int = 30) -> List[Dict[str, Any]]:
    _load_data()
    with _lock:
        return list(reversed(_experiences[-limit:]))

def clear() -> Dict[str, Any]:
    global _experiences
    with _lock:
        n = len(_experiences)
        _experiences.clear()
        _save_data()
        return {"ok": True, "cleared": n}


def info() -> Dict[str, Any]:
    """runtime_state.refresh_modules() bunu okur.

    available: yerel JSON arsivi, harici bagimlilik yok.

    CER "egitim gerektirmeyen oz-gelisim"dir: model AGIRLIKLARI degismez,
    degisen sey baglam penceresine ne konuldugudur. Yani buradaki gelisme
    gercek ama SINIRLI — arsiv bosken hicbir etkisi olmaz, bu yuzden notta
    kac yorunge biriktigi durustce yazilir.
    """
    s = stats()
    tot = int(s.get("total_experiences") or 0)
    if tot:
        note = (f"{tot} yorunge arsivde ({s.get('successes')} basarili, "
                f"{s.get('reflections')} hatali) · {s.get('replays_injected')} kez "
                f"baglama enjekte edildi.")
    else:
        note = ("Arsiv bos — henuz enjekte edilecek gecmis yorunge yok. "
                "Her tur sonunda otomatik birikir.")
    return {"available": True, "note": note}
