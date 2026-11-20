"""
batch_inference.py — CONCUR-tarzı Toplu Çıkarım (Concurrent Batch Inference).

NE YAPAR:
  1. Yan etkisiz / salt-okunur istekleri kısa bir mikro-pencerede
     (BATCH_WINDOW_MS) toplar ve TEK sevkiyatta, sınırlı eş-zamanlılıkla
     gönderir. ALES'te bunu besleyen yer main.py:_codeact_ask_llm — yani
     öz-yansıma (Reflexion), JIT derleme ve CodeAct planı gibi arka plan
     LLM işleri.
  2. Güvenlik Kapısı: Yıkıcı veya yan-etkili işlemler (dosya yazma, fare
     tıklaması, kod çalıştırma) ASLA kuyruğa alınmaz; anında doğrudan
     çalıştırılır (bkz. _is_safe_for_batch).

DÜRÜSTLÜK NOTU (2026-09-05): bu dosyada eskiden "4 kata varan verim
  artışı sağlar" yazıyordu. O rakam CONCUR makalesinin SUNUCU TARAFI
  sürekli-toplama (continuous batching) ölçümüdür; ALES ücretsiz
  barındırılan API'leri kullanır ve bu uçların hiçbiri toplu-istek ucu
  sunmaz. Dolayısıyla burada 4x YOKTUR ve ölçülmemiştir. Gerçek kazanç
  daha mütevazı: eş zamanlı tetiklenen arka plan işleri tek gather'da
  toplanır (N ayrı akış açılmaz), eş-zamanlılık sınırlanır ve tek bir
  istatistik altında görünür. Panelde 4x gibi bir sayı gösterilmemeli;
  stats() yalnızca gerçekten ölçülen batch sayısı/ortalamasını verir.
"""
import asyncio
import hashlib
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

MAX_BATCH_SIZE = 8
MIN_BATCH_SIZE = 3
BATCH_WINDOW_MS = 150  # 150ms bekleme penceresi

# NOT: burada eskiden import aninda `asyncio.get_event_loop()` cagiran bir
# modul-duzeyi kilit vardi. Kullanilmiyordu (motorun kendi self._lock'u var)
# ve Python 3.12+'da calisan dongu yokken get_event_loop() once uyari, sonra
# hata uretir — yani ALES'i ACILISTA dusurebilecek bir mayindi. Kaldirildi.

class BatchInferenceEngine:
    def __init__(self, batch_size: int = MAX_BATCH_SIZE, window_ms: int = BATCH_WINDOW_MS):
        self.batch_size = batch_size
        self.window_ms = window_ms
        self._queue: List[Tuple[Dict[str, Any], asyncio.Future]] = []
        self._timer_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._stats = {
            "total_requests": 0,
            "batches_executed": 0,
            "items_batched": 0,
            "direct_executions": 0,
            "avg_batch_size": 0.0,
        }

    def _is_safe_for_batch(self, req: Dict[str, Any]) -> bool:
        """Yan etkisiz, salt-okunur istek kontrolü."""
        task_type = str(req.get("type", "")).lower()
        prompt = str(req.get("prompt", "")).lower()
        unsafe_keywords = ["write", "delete", "remove", "click", "exec", "run", "shutdown", "kill"]
        if any(k in task_type for k in unsafe_keywords):
            return False
        if any(k in prompt[:60] for k in ["dosya sil", "tıkla", "yaz", "kapat", "çalıştır"]):
            return False
        return True

    async def submit(self, req: Dict[str, Any], executor: Optional[Callable] = None) -> Any:
        """
        İsteği toplu çıkarım kuyruğuna gönderir.
        Eğer istek yan-etkili ise doğrudan executor ile çalıştırır.

        DÖNÜŞ SÖZLEŞMESİ: her iki yolda da TEK istek için TEK sonuç döner.
        (Doğrudan yol eskiden executor([req])'in listesini ham döndürüyordu;
        toplu yol ise tek öğe veriyordu. Çağıran taraf aynı işten bazen str
        bazen [str] alıyordu — burada listeyi açıyoruz.)
        """
        self._stats["total_requests"] += 1
        if not self._is_safe_for_batch(req) or executor is None:
            self._stats["direct_executions"] += 1
            if executor:
                out = await executor([req])
                if isinstance(out, list):
                    return out[0] if out else None
                return out
            return None

        loop = asyncio.get_running_loop()
        future = loop.create_future()

        async with self._lock:
            self._queue.append((req, future))
            if len(self._queue) >= self.batch_size:
                if self._timer_task and not self._timer_task.done():
                    self._timer_task.cancel()
                    self._timer_task = None
                asyncio.create_task(self._flush_locked(executor))
            elif self._timer_task is None or self._timer_task.done():
                self._timer_task = asyncio.create_task(self._wait_and_flush(executor))

        return await future

    async def _wait_and_flush(self, executor: Callable):
        try:
            await asyncio.sleep(self.window_ms / 1000.0)
            async with self._lock:
                await self._flush_locked(executor)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[BATCH] Hata: {e}")

    async def _flush_locked(self, executor: Callable):
        if not self._queue:
            return
        items_to_process = list(self._queue)
        self._queue.clear()
        self._timer_task = None

        batch_count = len(items_to_process)
        self._stats["batches_executed"] += 1
        self._stats["items_batched"] += batch_count
        tot_b = self._stats["batches_executed"]
        self._stats["avg_batch_size"] = round(self._stats["items_batched"] / tot_b, 2)

        reqs = [it[0] for it in items_to_process]
        futures = [it[1] for it in items_to_process]

        try:
            results = await executor(reqs)
            if isinstance(results, list) and len(results) == len(futures):
                for fut, res in zip(futures, results):
                    if not fut.done():
                        fut.set_result(res)
            else:
                for fut in futures:
                    if not fut.done():
                        fut.set_result(results)
        except Exception as e:
            for fut in futures:
                if not fut.done():
                    fut.set_exception(e)

    def stats(self) -> Dict[str, Any]:
        return dict(self._stats)

# Global tekil örnek
engine = BatchInferenceEngine()


def stats() -> Dict[str, Any]:
    """Modul duzeyi kisayol: /system/status ve REST uclari bunu okur."""
    s = dict(engine.stats())
    s["batch_size"] = engine.batch_size
    s["window_ms"] = engine.window_ms
    s["queued_now"] = len(engine._queue)
    return s


def info() -> Dict[str, Any]:
    """runtime_state.refresh_modules() bunu okur.

    available: motor her zaman kullanilabilir (saf asyncio, harici bagimlilik
    yok). Kapatildiginda cagrilar dogrudan gonderilir — yani bu anahtarin
    kapali olmasi bir YETENEK kaybi degil, sadece toplama kapali demektir.
    """
    s = engine.stats()
    b = int(s.get("batches_executed") or 0)
    if b:
        note = (f"{b} toplu sevkiyat · ortalama {s.get('avg_batch_size')} istek/parti "
                f"· {s.get('direct_executions')} dogrudan (yan etkili).")
    else:
        note = (f"Henuz toplu sevkiyat olmadi ({engine.window_ms}ms pencere, "
                f"en fazla {engine.batch_size} istek). Kapaliyken cagrilar dogrudan gider.")
    return {"available": True, "note": note}
