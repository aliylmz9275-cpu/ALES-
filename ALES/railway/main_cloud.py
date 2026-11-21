"""
ALES Cloud Backend

main.py'nin (masaustu) internet'e acik, PC-BAGIMSIZ alt kumesi. Ayni
frontend (App.jsx) buna da baglanir - JSON mesaj sekilleri kasten
main.py ile ayni/benzer tutuldu, boylece "ayni arayuz" hedefi saglaniyor.

CALISAN: sohbet (5 AI saglayici + otomatik fallback, multi_agent.py'daki
dayaniklilik mantigi reuse edilerek), 4-AI multi-agent tartisma, sohbet
gecmisi (conversations.py reuse), freelance uzmanlik sistem promptu.

BILEREK CALISMAYAN (PC gerektirir, bulutta imkansiz):
Fiverr/Bionluk tarayici otomasyonu, ekran gorme/analiz, yerel dosya
islemleri, yerel uygulama acma, sesli yanit (TTS su an PC hoparlorunde
CALAR, telefona akitilmiyor - v2'de eklenebilir).
Kullanici bunlardan biri istediginde sistem promptu bunu acikca soyler.

KALICILIK NOTU: Sohbet gecmisi container'in yerel diskinde saklanir
(conversations.py, config_manager uzerinden ~/ALES/conversations). Railway/
Render gibi platformlarda 'persistent volume' eklenmezse, yeniden deploy
veya restart'ta bu veri silinebilir. Ilk surum icin bilinen bir sinirlama.

ENV DEGISKENLERI (Railway/Render panelinden ayarlanir):
  ALES_ACCESS_KEY   - Telefon/tarayicidan girisi koruyan sifre. BOS
                      birakilirsa auth TAMAMEN KAPALI olur (herkes
                      erisebilir) - guclu bir deger vermen ONERILIR.
  GROQ_API_KEY, CEREBRAS_API_KEY, GEMINI_API_KEY, SAMBANOVA_API_KEY,
  OPENROUTER_API_KEY, NVIDIA_API_KEY - AI saglayicilari (hepsi opsiyonel
                      ama en az biri sart, ne kadar cogu o kadar dayanikli).
"""
import os
import sys
import re
import json
import base64
import httpx
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException, UploadFile, File, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

# ─── backend/ MODULLERINI REUSE ET ────────────────────────────────
# multi_agent.py ve conversations.py masaustu backend'i icin yazildi ama
# ikisi de zaten env-degiskeni fallback'i ile calisiyor (bkz. multi_agent.py
# _call_nvidia vb: config_manager.load_config().get(...) or os.environ.get(...)).
# Kod tekrari yerine dogrudan reuse ediyoruz.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
import multi_agent  # noqa: E402
import conversations as conv_store  # noqa: E402

# ─── AYARLAR ───────────────────────────────────────────────────────
ACCESS_KEY = os.environ.get("ALES_ACCESS_KEY", "").strip()

def has_any_api_key() -> bool:
    import config_manager as cm
    return any(bool(cm.get_key(k) or os.environ.get(env)) for k, env in (
        ("groq_key", "GROQ_API_KEY"),
        ("cerebras_key", "CEREBRAS_API_KEY"),
        ("gemini_key", "GEMINI_API_KEY"),
        ("sambanova_key", "SAMBANOVA_API_KEY"),
        ("openrouter_key", "OPENROUTER_API_KEY"),
        ("nvidia_key", "NVIDIA_API_KEY"),
    ))

DIST_DIR = Path(__file__).resolve().parent.parent / "dist"  # multi-stage Dockerfile burayi doldurur

app = FastAPI()

if not ACCESS_KEY:
    print("[ALES CLOUD] UYARI: ALES_ACCESS_KEY set edilmedi - erisim kontrolu KAPALI, "
          "herkes bu URL'i bilirse ALES'ine erisebilir.")

