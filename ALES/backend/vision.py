"""
Vision - ALES ekrani gorur ve anlar.

HIZ SIRALAMASI (Ali'nin "max hiza cikar" istegiyle yeniden tasarlandi):
  1) OCR fast-path   - soru "ekranda ne yaziyor" turundeyse, hicbir LLM'e
                        gitmeden yerel Tesseract OCR ile ANINDA (~100-300ms,
                        ag yok) cevap verilir.
  2) Ollama/Ministral 3 (YEREL) - ayni bilgisayarda calisan bir Ollama
                        sunucusu + Ministral 3 vision modeli varsa once o
                        denenir: AG GECIKMESI SIFIR (istek hic internete
                        cikmiyor). Ollama calismiyorsa ~0.4sn icinde vazgecip
                        buluta duser (60sn cache'lenir, her seferinde
                        beklenmez).
  3) Groq (Qwen3.6-27B) - bulut secenekleri arasinda en dusuk gecikmeli
                        olan (LPU donanimi) - once bu denenir.
  4) OpenRouter / NVIDIA Nemotron 3 Nano Omni (ucretsiz) - Groq/Ollama
                        yoksa/basarisizsa, ucretsiz bir multimodal yedek.
  5) Gemini 2.5 Flash - yedek/dogruluk odakli son secenek.

Ayrica: ekran goruntusu varsayilan olarak TUM EKRAN yerine AKTIF PENCERE
bolgesinde aliniyor (cok daha kucuk payload = daha hizli encode+upload+
inference). Kullanici acikca "tum ekrani" isterse tam ekrana donuluyor.
"""
import base64
import time
from pathlib import Path

MAX_PREVIEW_WIDTH = 800
JPEG_QUALITY = 70

# Ekranda yazi okuma niyetini yakalayan anahtar kelimeler - bunlar
# eslesirse OCR once denenir (LLM'den COK daha hizli, ag gerektirmez)
OCR_TRIGGER_KEYWORDS = [
    "ne yazıyor", "ne yaziyor", "yazıyı oku", "yaziyi oku", "metni oku",
    "text oku", "yazısı ne", "yazisi ne", "içeriği oku", "icerigi oku",
    "ekrandaki yazı", "ekrandaki yazi", "ekrandaki metin", "metnini oku",
]


def encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ─── 1) OCR FAST-PATH (yerel, ~100-300ms, ag yok) ─────────────────
def _try_ocr(img, question: str):
    """Soru bir 'ekranda ne yazıyor' turundeyse Tesseract OCR ile ANINDA
    metni cikartir. pytesseract/Tesseract kurulu degilse ya da soru bu
    turden degilse None doner (caller normal vision akisina devam eder)."""
    q = (question or "").lower()
    if not any(kw in q for kw in OCR_TRIGGER_KEYWORDS):
        return None
    try:
        import pytesseract
    except ImportError:
        return None
    try:
        text = pytesseract.image_to_string(img, lang="tur+eng").strip()
        if len(text) < 5:
            return None
        if len(text) > 2000:
            text = text[:2000] + "...[kesildi]"
        return f"[OCR - anında, LLM kullanılmadı]\n{text}"
    except Exception:
        return None


# ─── 2) YEREL OLLAMA / MINISTRAL 3 ─────────────────────────────────
_ollama_status = {"available": None, "checked_at": 0.0}


def _ollama_running() -> bool:
    """Ollama'nin ayni makinede calisip calismadigini kontrol eder -
    sonuc 60sn cache'lenir ki Ollama kurulu degilse HER ekran sorgusunda
    tekrar tekrar beklenmesin."""
    now = time.time()
    if _ollama_status["available"] is not None and now - _ollama_status["checked_at"] < 60:
        return _ollama_status["available"]
    available = False
    try:
        import httpx
        r = httpx.get("http://localhost:11434/api/tags", timeout=0.4)
        available = r.status_code == 200
    except Exception:
        available = False
    _ollama_status["available"] = available
    _ollama_status["checked_at"] = now
    return available


def _analyze_with_ollama(screenshot_path: str, question: str, model: str = "ministral-3"):
    """Yerelde calisan Ollama + Ministral 3 (vision) modelini dener.
    Basariliysa AG GECIKMESI SIFIR (istek hic disariya cikmiyor). Ollama
    calismiyorsa/model cekilmemisse None doner, caller buluta duser."""
    if not _ollama_running():
        return None
    try:
        import httpx
        img_b64 = encode_image(screenshot_path)
        r = httpx.post(
            "http://localhost:11434/api/chat",
            json={
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": f"Türkçe, kısa yanıtla (max 3 cümle). {question}",
                    "images": [img_b64],
                }],
                "stream": False,
            },
            timeout=12,
        )
        r.raise_for_status()
        text = (r.json().get("message", {}) or {}).get("content", "").strip()
        return text or None
    except Exception as e:
        print(f"[VISION] Ollama/Ministral 3 basarisiz: {e}")
        return None


