"""
audio_streamer.py — Akan ses (streaming TTS). runtime_state.py'deki
"realtime_tts" slotunun Faz-2 karsiligi.

NEDEN: Bugun main.py send_tts_audio (satir ~825) TUM yanit bitmeden ses
uretmeye baslamaz: metin tamamlanir, tek seferde sese cevrilir, tek parca
gonderilir. Uzun yanitta kullanici sessizce bekler. Burada metni CUMLE
CUMLE sese ceviriyoruz: ilk cumle hazir olur olmaz calmaya baslar, geri
kalani arkadan gelir.

TASARIM KARARI — neden ham edge_tts alt-parcalarini iletmiyoruz:
edge_tts .stream() mp3'u kucuk parcalar halinde verir, ama TEK BASINA bir
mp3 parcasi cozulebilir bir dosya DEGILDIR; tarayicidaki <audio> onu
calamaz. O yuzden bir CUMLENIN tum parcalarini toplayip tam bir mp3 olarak
gonderiyoruz. Boylece her parca bagimsiz calinabilir olur ve ilk-ses
gecikmesi "ilk cumlenin suresi" kadar olur, tum yanit kadar degil.

MOTOR ZINCIRI (cagri aninda secilir, import aninda degil):
  1. edge_tts      — KURULU (edge-tts==6.1.12). Turkce tr-TR-AhmetNeural.
                     Tarayiciya/telefona ULASAN yol. VARSAYILAN.
  2. RealtimeTTS   — kurulu DEGIL (pip install RealtimeTTS). Kurulursa
                     yerel oynatma icin kullanilabilir; asagidaki nota bak.
  3. system (SAPI) — pyttsx3 veya win32com. Kurulu DEGIL.

ONEMLI DAVRANIS FARKI: RealtimeTTS ve SAPI sesi MAKINENIN hoparlorunden
calar; byte dondurmezler. voice.py'nin dokumantasyonunda anlatilan sorun
tam olarak buydu — ALES telefondan kullanilirken ses PC'den cikiyordu.
Bu yuzden VARSAYILAN motor edge_tts'tir ve digerleri "yerel oynatma"
olarak isaretlenir (engine_info()["local_playback"]). Bu bir detay degil,
kullanicinin duyup duymamasini belirleyen sey.
"""
import asyncio
import os
import sys
import re
import threading
import time