# ─── ERISIM KONTROLU ───────────────────────────────────────────────
def _key_ok(k: str) -> bool:
    if not ACCESS_KEY:
        return True
    return k == ACCESS_KEY

@app.get("/auth/verify")
async def auth_verify(x_ales_key: str = Header(default="")):
    if not _key_ok(x_ales_key):
        raise HTTPException(status_code=401, detail="Gecersiz erisim anahtari")
    return {"ok": True}

# ─── SISTEM PROMPTU (Genel ve Yetkin Asistan) ─────────────────────────
SYSTEM_PROMPT = """Sen ALES (Advanced Logic Execution System), Ali'nin kişisel AI asistanı ve düşünce ortağısın.
Şu an CLOUD/TELEFON modunda çalışıyorsun - Ali'nin bilgisayarında DEĞİL, internette bir sunucudasın.

GENEL ASİSTAN VE DÜŞÜNCE ORTAĞI:
- Sen çok yönlü, derin genel kültüre ve analitik yetkinliğe sahip genel bir yapay zeka asistanısın.
- Bilim, felsefe, havacılık, tarih, sanat, gündelik konular ve teknoloji dahil her soruya doğal, akıcı, kapsamlı ve samimi bir dille doğrudan yanıt ver.
- Kullanıcı açıkça istemediği sürece konuşmayı ASLA kodlamaya, web kazımaya (scraping), görev otomasyonuna veya bot işlevlerine ZORLAMA. Bir düşünce ortağı gibi sohbet et ve akıl yürüt.

BU MOD İÇİN ÖNEMLİ KISIT: Bilgisayara fiziksel erişimin YOK. Şu özellikler sadece masaüstü ALES'te çalışır:
- Masaüstü/tarayıcı otomasyonu
- Ekran görüntüsü alma/analiz etme
- Bilgisayardaki yerel dosyaları okuma/yazma
- Yerel masaüstü uygulamalarını açma
Kullanıcı bunları isterse "Bu özellik masaüstü ALES uygulamasında çalışır, bilgisayarındaki ALES'i açıp oradan deneyebilirsin" de.

YAPABİLDİKLERİN: Sohbet, genel kültür, felsefe, havacılık, bilim, analiz, stratejik tavsiye, çoklu-perspektif değerlendirme.

Türkçe konuş, kısa ve net ol. Tarih: {now}"""

# ─── TEK-TURLU SOHBET: SAĞLAYICI DÜŞEN SIRA (FALLBACK ZİNCİRİ) ────
# multi_agent.py'daki caller'lari (_call_groq, _call_gemini vb.) DOGRUDAN reuse ediyoruz.
# _call_qwen kaldirildi; dinamik getattr ile guvenli liste olusturulur.
_CANDIDATE_PROVIDERS = [
    ("Groq", getattr(multi_agent, "_call_groq", None)),
    ("Cerebras", getattr(multi_agent, "_call_cerebras", None)),
    ("Gemini", getattr(multi_agent, "_call_gemini", None)),
    ("SambaNova", getattr(multi_agent, "_call_sambanova", None)),
    ("NVIDIA", getattr(multi_agent, "_call_deepseek_v4", None)),
    ("OpenRouter", getattr(multi_agent, "_call_openrouter", None)),
]
_PROVIDER_CHAIN = [(name, caller) for name, caller in _CANDIDATE_PROVIDERS if caller is not None]

