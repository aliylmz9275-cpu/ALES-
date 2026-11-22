"""
advisor.py — ALES otomasyon beyni (danisman LLM + gorsel fallback).

Model onceligi (phone_speed_control > model_mode):
  "auto"   -> once yerel Ollama (qwen2.5-coder:7b), olmazsa bulut
  "local"  -> sadece Ollama
  "cloud"  -> sadece OpenRouter/Gemini
Bulut sirasi: OpenRouter -> Gemini.

Iki ana is:
  1) ask_advisor_ai(context) : bir gorev/adim basarisiz oldugunda stack
     trace + XML baglamini modele verir, JSON doner:
        {"action":"override","x":0.5,"y":0.8}  -> bu oranlara dokun
        {"action":"skip","reason":"..."}       -> gorevi temiz atla
        {"action":"retry"}                      -> tekrar dene
  2) vision_locate(png, prompt) : XML basarisiz olunca ekran goruntusunu
     800px'e olcekleyip JPEG q=70 sikistirir, modele "su butonu bul,
     oranini ver" der; 7s sert zaman asimi (asyncio.wait_for).

Tum agir islemler (httpx istekleri, PIL) executor'da calisir - event
loop bloklanmaz.
"""
import asyncio
import base64
import io
import json
import re

try:
    from config_manager import load_config
except Exception:
    def load_config():
        return {}

from phone_speed_control import load_settings

_ADVISOR_SYSTEM = (
    "Sen bir Android UI otomasyon danismanisin. Sana bir hata (stack trace) "
    "ve o anki ekranin uiautomator XML dokumu verilir. Gorevin: bir sonraki "
    "hamleyi SADECE JSON olarak vermek. Secenekler:\n"
    '{\"action\":\"override\",\"x\":<0..1>,\"y\":<0..1>} -> ekran oranina dokun\n'
    '{\"action\":\"skip\",\"reason\":\"...\"} -> gorevi atla\n'
    '{\"action\":\"retry\"} -> ayni adimi tekrar dene\n'
    "Baska hicbir sey yazma, aciklama ekleme, yalnizca tek satir JSON."
)

_VISION_SYSTEM = (
    "Sen bir gorsel UI bulucususun. Ekran goruntusunde istenen butonu/alani "
    "bul ve merkezinin ekran oranini ver. SADECE JSON: "
    '{\"found\":true,\"x\":<0..1>,\"y\":<0..1>} veya {\"found\":false}.'
)


def _extract_json(text: str) -> dict:
    """Model bazen JSON etrafina laf katar - ilk gecerli {...} blogunu ayikla."""
    if not text:
        return {}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


# ─── OLLAMA (yerel) ──────────────────────────────────────────────
def _ollama_chat_blocking(system: str, user: str, images_b64: list = None) -> str:
    import httpx
    s = load_settings()
    url = s.get("ollama_url", "http://localhost:11434").rstrip("/") + "/api/chat"
    msg = {"role": "user", "content": user}
    if images_b64:
        msg["images"] = images_b64
    payload = {
        "model": s.get("ollama_model", "qwen2.5-coder:7b") if not images_b64
                 else s.get("ollama_vision_model", s.get("ollama_model", "qwen2.5-coder:7b")),
        "messages": [{"role": "system", "content": system}, msg],
        "stream": False,
        "options": {"temperature": 0.1},
    }
    with httpx.Client(timeout=20) as c:
        r = c.post(url, json=payload)
    if r.status_code != 200:
        raise RuntimeError(f"ollama HTTP {r.status_code}: {r.text[:160]}")
    data = r.json()
    return (data.get("message") or {}).get("content", "") or ""


# ─── OPENROUTER (bulut) ──────────────────────────────────────────
def _openrouter_chat_blocking(system: str, user: str, images_b64: list = None) -> str:
    import httpx
    cfg = load_config()
    key = cfg.get("openrouter_key", "")
    if not key:
        raise RuntimeError("openrouter_key yok")
    content = [{"type": "text", "text": user}]
    for b in (images_b64 or []):
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b}"}})
    payload = {
        "model": "qwen/qwen-2.5-coder-32b-instruct" if not images_b64 else "google/gemini-2.5-flash",
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": content if images_b64 else user}],
        "temperature": 0.1,
    }
    with httpx.Client(timeout=20) as c:
        r = c.post("https://openrouter.ai/api/v1/chat/completions",
                   headers={"Authorization": f"Bearer {key}"}, json=payload)
    if r.status_code != 200:
        raise RuntimeError(f"openrouter HTTP {r.status_code}: {r.text[:160]}")
    data = r.json()
    return data["choices"][0]["message"]["content"] or ""


