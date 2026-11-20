"""
semantic_cache.py — ALES hafif anlamsal cache (Faz 1, Task #3; vCache yerine).

Bagimliliksiz (embedding modeli YOK). Yakin-tekrar bilgi sorularini yakalar:
normalize -> token vektoru -> kosinus benzerligi. Esik ustu -> cache HIT,
LLM cagrisi atlanir.

EN ONEMLI KURAL — MUHAFAZAKAR KAPI (is_cacheable):
  Bir istem EYLEM iceriyorsa (takip et, begen, gonder, sil, ac, calistir,
  URL, @kullanici, dosya yolu, ...) cache'e NE YAZILIR NE DE OKUNUR. Boylece
  bir aksiyon komutu ASLA eski bir cevapla kisa devre olmaz. Yanlis-negatif
  (cache'lenebilir seyi atlamak) kabul; yanlis-pozitif (aksiyonu cache'lemek)
  KABUL DEGIL.

Ayrica cache mod'a gore namespace'lenir (task-modu yaniti heavy-moda sizmaz).
"""
import json
import math
import re
import time
from collections import Counter
from pathlib import Path

try:
    from config_manager import get_appdata_dir
    _CACHE_FILE = get_appdata_dir() / "semantic_cache.json"
except Exception:
    _CACHE_FILE = Path("semantic_cache.json")

# ─── EYLEM IMZALARI (bunlardan biri varsa cache'lenmez) ──────────
# Turkce + Ingilizce emir/aksiyon fiilleri ve yan-etki tetikleyicileri.
_ACTION_WORDS = {
    # sosyal medya / otomasyon
    "takip", "follow", "begen", "beğen", "like", "paylas", "paylaş", "share",
    "repost", "yorum", "comment", "gonder", "gönder", "send", "dm", "mesaj",
    # dosya / sistem
    "ac", "aç", "kapat", "close", "open", "sil", "delete", "kaldir", "kaldır",
    "remove", "olustur", "oluştur", "create", "yaz", "write", "kaydet", "save",
    "indir", "download", "yukle", "yükle", "upload", "kur", "install",
    "calistir", "çalıştır", "run", "execute", "launch", "baslat", "başlat",
    "durdur", "stop", "tikla", "tıkla", "click", "tasi", "taşı", "move",
    "degistir", "değiştir", "change", "guncelle", "güncelle", "update",
    "ekle", "add", "cek", "çek", "screenshot", "ekran", "goruntu", "görüntü",
    "otomasyon", "otomatik", "pipeline", "gorev", "görev", "feed",
}
# Tam ifade tetikleyicileri (kelime siniri gerektirmez)
_ACTION_PHRASES = [
    "takip et", "follow", "beğen", "begen", "yorum yap", "dm at", "mesaj at",
    "ekran görüntüsü", "ekran goruntusu", "dosyayı aç", "dosyayi ac",
]

# ZAMANA DUYARLI VERI — cevap saatlerce onbellekte tutulursa BAYATLAR.
# Bunlar da cache DISI (Fast Path'i kacirsa bile eski fiyat/hava dönmesin).
_VOLATILE_WORDS = {
    "fiyat", "fiyati", "fiyatı", "fiyatlari", "fiyatları", "kur", "kuru",
    "kurlari", "kurları", "dolar", "euro", "sterlin", "altin", "altın",
    "bitcoin", "btc", "eth", "kripto", "borsa", "hisse", "hava", "derece",
    "haber", "haberler", "gundem", "gündem", "bugun", "bugün", "simdi",
    "şimdi", "guncel", "güncel", "son", "dakika", "tarih", "saat",
}
_URL_RE = re.compile(r"https?://|www\.", re.I)
_MENTION_RE = re.compile(r"@[A-Za-z0-9._]{2,}")
_PATH_RE = re.compile(r"[A-Za-z]:\\|/[A-Za-z0-9_]+/|\.\w{1,4}\b")

# Turkce -> ascii (yalniz eslesme icin; goruntulenen metin degismez)
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


def is_cacheable(prompt: str) -> tuple:
    """(cacheable: bool, reason: str). Muhafazakar: supheliyse cache'leme."""
    if not prompt or len(prompt.strip()) < 3:
        return False, "cok kisa"
    raw = prompt.strip()
    low = raw.translate(_TR).casefold()
    if _URL_RE.search(raw):
        return False, "URL iceriyor (aksiyon olabilir)"
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
        return False, "cok uzun (muhtemelen kod/baglam)"
    return True, "ok"


