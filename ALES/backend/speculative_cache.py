"""
speculative_cache.py — SpecCache: Spekülatif önbellekleme ve KV önbellek yeniden kullanımı.

2025-2026 Durumu:
  1. SpecCache: Görev akışında bir sonraki muhtemel adımları tahmin edip spekülatif olarak
     ön-çekme (predictive prefetch) yapar; web ve masaüstü ortamlarındaki G/Ç gecikmesini sıfıra indirir.
  2. RelayCaching: Ajanlar ve oturumlar arasında paylaşılan prompt/KV önbellek simülasyonu.
     Ortak sistem promptları ve geçmiş turlardaki sabit önekleri (prefix) eşleştirerek
     token ön-doldurma (prefill) yükünü minimize eder.
  3. Çok-kategorili TTL yönetimi: Ekran görüntüleri, OCR koordinatları, DOM durumları
     ve araç çıktıları için dinamik geçerlilik süreleri.
"""
import hashlib
import re
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

try:
    from config_manager import get_appdata_dir
    _CACHE_DIR = get_appdata_dir() / "speccache"
except Exception:
    import pathlib
    _CACHE_DIR = pathlib.Path("./speccache")

# ─── AYARLAR ─────────────────────────────────────────────────────────────
MAX_CACHE_ENTRIES = 512
MAX_KV_ENTRIES = 128
DEFAULT_TTL_S = 30.0

CATEGORY_TTL_S = {
    "screenshot": 2.0,      # Ekran çok hızlı değişebilir
    "dom_state": 5.0,       # Tarayıcı DOM ağacı
    "ocr_tokens": 4.0,      # Ekrandaki metin koordinatları
    "file_meta": 15.0,      # Dosya listeleri ve meta veriler
    "system_info": 10.0,    # CPU / RAM durumu
    "prediction": 8.0,      # Spekülatif tahmin edilmiş sonuçlar
    "web_page": 20.0,       # Çekilmiş web sayfası içerikleri
}

_lock = threading.RLock()
_cache_store: OrderedDict = OrderedDict()      # key -> {val, exp, cat, hits}
_kv_store: OrderedDict = OrderedDict()         # prefix_hash -> {prefix, metadata, hits, created}
_speculative_predictions: Dict[str, List[str]] = {} # action -> [predicted_next_actions]

_stats = {
    "hits": 0,
    "misses": 0,
    "speculative_hits": 0,
    "speculative_prefetches": 0,
    "kv_prefix_hits": 0,
    "kv_tokens_saved": 0,
    "evictions": 0,
}

# ─── YARDIMCI İŞLEVLER ───────────────────────────────────────────────────
def _make_key(key: str, category: str = "general") -> str:
    norm = str(key).strip().lower()
    h = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:24]
    return f"{category}:{h}"

def _evict_if_needed():
    now = time.time()
    # 1. Süresi dolanları temizle
    expired_keys = [k for k, v in _cache_store.items() if v["exp"] <= now]
    for k in expired_keys:
        _cache_store.pop(k, None)

    # 2. Boyut aşıldıysa en eskiyi çıkar (LRU)
    while len(_cache_store) > MAX_CACHE_ENTRIES:
        _cache_store.popitem(last=False)
        _stats["evictions"] += 1

    while len(_kv_store) > MAX_KV_ENTRIES:
        _kv_store.popitem(last=False)

# ─── SPECCACHE TEMEL İŞLEMLERİ ──────────────────────────────────────────
def get(key: str, category: str = "general") -> Optional[Any]:
    """Önbellekten değer getirir; süresi dolmuşsa None döner."""
    ckey = _make_key(key, category)
    with _lock:
        item = _cache_store.get(ckey)
        now = time.time()
        if not item:
            _stats["misses"] += 1
            return None
        if item["exp"] <= now:
            _cache_store.pop(ckey, None)
            _stats["misses"] += 1
            return None
        
        # LRU tazeleme
        _cache_store.move_to_end(ckey)
        item["hits"] += 1
        _stats["hits"] += 1
        if item.get("is_speculative"):
            _stats["speculative_hits"] += 1
        return item["val"]

def put(key: str, value: Any, category: str = "general", ttl: Optional[float] = None, is_speculative: bool = False) -> str:
    """Önbelleğe değer yazar."""
    ckey = _make_key(key, category)
    t = ttl if ttl is not None else CATEGORY_TTL_S.get(category, DEFAULT_TTL_S)
    now = time.time()
    with _lock:
        _evict_if_needed()
        _cache_store[ckey] = {
            "val": value,
            "exp": now + t,
            "cat": category,
            "hits": 0,
            "created": now,
            "is_speculative": is_speculative,
            "raw_key": str(key)[:120],
        }
        _cache_store.move_to_end(ckey)
        if is_speculative:
            _stats["speculative_prefetches"] += 1
        return ckey

def invalidate(pattern: str = "") -> int:
    """Belirli bir desene uyan anahtarları veya tümünü temizler."""
    with _lock:
        if not pattern:
            n = len(_cache_store)
            _cache_store.clear()
            return n
        rx = re.compile(pattern, re.I)
        matched = [k for k, v in _cache_store.items() if rx.search(k) or rx.search(v.get("raw_key", ""))]
        for k in matched:
            _cache_store.pop(k, None)
        return len(matched)