# ─── 3) GROQ (Qwen3.6-27B - bulutta en dusuk gecikme) ─────────────
def _analyze_with_groq(screenshot_path: str, question: str, groq_key: str):
    """NOT: Groq, Haziran 2026'da Llama 4 Scout vision modelini emekliye
    ayirdi (meta-llama/llama-4-scout-17b-16e-instruct artik calismiyor -
    'model_decommissioned' hatasi veriyor). Yerine Groq'un onerdigi
    qwen/qwen3.6-27b kullaniliyor (Groq'ta 'preview' etiketli ama vision
    destekli ve calisan tek model)."""
    try:
        img_data = encode_image(screenshot_path)
        mime = "image/jpeg" if screenshot_path.lower().endswith((".jpg", ".jpeg")) else "image/png"
        from groq import Groq
        client = Groq(api_key=groq_key)
        response = client.chat.completions.create(
            model="qwen/qwen3.6-27b",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_data}"}},
                    {"type": "text", "text": f"Türkçe, kısa yanıtla (max 3 cümle). {question}"}
                ]
            }],
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"[VISION] Groq basarisiz: {e}")
        return None


# ─── 3.5) OPENROUTER / NVIDIA NEMOTRON 3 NANO OMNI (ucretsiz yedek) ─
def _analyze_with_openrouter(screenshot_path: str, question: str, openrouter_key: str):
    """NVIDIA'nin ucretsiz (OpenRouter uzerinden) multimodal modeli -
    Nemotron 3 Nano Omni. Groq'ta HENUZ mevcut degil (topluluk talep
    ediyor ama Groq şu an sadece Qwen3.6-27B'yi (preview) vision icin sunuyor),
    bu yuzden OpenRouter'in ucretsiz katmani uzerinden erisiliyor.
    'reasoning' varyanti oldugu icin (dusunme adimi var) Groq/Gemini'den
    biraz daha yavas olabilir - zincirde ek bir ucretsiz yedek olarak
    duruyor, birincil hiz secenegi degil."""
    try:
        import httpx
        img_data = encode_image(screenshot_path)
        mime = "image/jpeg" if screenshot_path.lower().endswith((".jpg", ".jpeg")) else "image/png"
        r = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {openrouter_key}", "Content-Type": "application/json"},
            json={
                "model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Türkçe, kısa yanıtla (max 3 cümle). {question}"},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_data}"}},
                    ],
                }],
                "max_tokens": 500,
            },
            timeout=20,
        )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()
        return text or None
    except Exception as e:
        print(f"[VISION] OpenRouter/Nemotron Nano Omni basarisiz: {e}")
        return None


# ─── 4) GEMINI FLASH (yedek / dogruluk odakli) ───────────────────
def _analyze_with_gemini(screenshot_path: str, question: str, gemini_key: str):
    """Basarili olursa metni, olmazsa None doner. google-genai SDK kullanir."""
    k = (gemini_key or "").strip()
    if not k:
        return None
    try:
        from google import genai
        from PIL import Image
        client = genai.Client(api_key=k)
        img = Image.open(screenshot_path)
        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=[f"Türkçe, kısa yanıtla (max 3 cümle). {question}", img]
        )
        text = (response.text or "").strip()
        return text or None
    except Exception as e:
        print(f"[VISION] google-genai basarisiz: {e}")
        try:
            import google.generativeai as genai
            from PIL import Image
            genai.configure(api_key=k)
            model = genai.GenerativeModel("gemini-flash-latest")
            img = Image.open(screenshot_path)
            response = model.generate_content([f"Türkçe, kısa yanıtla (max 3 cümle). {question}", img])
            text = (response.text or "").strip()
            return text or None
        except Exception as e2:
            print(f"[VISION] Gemini legacy de basarisiz: {e2}")
            return None


