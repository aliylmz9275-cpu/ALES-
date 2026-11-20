"""
retry_util.py — ALES dayanikli islem yardimcilari (Faz 3 item 10).

Gercek karsilik: hata tolere eden, geri-alimli (backoff) yeniden deneme +
sayfa yukleme zaman asimi ve yeniden yukleme destegi. Hicbir saglayiciya
bagimli degildir; ALES'in hem WebSocket islemleri hem Playwright/tarayici
gorevleri icin kullanilabilir.

Fikirler:
  * `retry()` — senkron ya da asenkron islevi N kez dener; hatalar arasi
    ussel geri-alim + istege bagli sarsinti (jitter). En son hatayi firlatir.
  * `retry_playwright()` — tarayici eylemleri icin ozel: belirli hatalarda
    sayfayi YENIDEN YUKLER ve yeniden dener; "10 saniyede yuklenmediyse
    yenile ve tekrar dene" mantiginin genel hali.
  * `only_if_*` filtreleri — yalnizca yeniden denemenin ANLAMLI oldugu
    hatalari ayirt eder (ornegin "ElementNotFound" evet, "invalid selector"
    hayir — ayni hatayi tekrarlamak anlamsiz).
"""

import asyncio
import logging
import random
import time

log = logging.getLogger("ales.retry")

# Hangi hata tipi/eslesme yeniden denenmeli (yoksa "kalici hata" sayilir)
RETRYABLE_MARKERS = (
    "timeout", "timed out", "temporarily", "temporar", "unavailable",
    "connection", "network", "socket", "http 429", "429", "502", "503", "504",
    "gateway", "econnreset", "econnrefused", "elementnotfound",
    "no such element", "stale", "crash", "interrupted", "retry",
    "resource temporarily", "overload", "too many", "rate limit",
)


def is_retryable(exc: BaseException) -> bool:
    """Hata yeniden denenebilir mi? Mesajdaki isaretleyicilere bakar;
    bilinmeyen hatalar guvenli tarafta kalir (yeniden denenmez)."""
    msg = f"{type(exc).__name__}: {exc}".lower()
    return any(m in msg for m in RETRYABLE_MARKERS)


def sleep_before(retries_so_far: int, base_s: float, max_s: float, jitter: bool = True) -> float:
    """Ussel geri-alim: 2^deneme * base, max ile sinirli, %30 sarsintili."""
    delay = min(max_s, base_s * (2 ** max(0, retries_so_far - 1)))
    if jitter:
        delay *= random.uniform(0.7, 1.3)
    return round(delay, 3)


# ═════════════════════════════════════════════════════════════════
# ISLEM SAYAClARI — /retry/stats ile arayuze acilir
# ═════════════════════════════════════════════════════════════════
# NEDEN: bu modul saf bir yardimci kutuphaneydi; calisip calismadigi, ne
# kadar yeniden denedigi ve nerede pes ettigi HICBIR YERDEN gorunmuyordu.
# Sayaclar surec icinde tutulur (diske YAZILMAZ) ve `label` ile cagri
# yerine gore ayrisir. Hata METNI tutulmaz — yalnizca hata TIPI; boylece
# bir istisna mesajinda gecen sir/token sayaclara sizmaz.
#
# Kilit YOK: bunlar teshis sayaci; GIL altinda kacirilan bir artirim
# hicbir kararı etkilemez ve her cagriya kilit maliyeti bindirmek yanlis
# olur.
_MAX_LABELS = 50          # etiket sozlugu sinirsiz buyumesin

_STATS = {
    "calls": 0,           # retry/aretry/retry_playwright cagrisi
    "retries": 0,         # yapilan yeniden deneme sayisi
    "recovered": 0,       # en az bir yeniden denemeden SONRA basarili olan
    "failed": 0,          # denemeler tukendi ya da kalici hata
    "slept_s": 0.0,       # geri-alimda beklenen toplam sure
    "last": None,         # {label, attempt, error_type, delay_s}
    "by_label": {},       # etiket -> {calls, retries, recovered, failed}
}


def _slot(label) -> dict:
    key = str(label or "-")[:40]
    s = _STATS["by_label"].get(key)
    if s is None:
        if len(_STATS["by_label"]) >= _MAX_LABELS:
            key = "(diger)"
            s = _STATS["by_label"].get(key)
            if s is not None:
                return s
        s = {"calls": 0, "retries": 0, "recovered": 0, "failed": 0}
        _STATS["by_label"][key] = s
    return s


def _bump(label, field: str, n: int = 1):
    _STATS[field] = _STATS.get(field, 0) + n
    slot = _slot(label)
    slot[field] = slot.get(field, 0) + n


def _record_retry(label, attempt: int, exc: BaseException, delay: float):
    _bump(label, "retries")
    _STATS["slept_s"] = round(_STATS["slept_s"] + float(delay or 0), 3)
    _STATS["last"] = {"label": str(label or "-")[:40], "attempt": attempt,
                      "error_type": type(exc).__name__, "delay_s": delay}


