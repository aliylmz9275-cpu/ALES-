"""
ALES Ses Modulu
- ElevenLabs: gercekci/dogal sesler (key gerekir, secilebilir)
- Edge TTS: ucretsiz yedek (key yoksa veya ElevenLabs basarisiz olursa)

Bu modul SENKRON calisir - main.py bunu ThreadPoolExecutor icinde
cagirir, boylece ses uretimi asyncio event loop'unu kilitlemez.

ONEMLI (Ali'nin bildirdigi sorunun duzeltmesi): bu modul ARTIK sesi
kendisi CALMIYOR. Eskiden uretilen mp3 diske yazilip isletim
sisteminin varsayilan medya oynaticisiyla (subprocess ile) aciliyordu -
bu hem ayri bir pencere aciyordu hem de SADECE backend'in calistigi
bilgisayardan ses cikariyordu (telefondan kullaniliyorsa ses telefona
degil PC'ye gidiyordu). Simdi bu fonksiyonlar HAM SES BYTES doner;
main.py bunu websocket uzerinden frontend'e yolluyor, tarayici
<audio> ile CALIYOR - ChatGPT'deki gibi aninda, dosya penceresi
acilmadan, VE kullanicinin o an kullandigi cihazda (PC ya da telefon,
hangisinden bakiyorsa) ses cikiyor.
"""
import asyncio
import os
import re
import time
import concurrent.futures