def analyze_screenshot(screenshot_path: str, question: str = "Ekranda ne var? Ne yapilabilir?") -> str:
    """Ekran goruntusunu analiz et. HIZ SIRASI: Ollama/Ministral3 (yerel,
    varsa) -> Groq Llama4 Scout (bulutta en hizli) -> Gemini 2.5 Flash
    (yedek/dogruluk)."""
    try:
        from config_manager import load_config
        cfg = load_config()

        if not Path(screenshot_path).exists():
            return "Ekran goruntusu bulunamadi."

        # 1) Yerel Ministral 3 (Ollama) - ag gecikmesi sifir
        result = _analyze_with_ollama(screenshot_path, question)
        if result:
            return result

        # 2) Groq - bulutta en dusuk gecikme (LPU)
        if cfg.get("groq_key"):
            result = _analyze_with_groq(screenshot_path, question, cfg["groq_key"])
            if result:
                return result

        # 3) OpenRouter - NVIDIA Nemotron 3 Nano Omni (ucretsiz yedek)
        openrouter_key = cfg.get("openrouter_key", "")
        if openrouter_key:
            result = _analyze_with_openrouter(screenshot_path, question, openrouter_key)
            if result:
                return result

        # 4) Gemini - yedek
        gemini_key = cfg.get("gemini_key", "")
        if gemini_key:
            result = _analyze_with_gemini(screenshot_path, question, gemini_key)
            if result:
                return result

        if not cfg.get("groq_key") and not gemini_key and not openrouter_key:
            return "Vision icin Groq, Gemini veya OpenRouter key gerekli (ya da yerelde Ollama+Ministral 3 calistir)."
        return "Vision analizi basarisiz - hicbir saglayiciya ulasilamadi."
    except Exception as e:
        return f"Vision hatasi: {e}"


# ─── AKTIF PENCERE YAKALAMA (HIZ) ──────────────────────────────────
def _get_active_window_rect():
    """Windows: odaktaki (aktif) pencerenin ekran koordinatlarini
    (left, top, right, bottom) dondurur. Ekstra kutuphane gerektirmez -
    dogrudan Win32 API'sini ctypes ile cagirir. Basarisiz olursa (Windows
    disi bir platform, API hatasi vb.) None doner - caller tam ekrana
    duser."""
    try:
        import ctypes
        import ctypes.wintypes as wintypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        # Gecersiz/anlamsiz bir bolge (orn. simge durumuna kucultulmus
        # pencere -32000 gibi koordinatlar dondurebilir) - bu durumda
        # tam ekrana duselim
        if rect.right - rect.left < 50 or rect.bottom - rect.top < 50:
            return None
        return (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        return None


def _grab_screen(region: str = "auto"):
    """region: 'auto' (varsayilan - aktif pencere varsa onu, yoksa tam
    ekrani yakalar - KUCUK payload = HIZLI), 'active_window' (illa aktif
    pencere), 'full_screen' (illa tum ekran/tum monitorler)."""
    from PIL import ImageGrab, Image
    bbox = None
    if region in ("auto", "active_window"):
        bbox = _get_active_window_rect()
        if region == "active_window" and bbox is None:
            # kullanici acikca aktif pencere istedi ama bulunamadi -
            # yine de bir goruntu dondurelim (tam ekran)
            pass
    if bbox:
        try:
            return ImageGrab.grab(bbox=bbox)
        except Exception:
            pass
    try:
        return ImageGrab.grab()
    except Exception:
        # Fallback to mss (100% reliable on Windows even when ImageGrab fails)
        try:
            import mss
            with mss.mss() as sct:
                monitor = sct.monitors[0]
                shot = sct.grab(monitor)
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                if bbox:
                    l, t, r, b = bbox
                    return img.crop((max(0, l), max(0, t), min(img.width, r), min(img.height, b)))
                return img
        except Exception as e:
            raise RuntimeError(f"Ekran yakalama basarisiz: {e}")



def analyze_screen_and_act(question: str, region: str = "auto") -> str:
    """Ekran goruntusunu al, analiz et. HIZ: (1) once OCR fast-path
    denenir (soru uygunsa), (2) sonra kucultulmus/sikistirilmis goruntu
    analyze_screenshot()'un hizli-once-yerel-sonra-bulut zincirine
    gonderilir."""
    try:
        import tempfile, os
        path = os.path.join(tempfile.gettempdir(), "ales_vision.jpg")
        img = _grab_screen(region)
        if img.width > MAX_PREVIEW_WIDTH:
            ratio = MAX_PREVIEW_WIDTH / float(img.width)
            img = img.resize((MAX_PREVIEW_WIDTH, max(1, int(img.height * ratio))))
        rgb_img = img.convert("RGB")

        # OCR fast-path - LLM'e hic gitmeden, orijinal (kucultulmemis)
        # goruntu uzerinde dene (daha okunakli metin icin buyuk boy
        # kullanmak OCR dogrulugunu artirir, hizi neredeyse etkilemez)
        ocr_result = _try_ocr(img, question)
        if ocr_result:
            return ocr_result

        rgb_img.save(path, "JPEG", quality=JPEG_QUALITY, optimize=True)
        return analyze_screenshot(path, question)
    except Exception as e:
        return f"Ekran analizi hatasi: {e}"


def find_element_on_screen(element_description: str, region: str = "auto") -> str:
    """Ekranda bir elementi bul, koordinatini ver"""
    return analyze_screen_and_act(
        f"'{element_description}' var mi? Varsa x,y koordinat. Yoksa 'bulunamadi'.",
        region=region,
    )