def stats() -> dict:
    """UI/teshis anlik goruntusu. by_label en cok yeniden denenen ustte."""
    by = sorted(({"label": k, **v} for k, v in _STATS["by_label"].items()),
                key=lambda d: (d["retries"], d["calls"]), reverse=True)
    return {
        "calls": _STATS["calls"], "retries": _STATS["retries"],
        "recovered": _STATS["recovered"], "failed": _STATS["failed"],
        "slept_s": _STATS["slept_s"], "last": _STATS["last"],
        "by_label": by,
        "markers": len(RETRYABLE_MARKERS),
    }


def reset_stats():
    _STATS.update({"calls": 0, "retries": 0, "recovered": 0, "failed": 0,
                   "slept_s": 0.0, "last": None})
    _STATS["by_label"] = {}


def retry(fn, attempts: int = 3, base_s: float = 1.0, max_s: float = 15.0,
          retry_on=None, on_retry=None, jitter: bool = True, label: str = None):
    """Senkron islevi yeniden dener. retry_on: (hatayla->bool) islevi;
    yoksa is_retryable kullanilir. on_retry(attempt, exc, delay) geri cagirimi
    istege bagli (loglama/UI icin). label: /retry/stats'ta gorunen ad."""
    if attempts < 1:
        raise ValueError("attempts >= 1 olmali")
    _bump(label, "calls")
    last = None
    for attempt in range(1, attempts + 1):
        try:
            out = fn()
            if attempt > 1:
                _bump(label, "recovered")
            return out
        except BaseException as e:
            last = e
            should = retry_on(e) if retry_on else is_retryable(e)
            if attempt >= attempts or not should:
                break
            delay = sleep_before(attempt, base_s, max_s, jitter)
            _record_retry(label, attempt, e, delay)
            if on_retry:
                try:
                    on_retry(attempt, e, delay)
                except Exception:
                    pass
            log.warning("deneme %d/%d basarisiz (%s); %.1fs sonra yeniden",
                        attempt, attempts, type(e).__name__, delay)
            time.sleep(delay)
    _bump(label, "failed")
    if last is not None:
        raise last
    return None  # teorik olarak ulasilmaz


async def aretry(fn, attempts: int = 3, base_s: float = 1.0, max_s: float = 15.0,
                 retry_on=None, on_retry=None, jitter: bool = True,
                 label: str = None):
    """retry()'nin asenkron kardesi."""
    if attempts < 1:
        raise ValueError("attempts >= 1 olmali")
    _bump(label, "calls")
    last = None
    for attempt in range(1, attempts + 1):
        try:
            out = await fn()
            if attempt > 1:
                _bump(label, "recovered")
            return out
        except BaseException as e:
            last = e
            should = retry_on(e) if retry_on else is_retryable(e)
            if attempt >= attempts or not should:
                break
            delay = sleep_before(attempt, base_s, max_s, jitter)
            _record_retry(label, attempt, e, delay)
            if on_retry:
                try:
                    on_retry(attempt, e, delay)
                except Exception:
                    pass
            log.warning("deneme %d/%d basarisiz (%s); %.1fs sonra yeniden",
                        attempt, attempts, type(e).__name__, delay)
            await asyncio.sleep(delay)
    _bump(label, "failed")
    if last is not None:
        raise last
    return None


async def retry_playwright(page, action, attempts: int = 3,
                           timeout_ms: int = 10000, reload_on_timeout: bool = True,
                           on_retry=None, label: str = "playwright"):
    """Playwright tarayici eylemi icin dayanikli sarmalayici.

    page       — Playwright Page nesnesi (reload icin)
    action     — async fn(page) -> sonuc
    reload_on_timeout — TimeoutError'da sayfayi yeniden yukleyip yeniden dene

    Basarisiz olan deneme sayisi ve son hata dondurulur:
    (sonuc, deneme_sayisi, son_hata). Son hata yoksa None.
    """
    attempts = max(1, attempts)
    _bump(label, "calls")
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            result = await asyncio.wait_for(action(page), timeout=timeout_ms / 1000.0)
            if attempt > 1:
                _bump(label, "recovered")
            return result, attempt, None
        except (asyncio.TimeoutError, TimeoutError) as e:
            last_exc = e
            if on_retry:
                try:
                    on_retry(attempt, e, 0.0)
                except Exception:
                    pass
            if attempt < attempts and reload_on_timeout:
                _record_retry(label, attempt, e, 0.0)
                log.warning("zaman asimi (deneme %d) — sayfa yeniden yukleniyor", attempt)
                try:
                    await page.reload(wait_until="domcontentloaded")
                except Exception:
                    pass
            elif attempt >= attempts:
                break
        except Exception as e:
            last_exc = e
            if on_retry:
                try:
                    on_retry(attempt, e, 0.0)
                except Exception:
                    pass
            if attempt >= attempts:
                break
            # zaman asimi degilse: bekle ve yeniden dene (yalnizca yeniden
            # denenebilir hatalarda)
            if not is_retryable(e):
                break
            delay = sleep_before(attempt, 1.0, 8.0)
            _record_retry(label, attempt, e, delay)
            await asyncio.sleep(delay)
    _bump(label, "failed")
    return None, attempts, last_exc