# ─── GEMINI (bulut) ──────────────────────────────────────────────
def _gemini_chat_blocking(system: str, user: str, images_b64: list = None) -> str:
    import httpx
    cfg = load_config()
    key = cfg.get("gemini_key", "")
    if not key:
        raise RuntimeError("gemini_key yok")
    parts = [{"text": system + "\n\n" + user}]
    for b in (images_b64 or []):
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b}})
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"gemini-3.8-flash:generateContent?key={key}")
    payload = {"contents": [{"parts": parts}],
               "generationConfig": {"temperature": 0.1}}
    with httpx.Client(timeout=20) as c:
        r = c.post(url, json=payload)
    if r.status_code != 200:
        raise RuntimeError(f"gemini HTTP {r.status_code}: {r.text[:160]}")
    data = r.json()
    return data["candidates"][0]["content"]["parts"][0]["text"] or ""


# ─── BIRLESIK CAGRI (oncelik sirasi) ─────────────────────────────
async def _call_llm(system: str, user: str, images_b64: list = None, timeout: float = 20.0) -> str:
    """model_mode'a gore siirayla dener; ilk basarili yaniti doner. Hicbiri
    olmazsa '' doner (caller skip'e duser)."""
    loop = asyncio.get_event_loop()
    s = load_settings()
    mode = s.get("model_mode", "auto")

    providers = []
    if mode in ("auto", "local"):
        providers.append(("ollama", _ollama_chat_blocking))
    if mode in ("auto", "cloud"):
        providers.append(("openrouter", _openrouter_chat_blocking))
        providers.append(("gemini", _gemini_chat_blocking))

    for name, fn in providers:
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, fn, system, user, images_b64),
                timeout=timeout,
            )
        except Exception as e:
            print(f"[ADVISOR] {name} basarisiz: {e}")
            continue
    return ""


# ─── DIS API: SELF-HEALING DANISMAN ──────────────────────────────
async def ask_advisor_ai(stacktrace: str, xml_context: str, task_desc: str = "") -> dict:
    """
    2 denemeden sonra gorev hala basarisizsa cagrilir. Stack trace + XML
    baglamini modele verir, {"action": ...} doner. Model erisilemezse
    guvenli varsayilan: skip.
    """
    user = (
        f"GOREV: {task_desc}\n\n"
        f"HATA (stack trace):\n{stacktrace[:1500]}\n\n"
        f"EKRAN XML (kisaltilmis):\n{xml_context[:2500]}\n\n"
        "Bir sonraki hamle icin JSON ver."
    )
    raw = await _call_llm(_ADVISOR_SYSTEM, user, timeout=18.0)
    parsed = _extract_json(raw)
    if parsed.get("action") in ("override", "skip", "retry"):
        return parsed
    # Model konusamadi/gecersiz -> takilma, temiz atla
    return {"action": "skip", "reason": "advisor erisilemedi/gecersiz yanit"}


# ─── DIS API: GORSEL FALLBACK ────────────────────────────────────
def _compress_jpeg_blocking(png_bytes: bytes, max_w: int = 800, quality: int = 70) -> str:
    """PNG bytes -> max 800px genislik, JPEG q=70 -> base64 str."""
    from PIL import Image
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    if img.width > max_w:
        ratio = max_w / img.width
        img = img.resize((max_w, int(img.height * ratio)))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")


async def vision_locate(png_bytes: bytes, what_to_find: str) -> dict:
    """
    XML basarisiz oldugunda gorsel fallback. Ekran goruntusunu sikistirip
    modele "su elemani bul, oranini ver" der. 7s SERT zaman asimi.
    Doner: {"found":True,"x":..,"y":..} ya da {"found":False}.
    """
    if not png_bytes:
        return {"found": False}
    profile_timeout = load_settings().get("vision_timeout_s", 7.0)
    loop = asyncio.get_event_loop()
    try:
        b64 = await asyncio.wait_for(
            loop.run_in_executor(None, _compress_jpeg_blocking, png_bytes),
            timeout=3.0,
        )
    except Exception as e:
        print(f"[ADVISOR] jpeg sikistirma basarisiz: {e}")
        return {"found": False}

    user = f"Ekranda su elemani bul: {what_to_find}. Merkezinin ekran oranini JSON ver."
    try:
        raw = await asyncio.wait_for(
            _call_llm(_VISION_SYSTEM, user, images_b64=[b64], timeout=profile_timeout),
            timeout=profile_timeout,
        )
    except asyncio.TimeoutError:
        print("[ADVISOR] vision 7s zaman asimina ugradi")
        return {"found": False}
    parsed = _extract_json(raw)
    if parsed.get("found") and isinstance(parsed.get("x"), (int, float)):
        return {"found": True, "x": float(parsed["x"]), "y": float(parsed["y"])}
    return {"found": False}