async def chat_waterfall(history: list):
    """Sohbet gecmisini alir, ilk basarili saglayicinin cevabini doner.
    (cevap_metni, hata_notu_veya_None) tuple'i doner."""
    sys_prompt = SYSTEM_PROMPT.format(now=datetime.now().strftime("%d.%m.%Y %H:%M"))
    # multi_agent'in caller'lari (prompt, system) alir - son kullanici
    # mesajini prompt olarak, gecmisi de sistem promptuna gomerek geciyoruz
    # (bu caller'lar coklu-turn history parametresi almiyor, tek prompt alir).
    convo_txt = "\n".join(f"{m['role']}: {m['content']}" for m in history[-20:])
    prompt = convo_txt
    errors = []
    for name, caller in _PROVIDER_CHAIN:
        ok, text = await caller(prompt, sys_prompt)
        if ok:
            note = f" (⚠️ {', '.join(errors)} basarisizdi, {name} ile devam edildi)" if errors else ""
            return text, (note or None)
        errors.append(f"{name}: {text}")
    return ("Su an hicbir AI saglayicisina ulasilamiyor. Sebepler:\n" + "\n".join(errors)), None

# ─── WEBSOCKET ─────────────────────────────────────────────────────
@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    key = websocket.query_params.get("key", "")
    await websocket.accept()
    if not _key_ok(key):
        await websocket.close(code=4001)
        return

    await websocket.send_json({
        "type": "connected",
        "content": "🌐 ALES Cloud'a hosgeldin! Sohbet ve 4-AI analiz hazir. "
                    "(Tarayici otomasyonu/ekran gorme icin bilgisayarindaki ALES'i kullan.)",
        "setup_needed": False,
    })

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") != "message":
                continue
            text = (data.get("content") or "").strip()
            if not text:
                continue

            conv_id = data.get("conversation_id")
            if not conv_id:
                conv = conv_store.create_conversation(text)
                conv_id = conv["id"]
                await websocket.send_json({"type": "conversation_created", "id": conv_id})

            conv_store.append_message(conv_id, "user", text)
            history = conv_store.get_history_for_model(conv_id, limit=20)

            if not has_any_api_key():
                await websocket.send_json({"type": "error", "content": "❌ Sunucuda hic AI API key tanimli degil (Ayarlar sekmesinden veya Render ortam degiskenlerinden ekleyin)."})
                continue

            if re.search(r"derin analiz|tartis|4 ?ai", text, re.IGNORECASE):
                await websocket.send_json({"type": "tool_use", "tool": "multi_agent", "content": "4 AI tartisiyor..."})
                reply = await multi_agent.run_multi_agent_discussion(text)
            else:
                reply, note = await chat_waterfall(history)
                if note:
                    reply += "\n\n" + note

            conv_store.append_message(conv_id, "assistant", reply)
            await websocket.send_json({"type": "message", "content": reply})
    except WebSocketDisconnect:
        pass

# ─── HTTP: DURUM / SAGLIK KONTROLU (auth YOK - platform healthcheck icin) ──
@app.get("/status")
async def status():
    import config_manager as cm
    return {
        "status": "online",
        "mode": "cloud",
        "has_groq": bool(cm.get_key("groq_key") or os.environ.get("GROQ_API_KEY")),
        "has_cerebras": bool(cm.get_key("cerebras_key") or os.environ.get("CEREBRAS_API_KEY")),
        "has_gemini": bool(cm.get_key("gemini_key") or os.environ.get("GEMINI_API_KEY")),
        "has_sambanova": bool(cm.get_key("sambanova_key") or os.environ.get("SAMBANOVA_API_KEY")),
        "has_openrouter": bool(cm.get_key("openrouter_key") or os.environ.get("OPENROUTER_API_KEY")),
        "has_nvidia": bool(cm.get_key("nvidia_key") or os.environ.get("NVIDIA_API_KEY")),
        "auth_enabled": bool(ACCESS_KEY),
        "time": datetime.now().isoformat(),
    }