def _clean_for_speech(text: str) -> str:
    """
    TTS'e gonderilmeden once markdown/format isaretlerini temizler.
    ONCEDEN: modelin ham metni (** kalin **, --- cizgiler, # basliklar,
    [link](url) vb.) OLDUGU GIBI sese cevriliyordu - TTS bu isaretleri
    kelime kelime okuyup "salak sacma" ciktilar uretiyordu. Bu, TTS'in
    kendisinin degil, ona giden metnin temizlenmemesinin sonucuydu.
    """
    if not text:
        return text
    t = text
    t = re.sub(r"```.*?```", "", t, flags=re.DOTALL)          # kod bloklari
    t = re.sub(r"`([^`]*)`", r"\1", t)                          # `kod` -> kod
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.MULTILINE)        # ## baslik
    t = re.sub(r"\*\*\*([^*]+)\*\*\*", r"\1", t)                # ***vurgu***
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)                    # **kalin**
    t = re.sub(r"\*([^*]+)\*", r"\1", t)                        # *italik*
    t = re.sub(r"^[\-\*_]{3,}\s*$", "", t, flags=re.MULTILINE)  # --- cizgi
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)               # [link](url)
    t = re.sub(r"^[\-\*]\s+", "", t, flags=re.MULTILINE)         # - madde
    t = re.sub(r"\n{2,}", ". ", t)
    t = re.sub(r"\n", " ", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()

# ElevenLabs'in cok-dilli (Turkce dahil) modelinde dogal sesli,
# JARVIS tarzina uygun secenekler. Kullanici ayarlardan secebilir.
ELEVENLABS_VOICES = [
    {"id": "pNInz6obpgDQGcFmaJgB", "name": "Adam - Derin Erkek (JARVIS tarzi)"},
    {"id": "VR6AewLTigWG4xSOukaG", "name": "Arnold - Sert/Otoriter Erkek"},
    {"id": "ErXwobaYiN019PkySvjV", "name": "Antoni - Sicak/Yumusak Erkek"},
    {"id": "TxGEqnHWrfWFTfGW9XjX", "name": "Josh - Genc Erkek"},
    {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel - Dogal Kadin"},
    {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella - Sicak Kadin"},
]
DEFAULT_ELEVENLABS_VOICE = "pNInz6obpgDQGcFmaJgB"  # Adam


def _temp_path(name: str) -> str:
    if os.name == "nt":
        return os.path.join(os.environ.get("TEMP", "."), name)
    return f"/tmp/{name}"


def synthesize_elevenlabs(text: str, api_key: str, voice_id: str = None):
    """ElevenLabs ile ses uretir. Basarili olursa ham mp3 bytes, olmazsa None doner."""
    if not api_key or not str(api_key).strip():
        return None
    try:
        import httpx
        key = str(api_key).strip()
        vid = (voice_id or DEFAULT_ELEVENLABS_VOICE).strip()
        # İsimle verilmişse (Adam / Rachel) ID eşleştirmesi yap
        voice_map = {
            "adam": "pNInz6obpgDQGcFmaJgB",
            "rachel": "21m00Tcm4TlvDq8ikWAM",
            "arnold": "VR6AewLTigWG4xSOukaG",
            "antoni": "ErXwobaYiN019PkySvjV",
            "josh": "TxGEqnHWrfWFTfGW9XjX",
            "bella": "EXAVITQu4vr4xnSDxMaL",
        }
        if vid.lower() in voice_map:
            vid = voice_map[vid.lower()]

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}"
        headers = {
            "xi-api-key": key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": text[:1000],
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.45,
                "similarity_boost": 0.8,
                "style": 0.25,
                "use_speaker_boost": True,
            },
        }
        with httpx.Client(timeout=25) as client:
            r = client.post(url, headers=headers, json=payload)
        if r.status_code != 200:
            print(f"[TTS] ElevenLabs HTTP {r.status_code}: {r.text[:200]}")
            return None
        return r.content
    except Exception as e:
        print(f"[TTS] ElevenLabs hatasi: {e}")
        return None


def synthesize_edge_sync(text: str, voice: str = "tr-TR-AhmetNeural"):
    """Edge-TTS - senkron sarmalayici (executor icinde calisir). Basarili
    olursa ham mp3 bytes, olmazsa None doner. edge_tts kutuphanesi
    API'si geregi once gecici bir dosyaya yaziyor, biz onu okuyup
    bytes olarak dondurup HEMEN siliyoruz - kalici dosya birikmesin."""
    pid = os.getpid()
    ts = int(time.time() * 1000)
    path = _temp_path(f"ales_voice_{pid}_{ts}.mp3")
    try:
        import edge_tts

        async def _gen():
            comm = edge_tts.Communicate(text[:600], voice)
            await comm.save(path)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(lambda: asyncio.run(_gen())).result(timeout=15)
        else:
            asyncio.run(_gen())

        if os.path.exists(path) and os.path.getsize(path) > 0:
            with open(path, "rb") as f:
                data = f.read()
            return data
        return None
    except Exception as e:
        print(f"[TTS] Edge-TTS hatasi: {e}")
        return None
    finally:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


# Edge-TTS'in Turkce noral sesleri - ElevenLabs key'i olmayanlar icin
# ucretsiz secenekler. Bazi kullanicilar varsayilan erkek sesi (Ahmet)
# "kotu/robotik" bulabiliyor - kadin ses (Emel) farkli bir karakter,
# bazen daha dogal geliyor. Ayarlar panelinden secilebilir.
EDGE_VOICES = [
    {"id": "tr-TR-AhmetNeural", "name": "Ahmet - Erkek (ücretsiz)"},
    {"id": "tr-TR-EmelNeural", "name": "Emel - Kadın (ücretsiz)"},
]
DEFAULT_EDGE_VOICE = "tr-TR-AhmetNeural"


def synthesize_sapi_sync(text: str) -> bytes | None:
    """Windows SAPI (SpVoice + SpFileStream) cevrimdisi WAV uretimi."""
    path = _temp_path("ales_voice_sapi.wav")
    try:
        import win32com.client
        import pythoncom
        pythoncom.CoInitialize()
        sp = win32com.client.Dispatch("SAPI.SpVoice")
        fs = win32com.client.Dispatch("SAPI.SpFileStream")
        fs.Open(path, 3)
        sp.AudioOutputStream = fs
        sp.Speak(text[:600])
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
    return None


def synthesize(text: str, elevenlabs_key: str = "", elevenlabs_voice: str = "", edge_voice: str = ""):
    """
    Ana TTS fonksiyonu. SENKRON - her zaman bir executor/thread icinde
    cagrilmali (asyncio event loop'unu kilitler). ARTIK SESI KENDISI
    CALMIYOR - ham ses bytes'i (mp3 veya wav) ya da None doner.
    Oncelik: ElevenLabs -> Edge-TTS -> SAPI (yerel ses motoru)
    """
    if not text or not text.strip():
        return None
    clean = _clean_for_speech(text)
    if not clean:
        return None

    if elevenlabs_key:
        data = synthesize_elevenlabs(clean, elevenlabs_key, elevenlabs_voice or DEFAULT_ELEVENLABS_VOICE)
        if data:
            return data
        print("[TTS] ElevenLabs basarisiz, Edge-TTS'e geciliyor...")

    edge_res = synthesize_edge_sync(clean, edge_voice or DEFAULT_EDGE_VOICE)
    if edge_res:
        return edge_res

    print("[TTS] Edge-TTS basarisiz, Windows SAPI motoruna geciliyor...")
    return synthesize_sapi_sync(clean)


