"""
batch_queue.py — ALES toplu istek (batching) sistemi (Faz 3 / Priority 3, item 7).

Amac: "her tiklama icin bir API cagrisi" yerine, kisa bir pencerede biriken
5-10 eylemi TEK cagrida gondermek. Bu hem maliyeti hem gecikmeyi dusurur
(ozellikle Performance modda, bulut API'lerine gidilirken).

Nasil calisir:
  * add(item) ile eylemler kuyruga girer.
  * Kuyruk MAX_BATCH'e ulasinca YA DA MAX_WAIT_S dolunca "flush" olur.
  * flush aninda kayitli handler TEK seferde tum listeyi alir; her cagirana
    kendi sonucu (asyncio.Future ile) doner.

Kritik guvenlik notu: burada SADECE okuma/karar amacli, YAN ETKISIZ
istekler toplanmalidir. Onay kapisi olan (CodeAct, dosya silme, tiklama
gibi) yikici eylemler TOPLANMAZ — onlarin kapisi ve zaman asimi aynen
korunur (Faz-1 "model-only unrestricted" karari). is_batchable() bunu
zorunlu kilar.
"""

import asyncio
import time

MAX_BATCH = 10          # istenen 5-10 araligi
MIN_BATCH = 5           # bu sayiya ulasinca beklemeden gonder
MAX_WAIT_S = 0.35       # en fazla bu kadar bekle (kullanici gecikme hissetmesin)

# Toplanmasi YASAK olan eylemler — yikici/onay gerektiren her sey.
_NEVER_BATCH = {
    "run_python", "run_code", "codeact", "execute_code",
    "delete_file", "remove_file", "write_file", "move_file",
    "click", "type_text", "press_key", "mouse_move", "drag",
    "shutdown", "restart", "kill_process", "run_command", "shell",
}


def is_batchable(action: str) -> bool:
    """Yalnizca yan etkisiz/okuma amacli eylemler toplanabilir."""
    a = (action or "").strip().lower()
    if not a:
        return False
    if a in _NEVER_BATCH:
        return False
    # temkinli davran: silme/yazma/calistirma ima eden her sey disarida
    for bad in ("delete", "remove", "write", "exec", "run_", "kill", "install", "uninstall"):
        if bad in a:
            return False
    return True


class BatchQueue:
    """Zaman/sayi pencereli toplu isleyici."""

    def __init__(self, handler=None, max_batch: int = MAX_BATCH,
                 min_batch: int = MIN_BATCH, max_wait_s: float = MAX_WAIT_S):
        self.handler = handler          # async fn(list[item]) -> list[result]
        self.max_batch = max_batch
        self.min_batch = min_batch
        self.max_wait_s = max_wait_s
        self._pending = []              # [(item, future)]
        self._timer = None
        self._lock = asyncio.Lock()
        self.stats = {"batches": 0, "items": 0, "saved_calls": 0}

    async def add(self, item: dict):
        """Bir eylemi kuyruga ekle; kendi sonucunu bekle."""
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        async with self._lock:
            self._pending.append((item, fut))
            if len(self._pending) >= self.min_batch:
                # Pencere doldu: bekleyen zamanlayiciyi IPTAL ETME isini
                # _flush_locked'a birakmiyoruz (kendi kendini iptal sorunu),
                # burada guvenle iptal ediyoruz — bu kod zamanlayici
                # gorevinin ICINDE calismiyor.
                self._cancel_timer()
                await self._flush_locked()
            elif self._timer is None:
                self._timer = asyncio.ensure_future(self._wait_and_flush())
        return await fut

    def _cancel_timer(self):
        """Bekleyen zamanlayiciyi iptal et. ASLA calisan zamanlayicinin
        KENDI icinden cagrilmamali (kendini iptal eder)."""
        t, self._timer = self._timer, None
        if t is not None and not t.done():
            t.cancel()

    async def _wait_and_flush(self):
        """Zaman penceresi dolunca kuyrugu bosalt.

        KRITIK: burada self._timer'a DOKUNULMAZ. Eskiden _flush_locked
        icinde self._timer.cancel() vardi; _wait_and_flush _flush_locked'i
        cagirdigi icin gorev KENDINI iptal ediyordu. Handler ag cagrisi gibi
        bir sebeple askiya alindiginda CancelledError tam da orada patlayip
        'except CancelledError: pass' tarafindan yutuluyordu — batch'teki
        future'lar SONSUZA KADAR cozulmeden kaliyor, add() bekleyen her
        cagiran donmuyordu. Artik zamanlayici kendini iptal etmez."""
        try:
            await asyncio.sleep(self.max_wait_s)
        except asyncio.CancelledError:
            return          # normal: pencere dolmadan min_batch'e ulasildi
        async with self._lock:
            # Kendi kaydimizi temizle ki _flush_locked'tan sonra add()
            # yeni bir zamanlayici kurabilsin.
            if self._timer is asyncio.current_task():
                self._timer = None
            await self._flush_locked()

    async def _flush_locked(self):
        """Kuyrugu bosalt (cagiran _lock'u tutuyor olmali).

        Zamanlayici iptali BILEREK burada yapilmaz — bkz. _wait_and_flush."""
        while self._pending:
            batch = self._pending[: self.max_batch]
            self._pending = self._pending[self.max_batch :]
            items = [b[0] for b in batch]
            futures = [b[1] for b in batch]
            self.stats["batches"] += 1
            self.stats["items"] += len(items)
            self.stats["saved_calls"] += max(0, len(items) - 1)
            try:
                results = await self.handler(items) if self.handler else [None] * len(items)
            except asyncio.CancelledError:
                # Iptal edilsek bile cagiranlari ASILI BIRAKMA.
                for f in futures:
                    if not f.done():
                        f.cancel()
                raise
            except Exception as e:
                for f in futures:
                    if not f.done():
                        f.set_exception(e)
                continue
            if not isinstance(results, list) or len(results) != len(futures):
                results = [results] * len(futures)
            for f, r in zip(futures, results):
                if not f.done():
                    f.set_result(r)

    async def flush(self):
        async with self._lock:
            self._cancel_timer()
            await self._flush_locked()

    def pending(self) -> int:
        return len(self._pending)