# ─── HTTP: KONFİGÜRASYON (GET /config & POST /config) ─────────────
@app.get("/config")
async def get_config(x_ales_key: str = Header(default="")):
    if not _key_ok(x_ales_key):
        raise HTTPException(status_code=401)
    import config_manager as cm
    cfg = cm.load_config()
    mode_cfg = cm.get_mode_config()
    return {
        "has_groq": bool(cm.get_key("groq_key") or os.environ.get("GROQ_API_KEY")),
        "has_cerebras": bool(cm.get_key("cerebras_key") or os.environ.get("CEREBRAS_API_KEY")),
        "has_elevenlabs": bool(cm.get_key("elevenlabs_key") or os.environ.get("ELEVENLABS_API_KEY")),
        "has_gemini": bool(cm.get_key("gemini_key") or os.environ.get("GEMINI_API_KEY")),
        "has_sambanova": bool(cm.get_key("sambanova_key") or os.environ.get("SAMBANOVA_API_KEY")),
        "has_openrouter": bool(cm.get_key("openrouter_key") or os.environ.get("OPENROUTER_API_KEY")),
        "has_nvidia": bool(cm.get_key("nvidia_key") or os.environ.get("NVIDIA_API_KEY")),
        "elevenlabs_voice": cfg.get("elevenlabs_voice") or "eleven_monolingual_v1",
        "edge_voice": cfg.get("edge_voice") or "tr-TR-AhmetNeural",
        "mode": cm.get_mode(),
        "timeouts": mode_cfg.get("timeouts", {}),
        "cloud_readonly": False,
    }

@app.post("/config")
async def set_config(data: dict, x_ales_key: str = Header(default="")):
    if not _key_ok(x_ales_key):
        raise HTTPException(status_code=401)
    import config_manager as cm
    cfg = cm.load_config()
    
    env_map = {
        "groq_key": "GROQ_API_KEY",
        "cerebras_key": "CEREBRAS_API_KEY",
        "elevenlabs_key": "ELEVENLABS_API_KEY",
        "gemini_key": "GEMINI_API_KEY",
        "sambanova_key": "SAMBANOVA_API_KEY",
        "openrouter_key": "OPENROUTER_API_KEY",
        "nvidia_key": "NVIDIA_API_KEY",
    }
    
    for key in ["groq_key", "cerebras_key", "elevenlabs_key", "elevenlabs_voice", "edge_voice",
                "gemini_key", "sambanova_key", "openrouter_key", "nvidia_key"]:
        if key in data:
            val = data[key]
            if val is not None and str(val).strip() != "":
                clean_val = str(val).strip()
                cfg[key] = clean_val
                if key in env_map:
                    os.environ[env_map[key]] = clean_val
            elif data.get(f"clear_{key}") is True or val == "__CLEAR__":
                cfg[key] = ""
                if key in env_map and env_map[key] in os.environ:
                    del os.environ[env_map[key]]
                    
    if isinstance(data.get("timeouts"), dict):
        cur = dict(cfg.get("timeouts") or {})
        for k, v in data["timeouts"].items():
            try: cur[k] = float(v)
            except Exception: pass
        cfg["timeouts"] = cur
        
    cm.save_config(cfg)
    
    if data.get("mode"):
        try:
            cm.set_mode(data["mode"])
        except ValueError as e:
            return {"success": True, "mode_error": str(e)}
            
    return {"success": True}

# ─── HTTP: MOD SİSTEMİ (GET /modes & POST /mode) ─────────────────
@app.get("/modes")
async def get_modes():
    import config_manager as cm
    active = cm.get_mode_config()
    return {
        "modes": cm.list_modes(),
        "active": active["mode"],
        "active_chain": [{"layer": l["layer"], "provider": l.get("provider"),
                          "model": l.get("model")} for l in active["chain"]],
        "providers": ["groq", "cerebras", "gemini", "sambanova", "nvidia", "openrouter"],
        "timeouts": active.get("timeouts", {}),
    }

@app.post("/mode")
async def post_mode(data: dict):
    import config_manager as cm
    try:
        m = cm.set_mode(data.get("mode", ""))
    except ValueError as e:
        return {"ok": False, "error": str(e), "modes": [x["id"] for x in cm.list_modes()]}
    return {"ok": True, "mode": m, "active_chain":
            [{"layer": l["layer"], "provider": l.get("provider"), "model": l.get("model")}
             for l in cm.get_mode_config(m)["chain"]]}

