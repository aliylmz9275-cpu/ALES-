"""
semantic_cache.py — ALES SQLite Tabanlı Anlamsal Vektör Önbelleği (Faz 1, Task #3).

Yüksek Performanslı & Sıfır Bağımlılık:
  - SQLite (WAL modu) ile yerel, kalıcı ve eşzamanlı veri depolama.
  - Kelime + Karakter 3-Gram frekans vektörleri (Counter) üzerinden kosinüs benzerliği.
  - Benzerlik >= 0.85 (%85) olduğunda ANINDA önbellekten (Zero-LLM) döner.
  - Eylem ve zamana duyarlı komutlar (aç, tıkla, sil, dolar kuru, hava durumu vb.)
    kesinlikle önbelleğe ALINMAZ ve önbellekten DÖNMEZ (is_cacheable muhafaza kapısı).
"""

import json
import math
import os
import re
import sqlite3
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from config_manager import get_appdata_dir
    _CACHE_DB = get_appdata_dir() / "semantic_cache.sqlite3"
except Exception:
    _CACHE_DB = Path("semantic_cache.sqlite3")

# ─── EYLEM VE ZAMANA DUYARLI KELİMELER ──────────────────────────────
_ACTION_WORDS = {
    "takip", "follow", "begen", "like", "paylas", "share",
    "repost", "yorum", "comment", "gonder", "send", "dm", "mesaj",
    "ac", "kapat", "close", "open", "sil", "delete", "kaldir",
    "remove", "olustur", "create", "yaz", "write", "kaydet", "save",
    "indir", "download", "yukle", "upload", "kur", "install",
    "calistir", "run", "execute", "launch", "baslat",
    "durdur", "stop", "tikla", "click", "tasi", "move",
    "degistir", "change", "guncelle", "update",
    "ekle", "add", "cek", "screenshot", "ekran", "goruntu",
    "otomasyon", "otomatik", "pipeline", "gorev", "feed",
}

_ACTION_PHRASES = [
    "takip et", "follow", "begen", "yorum yap", "dm at", "mesaj at",
    "ekran goruntusu", "dosyayi ac", "uygulamayi ac", "open app",
]

_VOLATILE_WORDS = {
    "fiyat", "fiyati", "fiyatlari", "kur", "kuru", "kurlari", "dolar", "euro",
    "sterlin", "altin", "bitcoin", "btc", "eth", "kripto", "borsa", "hisse",
    "hava", "derece", "haber", "haberler", "gundem", "bugun", "simdi",
    "guncel", "son dakika", "tarih", "saat",
}

_URL_RE = re.compile(r"https?://|www\.", re.I)
_MENTION_RE = re.compile(r"@[A-Za-z0-9._]{2,}")
_PATH_RE = re.compile(r"[A-Za-z]:\\|/[A-Za-z0-9_]+/|\.\w{1,4}\b")

_TR = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "İ": "i", "ö": "o",
                     "ş": "s", "ü": "u", "Ç": "c", "Ğ": "g", "Ö": "o",
                     "Ş": "s", "Ü": "u", "I": "i"})
_PUNCT_RE = re.compile(r"[^\w\s]", re.U)
_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    if not text:
        return ""
    t = text.translate(_TR).casefold()
    t = _PUNCT_RE.sub(" ", t)
    return _WS_RE.sub(" ", t).strip()


def is_cacheable(prompt: str) -> Tuple[bool, str]:
    """(cacheable: bool, reason: str). Muhafazakar: şüpheliyse önbelleğe alma."""
    if not prompt or len(prompt.strip()) < 3:
        return False, "cok kisa"
    raw = prompt.strip()
    low = raw.translate(_TR).casefold()
    if _URL_RE.search(raw):
        return False, "URL iceriyor"
    if _MENTION_RE.search(raw):
        return False, "@kullanici iceriyor"
    if _PATH_RE.search(raw):
        return False, "dosya yolu iceriyor"
    for ph in _ACTION_PHRASES:
        if ph in low:
            return False, f"aksiyon ifadesi: '{ph}'"
    norm = _normalize(prompt)
    toks = set(norm.split())
    hit = toks & _ACTION_WORDS
    if hit:
        return False, f"aksiyon fiili: {sorted(hit)[:3]}"
    vol = toks & _VOLATILE_WORDS
    if vol:
        return False, f"zamana duyarli veri: {sorted(vol)[:3]}"
    if len(norm) > 2000:
        return False, "cok uzun"
    return True, "ok"


def _vectorize(norm: str) -> Counter:
    """Kelime ve 3-gram frekanslarını harmanlayarak anlamsal özellik vektörü üretir."""
    tokens = norm.split()
    counts = Counter(tokens)
    # Karakter trigramları (yazım farklılıkları ve ek toleransı için)
    for tok in tokens:
        if len(tok) >= 3:
            for i in range(len(tok) - 2):
                counts[f"3g_{tok[i:i+3]}"] += 1
    return counts


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[t] * b[t] for t in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


