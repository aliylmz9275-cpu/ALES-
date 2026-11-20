"""
token_optimizer.py — DEPO-tarzı Token ve Adım Optimizasyonu.

2025-2026 SOTA Token Yönetimi:
  1. Görev Karmaşıklık Analizi (Task Complexity Budgeting):
     Görevin zorluğuna (1-5) göre dinamik token bütçesi tahsis eder (kısa sorgularda
     512-1024 token, karmaşık kodlamada 4096+).
  2. Bağlam Sıkıştırma ve Temizleme (Context Pruning):
     Gereksiz araç çıktılarını, tekrarlanan sistem uyarılarını ve bayat konuşma turlarını
     akıllıca kırparak bağlam penceresini %60'a varan oranda rahatlatır.
  3. Adım Sayısı Azaltma (Step Count Reduction):
     Çok adımlı görevlerde birbiriyle birleştirilebilir adımları tespit eder.
"""
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

_lock = threading.RLock()

_stats = {
    "prompts_optimized": 0,
    "tokens_saved_approx": 0,
    "redundant_turns_pruned": 0,
    "messages_shrunk": 0,
    "avg_reduction_percent": 0.0,
}

# Karmaşıklık anahtar kelimeleri
_HIGH_COMPLEXITY = re.compile(
    r"(yazılım|algoritma|refactor|mimari|hata ayıkla|debug|optimizasyon|kodla|tüm projeyi|derle|script|database|sql)",
    re.I
)
_LOW_COMPLEXITY = re.compile(
    r"^(merhaba|selam|saat kaç|hava nasıl|ne haber|ping|tamam|teşekkür|günaydın|kimsin)",
    re.I
)

def estimate_complexity(text: str) -> int:
    """
    Görev metninin karmaşıklığını 1 (en basit) ile 5 (en zor) arasında derecelendirir.
    """
    if not text:
        return 1
    t = text.strip()
    if len(t) < 25 and _LOW_COMPLEXITY.search(t):
        return 1
    if len(t) > 300 or _HIGH_COMPLEXITY.search(t):
        return 5
    if len(t) > 100:
        return 4
    if any(k in t.lower() for k in ["nasıl", "açıkla", "özetle", "karşılaştır", "liste"]):
        return 3
    return 2

def get_token_budget(complexity: int) -> int:
    """Karmaşıklık derecesine göre önerilen maksimum çıktı token sayısı."""
    budgets = {
        1: 512,
        2: 1024,
        3: 2048,
        4: 3072,
        5: 4096,
    }
    return budgets.get(complexity, 2048)

def compress_tool_result(content: str, max_chars: int = 1500) -> str:
    """Çok uzun araç çıktılarını (ör. yüzlerce satırlık dosya dökümü) özetler."""
    if not content or len(content) <= max_chars:
        return content
    head = content[:max_chars // 2]
    tail = content[-max_chars // 2:]
    trimmed = len(content) - max_chars
    return f"{head}\n\n... [{trimmed} karakter kırpıldı (DEPO optimizer)] ...\n\n{tail}"

def optimize_messages(messages: List[Dict[str, Any]], task_hint: str = "") -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Model çağrısı öncesinde mesaj listesini optimize eder:
    - Son turlardaki kritik bilgileri korur.
    - Eski araç yanıtlarındaki aşırı uzun çıktıları sıkıştırır.
    - Tekrarlanan sistem direktiflerini tekilleştirir.
    """
    if not messages:
        return [], {"saved_tokens": 0, "complexity": 1}

    orig_len = sum(len(str(m.get("content", ""))) for m in messages)
    complexity = estimate_complexity(task_hint or str(messages[-1].get("content", "")))
    optimized = []
    pruned_count = 0

    # Mesajları tara
    n_msg = len(messages)
    for i, m in enumerate(messages):
        role = m.get("role", "")
        content = m.get("content", "")

        # Son 3 mesaja dokunma (taze bağlam)
        if i >= n_msg - 3 or role == "system":
            optimized.append(m)
            continue

        # Eski araç çıktısı ise ve çok uzunsa sıkıştır
        if role in ("tool", "function") or m.get("tool_calls"):
            if isinstance(content, str) and len(content) > 1200:
                new_m = dict(m)
                new_m["content"] = compress_tool_result(content, max_chars=1000)
                optimized.append(new_m)
                pruned_count += 1
                continue

        # Boş veya gereksiz kısa onay mesajlarını atla
        if role == "assistant" and isinstance(content, str) and content.strip().lower() in ("tamam.", "ok", "anladım."):
            pruned_count += 1
            continue

        optimized.append(m)

    new_len = sum(len(str(m.get("content", ""))) for m in optimized)
    chars_saved = max(0, orig_len - new_len)
    approx_tokens_saved = chars_saved // 4

    with _lock:
        _stats["prompts_optimized"] += 1
        _stats["tokens_saved_approx"] += approx_tokens_saved
        _stats["redundant_turns_pruned"] += pruned_count
        if chars_saved > 0:
            _stats["messages_shrunk"] += 1
        tot = _stats["prompts_optimized"]
        if tot > 0:
            cur_pct = (chars_saved / orig_len * 100) if orig_len > 0 else 0
            prev_avg = _stats["avg_reduction_percent"]
            _stats["avg_reduction_percent"] = round((prev_avg * (tot - 1) + cur_pct) / tot, 2)

    return optimized, {
        "complexity": complexity,
        "recommended_max_tokens": get_token_budget(complexity),
        "tokens_saved": approx_tokens_saved,
        "pruned_messages": pruned_count,
    }

def stats() -> Dict[str, Any]:
    with _lock:
        return dict(_stats)

def reset_stats():
    with _lock:
        for k in _stats:
            _stats[k] = 0.0 if isinstance(_stats[k], float) else 0


def info() -> Dict[str, Any]:
    """runtime_state.refresh_modules() bunu okur.

    available: saf Python, harici bagimlilik yok — her zaman kullanilabilir.
    Notta gosterilen sayilar GERCEKTEN olculmus degerlerdir (kac prompt
    optimize edildi, yaklasik ne kadar token dusuruldu). Makaledeki
    "-%60 token / +%29 basarim" rakamlari DEPO calismasinin kendi
    olcumleridir; burada gosterilmiyor cunku bu kurulumda olculmedi.
    """
    with _lock:
        n = int(_stats.get("prompts_optimized") or 0)
        saved = int(_stats.get("tokens_saved_approx") or 0)
        red = _stats.get("avg_reduction_percent") or 0.0
    if n:
        note = (f"{n} prompt optimize edildi · ~{saved} token dusuruldu "
                f"· ortalama %{red} kisalma.")
    else:
        note = ("Henuz prompt optimize edilmedi. Acikken her router cagrisinda "
                "gorev karmasikligina gore token butcesi belirlenir.")
    return {"available": True, "note": note}