# ─── RELAYCACHING: KV ÖNEK ÖNBELLEĞİ ──────────────────────────────────────
def get_kv_prefix(prompt: str) -> Optional[Dict[str, Any]]:
    """
    Prompt içindeki sabit sistem önekini eşleştirir (RelayCaching).
    Benzer bağlam pencerelerinde token ön-doldurma tasarrufunu simüle eder.
    """
    if not prompt or len(prompt) < 60:
        return None
    # İlk 500 karakteri önek olarak baz al
    prefix = prompt[:500]
    p_hash = hashlib.sha256(prefix.encode("utf-8")).hexdigest()[:20]
    
    with _lock:
        item = _kv_store.get(p_hash)
        if item:
            _kv_store.move_to_end(p_hash)
            item["hits"] += 1
            _stats["kv_prefix_hits"] += 1
            approx_tokens = len(prefix) // 4
            _stats["kv_tokens_saved"] += approx_tokens
            return {
                "matched": True,
                "prefix_hash": p_hash,
                "tokens_saved": approx_tokens,
                "hits": item["hits"],
            }
        return None

def cache_kv_prefix(prompt: str, metadata: Optional[Dict[str, Any]] = None):
    """Sık kullanılan bir prompt önekini KV önbelleğine ekler."""
    if not prompt or len(prompt) < 60:
        return
    prefix = prompt[:500]
    p_hash = hashlib.sha256(prefix.encode("utf-8")).hexdigest()[:20]
    with _lock:
        _evict_if_needed()
        _kv_store[p_hash] = {
            "prefix": prefix[:120],
            "metadata": metadata or {},
            "hits": 0,
            "created": time.time(),
        }
        _kv_store.move_to_end(p_hash)

# ─── SPEKÜLATİF ÖN-GETİRME (Speculative Prefetch) ─────────────────────────
def register_transition(prev_action: str, next_action: str):
    """İki işlem arasındaki geçiş ilişkisini öğrenir."""
    p = prev_action.strip().lower()
    n = next_action.strip().lower()
    if not p or not n or p == n:
        return
    with _lock:
        candidates = _speculative_predictions.setdefault(p, [])
        if n not in candidates:
            candidates.append(n)
            if len(candidates) > 5:
                candidates.pop(0)

def predict_next_steps(current_action: str) -> List[str]:
    """Mevcut eylemden sonra muhtemel sonraki adımları tahmin eder."""
    a = current_action.strip().lower()
    static_map = {
        "click": ["screenshot", "dom_state"],
        "type": ["press_enter", "screenshot"],
        "browse": ["dom_state", "ocr_tokens"],
        "open_app": ["focus_window", "screenshot"],
        "search": ["read_file", "extract_info"],
    }
    with _lock:
        learned = _speculative_predictions.get(a, [])
        statics = static_map.get(a, [])
        combined = list(dict.fromkeys(learned + statics))
        return combined[:3]

# ─── DURUM VE İSTATİSTİKLER ──────────────────────────────────────────────
def stats() -> Dict[str, Any]:
    with _lock:
        total = _stats["hits"] + _stats["misses"]
        hit_rate = round(_stats["hits"] / total, 4) if total > 0 else 0.0
        return {
            "entries": len(_cache_store),
            "max_entries": MAX_CACHE_ENTRIES,
            "kv_entries": len(_kv_store),
            "max_kv_entries": MAX_KV_ENTRIES,
            "hits": _stats["hits"],
            "misses": _stats["misses"],
            "hit_rate": hit_rate,
            "speculative_hits": _stats["speculative_hits"],
            "speculative_prefetches": _stats["speculative_prefetches"],
            "kv_prefix_hits": _stats["kv_prefix_hits"],
            "kv_tokens_saved": _stats["kv_tokens_saved"],
            "evictions": _stats["evictions"],
        }

def clear() -> Dict[str, Any]:
    with _lock:
        c_count = len(_cache_store)
        k_count = len(_kv_store)
        _cache_store.clear()
        _kv_store.clear()
        return {"ok": True, "cleared_cache": c_count, "cleared_kv": k_count}


def info() -> Dict[str, Any]:
    """runtime_state.refresh_modules() bunu okur.

    available: bellek-ici sozluk, harici bagimlilik yok.

    DURUSTLUK: "KV cache reuse" burada SUNUCU tarafinda KV tensorlerini
    yeniden kullanmak DEGILDIR — ucretsiz barindirilan API'ler boyle bir
    kanca sunmuyor. Yapilan is, ayni sistem-prompt onekini imzalayip
    tekrarini olcmek ve tekrar eden istekleri onbellekten karsilamak.
    Bu yuzden notta gosterilen tek sey gercekten olculen isabet oranidir.
    """
    with _lock:
        total = _stats["hits"] + _stats["misses"]
        hit = round(_stats["hits"] / total * 100, 1) if total else 0.0
        entries = len(_cache_store)
        kv = len(_kv_store)
        spec = _stats.get("speculative_hits", 0)
    if total:
        note = (f"{entries} kayit · isabet %{hit} ({_stats['hits']}/{total}) "
                f"· {spec} spekulatif isabet · {kv} onek imzasi.")
    else:
        note = (f"Henuz sorgulanmadi ({entries} kayit, {kv} onek imzasi). "
                "Acikken tekrar eden istekler LLM'e hic gitmez.")
    return {"available": True, "note": note}