class SemanticCache:
    """
    SQLite tabanlı yüksek hızlı anlamsal vektör önbelleği.
    Benzerlik eşiği >= 0.85 (%85) olduğunda anında sonuç döner.
    """

    def __init__(self, db_path: Optional[Path] = None, max_size: int = 500,
                 ttl_s: float = 7200.0, threshold: float = 0.85):
        self.db_path = db_path or _CACHE_DB
        self.max_size = max_size
        self.ttl_s = ttl_s
        self.threshold = threshold
        self.stats = {"hits": 0, "misses": 0, "stored": 0, "skipped": 0}
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        with self._lock:
            try:
                with self._get_connection() as conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS semantic_cache (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            ns TEXT,
                            norm TEXT,
                            prompt TEXT,
                            answer TEXT,
                            vec_json TEXT,
                            hits INTEGER DEFAULT 0,
                            ts REAL
                        );
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_sc_ns_ts ON semantic_cache(ns, ts);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_sc_norm ON semantic_cache(norm);")
            except Exception as e:
                print(f"[SEMANTIC_CACHE] DB başlatma hatası: {e}")

    def get(self, prompt: str, namespace: str = "") -> Optional[Dict]:
        """
        Kosinüs benzerliği >= 0.85 ise {answer, similarity, matched, age_s} döner, yoksa None.
        """
        ok, _ = is_cacheable(prompt)
        if not ok:
            return None

        norm = _normalize(prompt)
        qv = _vectorize(norm)
        now = time.time()
        min_ts = now - self.ttl_s

        with self._lock:
            try:
                with self._get_connection() as conn:
                    # 1. Tam norm eşleşmesi (Anında 1.0 HIT)
                    row = conn.execute(
                        "SELECT id, prompt, answer, ts, hits FROM semantic_cache WHERE ns = ? AND norm = ? AND ts >= ? LIMIT 1",
                        (namespace, norm, min_ts)
                    ).fetchone()
                    if row:
                        cid, matched_p, ans, c_ts, hits = row
                        conn.execute("UPDATE semantic_cache SET hits = hits + 1 WHERE id = ?", (cid,))
                        self.stats["hits"] += 1
                        return {
                            "answer": ans,
                            "similarity": 1.0,
                            "matched": matched_p,
                            "age_s": round(now - c_ts, 1)
                        }

                    # 2. Vektör Benzerlik Taraması
                    cursor = conn.execute(
                        "SELECT id, prompt, answer, vec_json, ts, hits FROM semantic_cache WHERE ns = ? AND ts >= ? ORDER BY ts DESC LIMIT ?",
                        (namespace, min_ts, self.max_size)
                    )
                    best_match = None
                    best_sim = 0.0

                    for cid, matched_p, ans, vec_json, c_ts, hits in cursor.fetchall():
                        try:
                            stored_vec = Counter(json.loads(vec_json))
                            sim = _cosine(qv, stored_vec)
                            if sim > best_sim:
                                best_sim = sim
                                best_match = (cid, matched_p, ans, c_ts)
                                if best_sim >= 0.98:  # Neredeyse birebir eşleşme
                                    break
                        except Exception:
                            continue

                    if best_match and best_sim >= self.threshold:
                        cid, matched_p, ans, c_ts = best_match
                        conn.execute("UPDATE semantic_cache SET hits = hits + 1 WHERE id = ?", (cid,))
                        self.stats["hits"] += 1
                        return {
                            "answer": ans,
                            "similarity": round(best_sim, 4),
                            "matched": matched_p,
                            "age_s": round(now - c_ts, 1)
                        }

            except Exception as e:
                print(f"[SEMANTIC_CACHE] Sorgu hatası: {e}")

        self.stats["misses"] += 1
        return None

    def put(self, prompt: str, answer: str, namespace: str = "") -> bool:
        """Cache'lenebilirse SQLite'a sakla."""
        ok, _ = is_cacheable(prompt)
        if not ok or not (answer or "").strip():
            self.stats["skipped"] += 1
            return False

        norm = _normalize(prompt)
        qv = _vectorize(norm)
        vec_json = json.dumps(dict(qv), ensure_ascii=False)
        now = time.time()

        with self._lock:
            try:
                with self._get_connection() as conn:
                    # Mevcutsa güncelle
                    existing = conn.execute(
                        "SELECT id FROM semantic_cache WHERE ns = ? AND norm = ?",
                        (namespace, norm)
                    ).fetchone()

                    if existing:
                        conn.execute(
                            "UPDATE semantic_cache SET prompt = ?, answer = ?, vec_json = ?, ts = ? WHERE id = ?",
                            (prompt, answer, vec_json, now, existing[0])
                        )
                    else:
                        conn.execute(
                            "INSERT INTO semantic_cache (ns, norm, prompt, answer, vec_json, hits, ts) VALUES (?, ?, ?, ?, ?, 0, ?)",
                            (namespace, norm, prompt, answer, vec_json, now)
                        )
                        # Boyut sınırını aşarsa eski kayıtları temizle
                        conn.execute("""
                            DELETE FROM semantic_cache WHERE id NOT IN (
                                SELECT id FROM semantic_cache ORDER BY ts DESC LIMIT ?
                            )
                        """, (self.max_size,))

                self.stats["stored"] += 1
                return True
            except Exception as e:
                print(f"[SEMANTIC_CACHE] Kayıt hatası: {e}")
                return False

    def clear(self):
        with self._lock:
            try:
                with self._get_connection() as conn:
                    conn.execute("DELETE FROM semantic_cache;")
            except Exception:
                pass


# ─── SINGLETON & KISAYOLLAR ─────────────────────────────────────────
_default = None


def get_cache() -> SemanticCache:
    global _default
    if _default is None:
        _default = SemanticCache()
    return _default


def lookup(prompt: str, namespace: str = "") -> Optional[Dict]:
    return get_cache().get(prompt, namespace)


def store(prompt: str, answer: str, namespace: str = "") -> bool:
    return get_cache().put(prompt, answer, namespace)