# ─── HTTP: MODELLER (GET /models) ─────────────────────────────────
@app.get("/models")
async def models_list():
    import config_manager as cm
    return {
        "layers": cm.list_model_layers(),
        "mode": cm.get_mode(),
        "heavy_available": cm.heavy_available(),
        "providers": ["groq", "cerebras", "gemini", "sambanova", "nvidia", "openrouter"],
        "credential_problems": cm.credential_problems(),
    }

# ─── HTTP: MECLİS & BIG ALES DESTEKLEYİCİ ROTALAR ──────────────────
@app.get("/council")
async def council_get():
    return {"config": {"enabled": False}, "strategies": []}

@app.get("/big-ales")
async def big_ales_get():
    return {"available": False, "session": {"signed_in": False}}

# ─── HTTP: API TEST VE PING KONTROLÜ ──────────────────────────────
@app.post("/test-key")
async def test_key_route(data: dict):
    provider = (data.get("provider") or "groq").lower().strip()
    key = (data.get("key") or "").strip()
    if not key:
        return {"ok": False, "error": "API Key boş olamaz."}
    try:
        if provider == "groq":
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {key}"}
                )
                if resp.status_code == 200:
                    return {"ok": True, "provider": "groq"}
                else:
                    return {"ok": False, "error": f"Groq Doğrulama Hatası ({resp.status_code}): {resp.text}"}
        elif provider == "gemini":
            from google import genai
            client = genai.Client(api_key=key)
            client.models.list()
            return {"ok": True, "provider": "gemini"}
        else:
            return {"ok": False, "error": f"Bilinmeyen sağlayıcı: {provider}"}
    except Exception as e:
        return {"ok": False, "error": f"Bağlantı Hatası: {e}"}

# ─── HTTP: SİSTEM VE MODÜL CANLI DURUMU (DURUM PANELİ İÇİN) ───────
@app.get("/api/system/status")
async def get_real_system_status():
    import config_manager as cm
    cfg = cm.load_config()
    caps = {}

    active_keys = []
    for prov, k in (("Groq", "groq_key"), ("Gemini", "gemini_key"), ("Cerebras", "cerebras_key"),
                    ("NVIDIA", "nvidia_key"), ("OpenRouter", "openrouter_key"), ("SambaNova", "sambanova_key")):
        if cm.get_key(k) or os.environ.get(f"{prov.upper()}_API_KEY"):
            active_keys.append(prov)
    
    if active_keys:
        caps["api_models"] = {
            "status": "working",
            "label": "Model Sağlayıcıları & API (Cloud)",
            "details": f"Aktif Anahtarlar: {', '.join(active_keys)} (Bulut Fallback Zinciri Hazır)"
        }
    else:
        caps["api_models"] = {
            "status": "failed",
            "label": "Model Sağlayıcıları & API",
            "details": "Hiçbir API anahtarı tanımlanmamış. ALES yanıt veremez; Ayarlar'dan anahtar ekleyin."
        }

    caps["cloud_mode"] = {
        "status": "working",
        "label": "Cloud / Web / Mobil Motoru",
        "details": "FastAPI + WebSocket Bulut Sunucusu devrede. Masaüstü/ekran erişimi sadece yerel EXE'de çalışır."
    }

    try:
        import manager_agent
        caps["manager_agent"] = {
            "status": "working",
            "label": "Manager-Executor Mimarisi",
            "details": "Manager Agent devrede, adımlı hedef ve planlama yapabilir."
        }
    except Exception as e_ma:
        caps["manager_agent"] = {
            "status": "beta",
            "label": "Manager-Executor Mimarisi",
            "details": f"Yedek: {e_ma}"
        }

    return {"ok": True, "capabilities": caps}