def _bundle_path(rel_path: str) -> str:
    """PyInstaller _MEIPASS veya normal dosya yolu çözücü."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel_path)


# ─── OPSIYONEL BAGIMLILIKLAR ───────────────────────────────────────────
try:
    import edge_tts
except Exception:
    edge_tts = None

try:                      # pip install RealtimeTTS  (kurulu degil)
    import RealtimeTTS as _rtts
except Exception:
    _rtts = None

try:                      # pip install pyttsx3      (kurulu degil)
    import pyttsx3
except Exception:
    pyttsx3 = None

try:                      # Windows SAPI (pywin32 ile gelir; kurulu degil)
    import win32com.client as _win32com
except Exception:
    _win32com = None

# Markdown temizligini YENIDEN YAZMIYORUZ: voice.py'de calisan bir tane var
# ve ALES'te tek idiom olmali (** kalin ** gibi isaretler sesli okunmasin).
try:
    from voice import _clean_for_speech as _clean
except Exception:
    def _clean(t):
        return (t or "").strip()

# ─── AYARLAR ───────────────────────────────────────────────────────────
DEFAULT_TR_VOICE = "tr-TR-AhmetNeural"
FALLBACK_TR_VOICE = "tr-TR-EmelNeural"
MIN_CHARS = 12            # bundan kisa parca ayri cumle sayilmaz
MAX_SENTENCE_CHARS = 400  # cok uzun cumle TTS'i bekletir; zorla bolunur
MAX_TOTAL_CHARS = 6000    # tek yanitta sese cevrilecek ust sinir

_MIME = {"edge_tts": "audio/mpeg", "pyttsx3": "audio/wav"}

_lock = threading.RLock()
_stats = {"calls": 0, "chunks": 0, "bytes": 0, "failures": 0,
          "sentences": 0, "engine_used": None, "first_audio_total_s": 0.0,
          "first_audio_n": 0, "last_error": None}


# ─── CUMLE BOLME ───────────────────────────────────────────────────────
# Yarim cumleyi sese cevirmek yanlis tonlama ve kesik kelime uretir; o
# yuzden sadece TAM cumlelerde boluyoruz.
_ABBREV = ("vb", "vs", "dr", "sn", "bkz", "prof", "doc", "doç", "av",
           "mah", "cad", "sok", "no", "orn", "örn", "yy", "tl", "ör",
           "bkz", "age", "hz", "st", "mr", "mrs", "ms", "vd")
_SENT_END = ".!?…:;\n"


def _is_split_point(buf: str, i: int) -> bool:
    """buf[i] bir cumle sonu mu? Yanlis bolmeleri tek tek engelliyoruz."""
    ch = buf[i]
    if ch not in _SENT_END:
        return False
    if ch == "\n":
        return True
    # 1) Sayi icinde nokta: "3.14" veya "1.000" bolunmemeli.
    if ch == "." and i > 0 and buf[i - 1].isdigit():
        nxt = buf[i + 1] if i + 1 < len(buf) else ""
        if nxt.isdigit():
            return False
    # 2) Kisaltmadan sonra nokta: "vb." / "Dr." bolunmemeli.
    if ch == ".":
        m = re.search(r"([A-Za-zÇĞİÖŞÜçğıöşü]{1,5})\.$", buf[:i + 1])
        if m and m.group(1).casefold() in _ABBREV:
            return False
        # 3) Tek harf + nokta (bas harf: "A. Yilmaz") bolunmemeli.
        if i >= 1 and buf[i - 1].isalpha() and (i < 2 or not buf[i - 2].isalnum()):
            return False
    # 4) Uc nokta ortasinda bolme ("...") — son noktayi bekle.
    if ch == "." and i + 1 < len(buf) and buf[i + 1] == ".":
        return False
    return True


def split_sentences(text: str) -> list:
    """Metni sese uygun cumlelere bol. MIN_CHARS'tan kisa parcalar bir
    sonrakiyle birlestirilir — kisa unlemler tek tek gonderilse ses
    kekeleyerek gelir."""
    text = (text or "").strip()
    if not text:
        return []
    out, buf = [], ""
    for i, ch in enumerate(text):
        buf += ch
        if _is_split_point(text, i) and len(buf.strip()) >= MIN_CHARS:
            out.append(buf.strip())
            buf = ""
        elif len(buf) >= MAX_SENTENCE_CHARS:
            # Cumle bitmiyor ama beklemek ilk-ses gecikmesini buyutuyor:
            # son bosluktan zorla bol.
            cut = buf.rfind(" ")
            if cut < MIN_CHARS:
                cut = len(buf)
            out.append(buf[:cut].strip())
            buf = buf[cut:]
    if buf.strip():
        if out and len(buf.strip()) < MIN_CHARS:
            out[-1] = (out[-1] + " " + buf.strip()).strip()
        else:
            out.append(buf.strip())
    return [s for s in out if s]


class SentenceStreamer:
    """Token besle, TAM cumleler al.

    main.py router'dan token token yanit alir; her token'da feed() cagirilir
    ve donen cumleler hemen sese cevrilir.
    """

    def __init__(self, min_chars: int = None):
        self.min_chars = int(min_chars or MIN_CHARS)
        self._buf = ""

    def feed(self, token: str) -> list:
        if not token:
            return []
        self._buf += token
        done = []
        # Tampondaki her cumle sonunu sirayla tuket.
        i = 0
        while i < len(self._buf):
            if _is_split_point(self._buf, i):
                head = self._buf[:i + 1].strip()
                if len(head) >= self.min_chars:
                    done.append(head)
                    self._buf = self._buf[i + 1:]
                    i = 0
                    continue
            i += 1
        if len(self._buf) >= MAX_SENTENCE_CHARS:
            cut = self._buf.rfind(" ")
            if cut < self.min_chars:
                cut = len(self._buf)
            done.append(self._buf[:cut].strip())
            self._buf = self._buf[cut:]
        return [d for d in done if d]

    def flush(self) -> str:
        rest, self._buf = self._buf.strip(), ""
        return rest

    def reset(self) -> None:
        self._buf = ""


# ─── MOTOR SECIMI ──────────────────────────────────────────────────────
def _engines() -> list:
    return [
        {"name": "edge_tts", "installed": edge_tts is not None,
         "streaming": True, "local_playback": False,
         "reason": "" if edge_tts else "pip install edge-tts",
         "note": "Ucretsiz, Turkce noral ses; bytes doner -> tarayici/telefon calar."},
        {"name": "realtimetts", "installed": _rtts is not None,
         "streaming": True, "local_playback": True,
         "reason": "" if _rtts else "pip install RealtimeTTS",
         "note": ("Dusuk gecikme, ama sesi MAKINENIN hoparlorunden calar; "
                  "telefondan kullanilirken duyulmaz.")},
        {"name": "system", "installed": bool(pyttsx3 or _win32com),
         "streaming": False,
         "local_playback": pyttsx3 is None,   # pyttsx3 dosyaya yazabilir
         "reason": "" if (pyttsx3 or _win32com) else "pip install pyttsx3",
         "note": ("Yerel Windows SAPI sesleri. pyttsx3 varsa WAV bytes "
                  "uretilebilir; sadece win32com varsa yalniz yerel oynatma.")},
    ]


def pick_engine(prefer: str = None) -> str:
    """Kullanilacak motoru cagri aninda sec. Tercih kuruluysa o, degilse
    edge_tts, o da yoksa system. Hicbiri yoksa None."""
    engines = {e["name"]: e for e in _engines()}
    if prefer and engines.get(prefer, {}).get("installed"):
        return prefer
    for name in ("edge_tts", "realtimetts", "system"):
        if engines[name]["installed"]:
            return name
    return None


def engine_info() -> dict:
    active = pick_engine()
    engines = _engines()
    cur = next((e for e in engines if e["name"] == active), None)
    with _lock:
        used = _stats["engine_used"]
        n = _stats["first_audio_n"]
        avg = round(_stats["first_audio_total_s"] / n, 3) if n else None
    return {
        "engine": active,
        "available": active is not None,
        "voice": DEFAULT_TR_VOICE,
        "voices": [DEFAULT_TR_VOICE, FALLBACK_TR_VOICE],
        "streaming": bool(cur and cur.get("streaming")),
        "local_playback": bool(cur and cur.get("local_playback")),
        "mime": _MIME.get(active, "audio/mpeg"),
        "engines": engines,
        "engine_used": used,
        "avg_first_audio_s": avg,
        "min_chars": MIN_CHARS,
        "reason": "" if active else "hicbir TTS motoru kurulu degil",
        "note": ("Varsayilan edge_tts: ses bytes olarak websocket'ten "
                 "tarayiciya gider, boylece telefondan da duyulur."),
    }


def available() -> bool:
    return pick_engine() is not None


# runtime_state.refresh_modules() bu adi arar (tum yeni modullerde ayni ad).
info = engine_info


# ─── TEK CUMLE SENTEZI ─────────────────────────────────────────────────
async def _synth_edge(text: str, voice: str) -> bytes:
    """edge_tts ile tam bir cumleyi mp3'e cevir. .stream() parcalarini
    BURADA birlestiriyoruz (tek parca bagimsiz calinamaz — modul basligi)."""
    buf = bytearray()
    comm = edge_tts.Communicate(text, voice)
    async for chunk in comm.stream():
        if chunk.get("type") == "audio" and chunk.get("data"):
            buf += chunk["data"]
    return bytes(buf)


def _synth_pyttsx3_sync(text: str) -> bytes:
    """pyttsx3 -> WAV bytes. SENKRON; executor icinde cagirilir."""
    path = os.path.join(os.environ.get("TEMP", "."),
                        f"ales_tts_{int(time.time() * 1000)}.wav")
    try:
        eng = pyttsx3.init()
        eng.save_to_file(text, path)
        eng.runAndWait()
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return b""
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


def _speak_local_sync(text: str) -> bool:
    """SAPI ile MAKINEDE sesli oku. Byte dondurmez (bkz. modul basligi)."""
    try:
        if _win32com is not None:
            sp = _win32com.Dispatch("SAPI.SpVoice")
            sp.Speak(text)
            return True
        if pyttsx3 is not None:
            eng = pyttsx3.init()
            eng.say(text)
            eng.runAndWait()
            return True
    except Exception:
        pass
    return False


def _synth_sapi_sync(text: str) -> bytes:
    """Windows SAPI -> WAV bytes (çevrimdışı güvenilir ses üretimi)."""
    path = os.path.join(os.environ.get("TEMP", "."), f"ales_sapi_{int(time.time()*1000)}.wav")
    try:
        import win32com.client
        import pythoncom
        pythoncom.CoInitialize()
        sp = win32com.client.Dispatch("SAPI.SpVoice")
        fs = win32com.client.Dispatch("SAPI.SpFileStream")
        fs.Open(path, 3)
        sp.AudioOutputStream = fs
        sp.Speak(text)
        fs.Close()
        if os.path.exists(path) and os.path.getsize(path) > 44:
            with open(path, "rb") as f:
                return f.read()
    except Exception as e:
        print(f"[TTS] SAPI hatasi: {e}")
    finally:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
    return b""


async def synth_sentence(text: str, voice: str = None,
                         engine: str = None) -> bytes:
    """Tek cumleyi sese cevir. Basarisizlikta b"" doner, ASLA raise etmez."""
    text = (text or "").strip()
    if not text:
        return b""
    eng = pick_engine(engine)
    voice = voice or DEFAULT_TR_VOICE
    try:
        if eng == "edge_tts":
            try:
                data = await asyncio.wait_for(_synth_edge(text, voice), timeout=10.0)
                if data:
                    return data
            except Exception as ee:
                print(f"[TTS] edge_tts basarisiz, SAPI yedegine geciliyor: {ee}")
            return await asyncio.get_running_loop().run_in_executor(
                None, _synth_sapi_sync, text)
        if eng == "realtimetts":
            # RealtimeTTS yerel calar; byte uretmez. Metni yerel oku ve
            # cagirana bos bytes dondur (o da "local_playback" gorur).
            await asyncio.get_running_loop().run_in_executor(
                None, _rtts_speak_sync, text, voice)
            return b""
        if eng == "system":
            if pyttsx3 is not None:
                return await asyncio.get_running_loop().run_in_executor(
                    None, _synth_pyttsx3_sync, text)
            await asyncio.get_running_loop().run_in_executor(
                None, _speak_local_sync, text)
            return b""
    except Exception as e:
        with _lock:
            _stats["failures"] += 1
            _stats["last_error"] = f"{type(e).__name__}: {e}"[:200]
    return b""


def _rtts_speak_sync(text: str, voice: str) -> bool:
    """RealtimeTTS ile yerel oynatma. Kutuphane kurulu degil; kurulursa
    API adlari surume gore degisebilecegi icin her sey try icinde."""
    try:
        Engine = getattr(_rtts, "EdgeEngine", None) or getattr(_rtts, "SystemEngine", None)
        Stream = getattr(_rtts, "TextToAudioStream", None)
        if not (Engine and Stream):
            return False
        try:
            engine = Engine(voice=voice)
        except TypeError:
            engine = Engine()
        stream = Stream(engine)
        stream.feed(text)
        stream.play()
        return True
    except Exception:
        return False


# ─── AKIS API ──────────────────────────────────────────────────────────
async def stream_text(text: str, on_chunk, voice: str = None,
                      engine: str = None) -> dict:
    """Tam metni cumle cumle sese cevir ve her parcayi on_chunk'a ver.

    on_chunk: async (audio_bytes: bytes, mime: str, seq: int, is_last: bool)
    Doner: {"ok","engine","chunks","bytes","sentences","elapsed",
            "first_audio_s","local_playback","error"}
    """
    t0 = time.time()
    out = {"ok": False, "engine": None, "chunks": 0, "bytes": 0,
           "sentences": 0, "elapsed": 0.0, "first_audio_s": None,
           "local_playback": False, "error": None}
    eng = pick_engine(engine)
    out["engine"] = eng
    if eng is None:
        out["error"] = "hicbir TTS motoru kurulu degil"
        return out

    clean = _clean(text)[:MAX_TOTAL_CHARS]
    sentences = split_sentences(clean)
    out["sentences"] = len(sentences)
    if not sentences:
        out["ok"] = True
        return out

    info = next((e for e in _engines() if e["name"] == eng), {})
    out["local_playback"] = bool(info.get("local_playback"))
    mime = _MIME.get(eng, "audio/mpeg")

    with _lock:
        _stats["calls"] += 1
        _stats["engine_used"] = eng
        _stats["sentences"] += len(sentences)

    seq = 0
    for idx, s in enumerate(sentences):
        data = await synth_sentence(s, voice=voice, engine=eng)
        is_last = (idx == len(sentences) - 1)
        if not data:
            if out["local_playback"]:
                continue          # yerel calindi, gonderilecek byte yok
            continue              # bu cumle uretilemedi; digerine gec
        if out["first_audio_s"] is None:
            out["first_audio_s"] = round(time.time() - t0, 3)
            with _lock:
                _stats["first_audio_total_s"] += out["first_audio_s"]
                _stats["first_audio_n"] += 1
        try:
            await on_chunk(data, mime, seq, is_last)
        except Exception as e:
            out["error"] = f"on_chunk hatasi: {type(e).__name__}"
            break
        seq += 1
        out["chunks"] += 1
        out["bytes"] += len(data)
        with _lock:
            _stats["chunks"] += 1
            _stats["bytes"] += len(data)

    out["ok"] = out["chunks"] > 0 or out["local_playback"]
    out["elapsed"] = round(time.time() - t0, 3)
    return out


async def stream_tokens(token_iter, on_chunk, voice: str = None,
                        engine: str = None) -> dict:
    """Token akisini cumle cumle sese cevir.

    token_iter: async-iterable of str. Model daha yazmaya devam ederken ilk
    cumle sese cevrilmeye baslar — bu, modulun asil amaci.
    """
    t0 = time.time()
    out = {"ok": False, "engine": None, "chunks": 0, "bytes": 0,
           "sentences": 0, "elapsed": 0.0, "first_audio_s": None,
           "local_playback": False, "error": None}
    eng = pick_engine(engine)
    out["engine"] = eng
    if eng is None:
        out["error"] = "hicbir TTS motoru kurulu degil"
        return out
    info = next((e for e in _engines() if e["name"] == eng), {})
    out["local_playback"] = bool(info.get("local_playback"))
    mime = _MIME.get(eng, "audio/mpeg")

    with _lock:
        _stats["calls"] += 1
        _stats["engine_used"] = eng

    st = SentenceStreamer()
    seq = 0
    total = 0

    async def _emit(sentence: str, is_last: bool):
        nonlocal seq
        data = await synth_sentence(_clean(sentence), voice=voice, engine=eng)
        if not data:
            return
        if out["first_audio_s"] is None:
            out["first_audio_s"] = round(time.time() - t0, 3)
            with _lock:
                _stats["first_audio_total_s"] += out["first_audio_s"]
                _stats["first_audio_n"] += 1
        await on_chunk(data, mime, seq, is_last)
        seq += 1
        out["chunks"] += 1
        out["bytes"] += len(data)
        with _lock:
            _stats["chunks"] += 1
            _stats["bytes"] += len(data)

    try:
        async for tok in token_iter:
            if not isinstance(tok, str):
                continue
            total += len(tok)
            if total > MAX_TOTAL_CHARS:
                break
            for s in st.feed(tok):
                out["sentences"] += 1
                await _emit(s, False)
        rest = st.flush()
        if rest:
            out["sentences"] += 1
            await _emit(rest, True)
        elif out["chunks"]:
            # Son parcayi "last" olarak isaretleyemedik; frontend kuyrugu
            # bosalinca zaten susar, ama bilgi olarak gonderelim.
            try:
                await on_chunk(b"", mime, seq, True)
            except Exception:
                pass
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"[:200]
        with _lock:
            _stats["failures"] += 1
            _stats["last_error"] = out["error"]

    out["ok"] = out["chunks"] > 0 or out["local_playback"]
    out["elapsed"] = round(time.time() - t0, 3)
    return out


# ─── ISTATISTIK ────────────────────────────────────────────────────────
def stats() -> dict:
    with _lock:
        s = dict(_stats)
    n = s.pop("first_audio_n", 0)
    tot = s.pop("first_audio_total_s", 0.0)
    s["avg_first_audio_s"] = round(tot / n, 3) if n else None
    s["measured_calls"] = n
    s["engine"] = pick_engine()
    return s


def reset_stats() -> dict:
    with _lock:
        _stats.update({"calls": 0, "chunks": 0, "bytes": 0, "failures": 0,
                       "sentences": 0, "engine_used": None,
                       "first_audio_total_s": 0.0, "first_audio_n": 0,
                       "last_error": None})
    return stats()