def _vec(norm: str) -> Counter:
    return Counter(norm.split())


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
    """Kucuk, bagimliliksiz anlamsal cache. Kosinus benzerligi >= threshold
    ise HIT. TTL + LRU tahliye. AppData'ya kalici yazar."""

    def __init__(self, max_size: int = 256, ttl_s: float = 3600.0,
                 threshold: float = 0.80, persist: bool = True):
        self.max_size = max_size
        self.ttl_s = ttl_s
        self.threshold = threshold
        self.persist = persist
        self._entries = []  # {ns, norm, vec(Counter), prompt, answer, ts, hits}
        self.stats = {"hits": 0, "misses": 0, "stored": 0, "skipped": 0}
        if persist:
            self._load()

    # ── kalicilik ──
    def _load(self):
        if not _CACHE_FILE.exists():
            return
        try:
            data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            now = time.time()
            for e in data.get("entries", []):
                if now - e.get("ts", 0) <= self.ttl_s:
                    e["vec"] = Counter((e.get("norm") or "").split())
                    self._entries.append(e)
        except Exception:
            pass

    def _save(self):
        if not self.persist:
            return
        try:
            out = {"entries": [{k: v for k, v in e.items() if k != "vec"}
                               for e in self._entries]}
            _CACHE_FILE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _evict(self):
        now = time.time()
        self._entries = [e for e in self._entries if now - e["ts"] <= self.ttl_s]
        if len(self._entries) > self.max_size:
            # en az kullanilan + en eski once gider
            self._entries.sort(key=lambda e: (e.get("hits", 0), e["ts"]))
            self._entries = self._entries[-self.max_size:]

    # ── ana API ──
    def get(self, prompt: str, namespace: str = "") -> dict:
        """Benzer bir istem varsa {answer, similarity, matched, age_s} doner,
        yoksa None. Aksiyon istemleri icin (is_cacheable=False) her zaman None."""
        ok, _ = is_cacheable(prompt)
        if not ok:
            return None
        norm = _normalize(prompt)
        qv = _vec(norm)
        now = time.time()
        best, best_sim = None, 0.0
        for e in self._entries:
            if e.get("ns") != namespace:
                continue
            if now - e["ts"] > self.ttl_s:
                continue
            if e.get("norm") == norm:
                best, best_sim = e, 1.0
                break
            sim = _cosine(qv, e["vec"])
            if sim > best_sim:
                best, best_sim = e, sim
        if best and best_sim >= self.threshold:
            best["hits"] = best.get("hits", 0) + 1
            self.stats["hits"] += 1
            return {"answer": best["answer"], "similarity": round(best_sim, 4),
                    "matched": best["prompt"], "age_s": round(now - best["ts"], 1)}
        self.stats["misses"] += 1
        return None

    def put(self, prompt: str, answer: str, namespace: str = "") -> bool:
        """Cache'lenebilirse sakla. Aksiyon istemleri saklanmaz (skipped)."""
        ok, _ = is_cacheable(prompt)
        if not ok or not (answer or "").strip():
            self.stats["skipped"] += 1
            return False
        norm = _normalize(prompt)
        for e in self._entries:  # ayni normalize -> guncelle
            if e.get("ns") == namespace and e.get("norm") == norm:
                e.update(answer=answer, prompt=prompt, ts=time.time())
                self._save()
                return True
        self._entries.append({"ns": namespace, "norm": norm, "vec": _vec(norm),
                              "prompt": prompt, "answer": answer,
                              "ts": time.time(), "hits": 0})
        self.stats["stored"] += 1
        self._evict()
        self._save()
        return True

    def clear(self):
        self._entries = []
        self._save()


# ─── MODUL SINGLETON + KISAYOLLAR ────────────────────────────────
_default = None


def get_cache() -> SemanticCache:
    global _default
    if _default is None:
        _default = SemanticCache()
    return _default


def lookup(prompt: str, namespace: str = "") -> dict:
    return get_cache().get(prompt, namespace)


def store(prompt: str, answer: str, namespace: str = "") -> bool:
    return get_cache().put(prompt, answer, namespace)