@app.post("/api/transcribe")
@app.post("/transcribe")
async def transcribe_audio_api(request: Request, file: UploadFile = File(None)):
    """Ses kaydını metne dönüştürür (Groq Whisper API)."""
    import config_manager as cm
    audio_bytes = None
    filename = "audio.webm"
    content_type = "audio/webm"

    if file is not None:
        try:
            audio_bytes = await file.read()
            filename = file.filename or "audio.webm"
            content_type = file.content_type or "audio/webm"
        except Exception:
            pass

    if not audio_bytes:
        try:
            body = await request.json()
            if "audio_base64" in body:
                raw_b64 = body["audio_base64"]
                if "," in raw_b64:
                    raw_b64 = raw_b64.split(",", 1)[1]
                audio_bytes = base64.b64decode(raw_b64)
        except Exception:
            pass

    if not audio_bytes:
        return {"ok": False, "error": "Ses verisi alınamadı", "text": ""}

    groq_key = cm.get_key("groq_key") or os.environ.get("GROQ_API_KEY")
    if not groq_key:
        return {"ok": False, "error": "GROQ_API_KEY bulunamadı", "text": ""}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            files = {"file": (filename, audio_bytes, content_type)}
            data = {"model": "whisper-large-v3-turbo", "language": "tr", "response_format": "json"}
            resp = await client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {groq_key}"},
                files=files,
                data=data
            )
            if resp.status_code == 200:
                result = resp.json()
                return {"ok": True, "text": result.get("text", "").strip()}
            else:
                return {"ok": False, "error": f"Groq Whisper hatası ({resp.status_code})", "text": ""}
    except Exception as e:
        return {"ok": False, "error": f"Transkripsiyon hatası: {str(e)}", "text": ""}

# ─── HTTP: SOHBET GECMISI (conversations.py DOGRUDAN reuse) ───────
@app.get("/conversations")
async def list_conversations(x_ales_key: str = Header(default="")):
    if not _key_ok(x_ales_key):
        raise HTTPException(status_code=401)
    return {"conversations": conv_store.list_conversations()}

@app.post("/conversations")
async def new_conversation(x_ales_key: str = Header(default="")):
    if not _key_ok(x_ales_key):
        raise HTTPException(status_code=401)
    return conv_store.create_conversation()

@app.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str, x_ales_key: str = Header(default="")):
    if not _key_ok(x_ales_key):
        raise HTTPException(status_code=401)
    conv = conv_store.get_conversation(conv_id)
    if not conv:
        return JSONResponse({"error": "Sohbet bulunamadi"}, status_code=404)
    return conv

@app.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str, x_ales_key: str = Header(default="")):
    if not _key_ok(x_ales_key):
        raise HTTPException(status_code=401)
    return {"success": conv_store.delete_conversation(conv_id)}

@app.patch("/conversations/{conv_id}")
async def rename_conversation(conv_id: str, data: dict, x_ales_key: str = Header(default="")):
    if not _key_ok(x_ales_key):
        raise HTTPException(status_code=401)
    return {"success": conv_store.rename_conversation(conv_id, data.get("title", ""))}

# ─── HTTP: ONAYLAR / SES (cloud'da devre disi - frontend'in polling'i
# hata almasin diye no-op donuyor) ─────────────────────────────────
@app.get("/approvals")
async def approvals_stub():
    return {"approvals": []}

@app.get("/voices")
async def voices_stub():
    return {"voices": [], "current": None, "note": "TTS cloud modunda henuz desteklenmiyor."}

# ─── FRONTEND'I STATIK DOSYA OLARAK SUN (ayni deployment'tan tek URL) ──
if DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="static")
else:
    @app.get("/")
    async def no_frontend():
        return JSONResponse(
            {"error": "Frontend build bulunamadi. Dockerfile.cloud frontend'i build edip "
                      "dist/ klasorune kopyalamis olmali - build loglarini kontrol et."},
            status_code=500,
        )

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"[ALES CLOUD] Starting server on 0.0.0.0:{port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
