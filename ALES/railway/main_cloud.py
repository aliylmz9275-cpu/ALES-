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
import asyncio
import httpx
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException, UploadFile, File, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse

# ─── DIZINLERI BELIRLE VE BACKEND'I sys.path'e EKLE ───────────────
BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"
if not BACKEND_DIR.exists():
    for _b in [Path("/app/backend"), Path("backend"), Path("ALES/backend")]:
        if _b.exists():
            BACKEND_DIR = _b
            break

sys.path.insert(0, str(BACKEND_DIR))
import multi_agent  # noqa: E402
import conversations as conv_store  # noqa: E402

try:
    import voice
except Exception as _e:
    voice = None

try:
    import telemetry
except Exception as _e:
    telemetry = None

try:
    import document_generator
except Exception as _e:
    document_generator = None

try:
    import profile_manager
except Exception as _e:
    profile_manager = None

try:
    import plan_manager
except Exception as _e:
    plan_manager = None

try:
    import model_registry
    import auto_model_discovery
except Exception as _e:
    model_registry = None
    auto_model_discovery = None

# In-memory persistent session key store (cloud ephemeral container memory)
_SESSION_KEYS: dict[str, str] = {}

# ─── AYARLAR ───────────────────────────────────────────────────────
ACCESS_KEY = os.environ.get("ALES_ACCESS_KEY", "").strip()

def has_any_api_key() -> bool:
    import config_manager as cm
    return any(bool(_SESSION_KEYS.get(k) or cm.get_key(k) or os.environ.get(env)) for k, env in (
        ("groq_key", "GROQ_API_KEY"),
        ("cerebras_key", "CEREBRAS_API_KEY"),
        ("gemini_key", "GEMINI_API_KEY"),
        ("sambanova_key", "SAMBANOVA_API_KEY"),
        ("openrouter_key", "OPENROUTER_API_KEY"),
        ("nvidia_key", "NVIDIA_API_KEY"),
        ("openai_key", "OPENAI_API_KEY"),
    ))

DIST_DIR = BASE_DIR / "dist"
for _d in [BASE_DIR / "dist", Path("/app/dist"), Path("dist"), Path("ALES/dist"), BASE_DIR / "frontend" / "dist"]:
    if _d.exists() and (_d / "index.html").exists():
        DIST_DIR = _d
        break

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    if model_registry and hasattr(model_registry, "registry"):
        try:
            asyncio.create_task(model_registry.registry.scheduler.run())
            print("[ALES CLOUD] Model registry scheduler devrede.")
        except Exception as e:
            print(f"[ALES CLOUD] Model registry scheduler error: {e}")
    if auto_model_discovery:
        try:
            auto_model_discovery.start_discovery_loop()
            print("[ALES CLOUD] Auto model discovery loop devrede.")
        except Exception as e:
            print(f"[ALES CLOUD] Auto model discovery loop error: {e}")

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

# ─── SISTEM PROMPTU (CLAUDE CODE STANDARD - CRISP) ───────────────────
SYSTEM_PROMPT = """You are ALES, a Claude Code clone. Keep responses extremely brief. DO NOT explain how to do a task. Use your tools to do it directly.

RULES:
1. EXECUTE, NEVER EXPLAIN. If you have a tool, CALL IT. Never write tutorial code.
2. BE EXTREMELY BRIEF: Short, direct answers. No essays, no filler. Max 1-2 paragraphs.
3. TOOLS: read_file, write_file, str_replace_editor, run_terminal_command, search_web, generate_pdf.
4. WORKFLOW: Read -> Act -> Observe -> Verify. Pragmatic, no fluff.
5. LANGUAGE: Respond in the user's language (Turkish if Turkish, English if English).

Tarih: {now}"""

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

async def chat_waterfall(history: list, pdf_intent: bool = False):
    """Sohbet gecmisini alir, ilk basarili saglayicinin cevabini doner.
    (cevap_metni, hata_notu_veya_None) tuple'i doner."""
    sys_prompt = SYSTEM_PROMPT.format(now=datetime.now().strftime("%d.%m.%Y %H:%M"))
    if pdf_intent:
        sys_prompt += (
            "\n\n[KRİTİK TALİMAT - PDF & RAPOR MODU]: Kullanıcı bir PDF raporu/belgesi talep etti. "
            "Bu konuyla ilgili eksiksiz, profesyonel, zengin ve detaylı bir rapor içeriği üret. "
            "Başlıkları (#, ##), alt maddeleri, özet ve sonuç bölümlerini temiz Markdown formatında yapılandır. "
            "ASLA 'Python ile yapabilirsiniz' veya kod örneği verme. DOĞRUDAN raporun kendisini yaz!"
        )
    # multi_agent'in caller'lari (prompt, system) alir - son kullanici
    # mesajini prompt olarak, gecmisi de sistem promptuna gomerek geciyoruz
    # (bu caller'lar coklu-turn history parametresi almiyor, tek prompt alir).
    convo_txt = "\n".join(f"{m['role']}: {m['content']}" for m in history[-20:])
    prompt = convo_txt
    errors = []
    for name, caller in _PROVIDER_CHAIN:
        ok, text = await caller(prompt, sys_prompt)
        if telemetry:
            try:
                telemetry.record_api_call(name, ok)
            except Exception:
                pass
        if ok:
            note = f" (⚠️ {', '.join(errors)} basarisizdi, {name} ile devam edildi)" if errors else ""
            return text, (note or None)
        errors.append(f"{name}: {text}")
    return ("Su an hicbir AI saglayicisina ulasilamiyor. Sebepler:\n" + "\n".join(errors)), None


async def send_cloud_tts_audio(text: str, websocket: WebSocket):
    """Bulut ve mobil istemciye WebSocket üzerinden ses gönderir (ChatGPT/ElevenLabs/Edge-TTS)."""
    try:
        import voice
        import config_manager as cm
        cfg = cm.load_config()
        openai_key = (
            _SESSION_KEYS.get("openai_key")
            or cfg.get("openai_key")
            or cm.get_key("openai_key")
            or os.environ.get("OPENAI_API_KEY", "")
        )
        eleven_key = (
            _SESSION_KEYS.get("elevenlabs_key")
            or cfg.get("elevenlabs_key")
            or cm.get_key("elevenlabs_key")
            or os.environ.get("ELEVENLABS_API_KEY", "")
            or os.environ.get("ELEVENLABS_KEY", "")
        )
        voice_id = cfg.get("tts_voice") or cfg.get("openai_voice") or cfg.get("elevenlabs_voice") or getattr(voice, "DEFAULT_OPENAI_VOICE", "alloy")
        edge_voice = cfg.get("edge_voice") or getattr(voice, "DEFAULT_EDGE_VOICE", "tr-TR-AhmetNeural")

        clean = voice._clean_for_speech(text) if hasattr(voice, "_clean_for_speech") else text
        if not clean or not clean.strip():
            return

        loop = asyncio.get_event_loop()
        audio_bytes = await loop.run_in_executor(
            None,
            voice.synthesize,
            clean,
            eleven_key,
            voice_id,
            edge_voice,
            openai_key,
            voice_id
        )
        if audio_bytes:
            mime = "audio/wav" if audio_bytes.startswith(b"RIFF") else "audio/mpeg"
            b64 = base64.b64encode(audio_bytes).decode("ascii")
            await websocket.send_json({"type": "audio", "data": b64, "mime": mime})
    except Exception as e:
        print(f"[CLOUD TTS] Ses gönderim hatası: {e}")

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
            if data.get("type") == "sync_session":
                keys = data.get("keys") or {}
                import config_manager as cm
                cfg = cm.load_config()
                env_map = {
                    "groq_key": "GROQ_API_KEY",
                    "cerebras_key": "CEREBRAS_API_KEY",
                    "openai_key": "OPENAI_API_KEY",
                    "elevenlabs_key": "ELEVENLABS_API_KEY",
                    "gemini_key": "GEMINI_API_KEY",
                    "sambanova_key": "SAMBANOVA_API_KEY",
                    "openrouter_key": "OPENROUTER_API_KEY",
                    "nvidia_key": "NVIDIA_API_KEY",
                }
                for k, v in keys.items():
                    if isinstance(v, str) and v.strip():
                        clean_v = v.strip()
                        _SESSION_KEYS[k] = clean_v
                        cfg[k] = clean_v
                        if k in env_map:
                            os.environ[env_map[k]] = clean_v
                cm.save_config(cfg)
                if data.get("mode"):
                    try:
                        cm.set_mode(data["mode"])
                    except Exception:
                        pass
                await websocket.send_json({"type": "session_synced", "ok": True})
                continue

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

            _pdf_intent = bool(re.search(
                r"\b(pdf|rapor|doküman|dokuman|belge)\b.*\b(yap|oluştur|olustur|hazırla|hazirla|üret|uret|indir|çıkart|cıkart|yaz|kaydet|generate|create|aktar|çıkar|cikar)\b|"
                r"\b(yap|oluştur|olustur|hazırla|hazirla|üret|uret|indir|çıkart|cıkart|yaz|kaydet|generate|create|aktar|çıkar|cikar)\b.*\b(pdf|rapor|doküman|dokuman|belge)\b",
                text, re.IGNORECASE
            ))

            if re.search(r"derin analiz|tartis|4 ?ai", text, re.IGNORECASE):
                await websocket.send_json({"type": "tool_use", "tool": "multi_agent", "content": "4 AI tartisiyor..."})
                reply = await multi_agent.run_multi_agent_discussion(text)
            elif _pdf_intent:
                await websocket.send_json({
                    "type": "tool_use",
                    "tool": "generate_pdf",
                    "content": "📄 Belge içeriği hazırlanıyor ve PDF oluşturuluyor..."
                })
                reply, note = await chat_waterfall(history, pdf_intent=True)
                if note:
                    reply += "\n\n" + note
                if document_generator:
                    try:
                        pdf_title = "ALES_Raporu"
                        for line in reply.strip().split("\n"):
                            clean_l = re.sub(r"^[#\*\-\s]+", "", line).strip()
                            if 3 < len(clean_l) < 60:
                                pdf_title = clean_l
                                break
                        gen_res = document_generator.generate_pdf(pdf_title, reply)
                        if gen_res.get("ok"):
                            dl_url = gen_res.get("url", "")
                            fname = gen_res.get("filename", "belge.pdf")
                            await websocket.send_json({
                                "type": "tool_result",
                                "tool": "generate_pdf",
                                "result": f"✅ PDF başarıyla oluşturuldu: {fname}"
                            })
                            reply += f"\n\n---\n### 📄 Belgeniz Hazır\n**Dosya:** [{fname}]({dl_url})\n\n[⬇️ PDF'yi İndir]({dl_url})"
                        else:
                            await websocket.send_json({
                                "type": "tool_result",
                                "tool": "generate_pdf",
                                "result": f"⚠️ PDF oluşturma uyarısı: {gen_res.get('error')}"
                            })
                    except Exception as e_pdf:
                        print(f"[CLOUD PDF] Üretim hatası: {e_pdf}")
            else:
                reply, note = await chat_waterfall(history)
                if note:
                    reply += "\n\n" + note

            conv_store.append_message(conv_id, "assistant", reply)
            await websocket.send_json({"type": "message", "content": reply})

            # Sesli yanıtı WebSocket üzerinden gönder (ChatGPT / ElevenLabs / Edge-TTS)
            asyncio.create_task(send_cloud_tts_audio(reply, websocket))
    except WebSocketDisconnect:
        pass

# ─── HTTP: DURUM / SAGLIK KONTROLU (auth YOK - platform healthcheck icin) ──
@app.get("/status")
async def status():
    import config_manager as cm
    return {
        "status": "online",
        "mode": "cloud",
        "has_groq": bool(_SESSION_KEYS.get("groq_key") or cm.get_key("groq_key") or os.environ.get("GROQ_API_KEY")),
        "has_cerebras": bool(_SESSION_KEYS.get("cerebras_key") or cm.get_key("cerebras_key") or os.environ.get("CEREBRAS_API_KEY")),
        "has_openai": bool(_SESSION_KEYS.get("openai_key") or cm.get_key("openai_key") or os.environ.get("OPENAI_API_KEY")),
        "has_gemini": bool(_SESSION_KEYS.get("gemini_key") or cm.get_key("gemini_key") or os.environ.get("GEMINI_API_KEY")),
        "has_sambanova": bool(_SESSION_KEYS.get("sambanova_key") or cm.get_key("sambanova_key") or os.environ.get("SAMBANOVA_API_KEY")),
        "has_openrouter": bool(_SESSION_KEYS.get("openrouter_key") or cm.get_key("openrouter_key") or os.environ.get("OPENROUTER_API_KEY")),
        "has_nvidia": bool(_SESSION_KEYS.get("nvidia_key") or cm.get_key("nvidia_key") or os.environ.get("NVIDIA_API_KEY")),
        "auth_enabled": bool(ACCESS_KEY),
        "time": datetime.now().isoformat(),
    }

# ─── HTTP: SESSION SYNC (Cloud/Mobil için Anahtar ve Mod Kalıcılığı) ────
@app.post("/api/session/sync")
@app.post("/session/sync")
async def api_session_sync(data: dict):
    """Frontend localStorage'dan gelen anahtarları ve modu oturum belleğine al."""
    global _SESSION_KEYS
    try:
        keys = data.get("keys") or data
        import config_manager as cm
        cfg = cm.load_config()
        env_map = {
            "groq_key": "GROQ_API_KEY",
            "cerebras_key": "CEREBRAS_API_KEY",
            "openai_key": "OPENAI_API_KEY",
            "elevenlabs_key": "ELEVENLABS_API_KEY",
            "gemini_key": "GEMINI_API_KEY",
            "sambanova_key": "SAMBANOVA_API_KEY",
            "openrouter_key": "OPENROUTER_API_KEY",
            "nvidia_key": "NVIDIA_API_KEY",
        }
        for k, v in keys.items():
            if isinstance(v, str) and v.strip():
                clean_v = v.strip()
                _SESSION_KEYS[k] = clean_v
                cfg[k] = clean_v
                if k in env_map:
                    os.environ[env_map[k]] = clean_v
        cm.save_config(cfg)
        mode = data.get("mode")
        if mode:
            try:
                cm.set_mode(mode)
            except Exception:
                pass
        return {"ok": True, "message": "Oturum senkronize edildi", "keys_received": list(keys.keys())}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ─── HTTP: KONFİGÜRASYON (GET /config & POST /config) ─────────────
@app.get("/config")
async def get_config(x_ales_key: str = Header(default="")):
    if not _key_ok(x_ales_key):
        raise HTTPException(status_code=401)
    import config_manager as cm
    cfg = cm.load_config()
    mode_cfg = cm.get_mode_config()
    return {
        "has_groq": bool(_SESSION_KEYS.get("groq_key") or cm.get_key("groq_key") or os.environ.get("GROQ_API_KEY")),
        "has_cerebras": bool(_SESSION_KEYS.get("cerebras_key") or cm.get_key("cerebras_key") or os.environ.get("CEREBRAS_API_KEY")),
        "has_openai": bool(_SESSION_KEYS.get("openai_key") or cm.get_key("openai_key") or os.environ.get("OPENAI_API_KEY")),
        "has_elevenlabs": bool(_SESSION_KEYS.get("elevenlabs_key") or cm.get_key("elevenlabs_key") or os.environ.get("ELEVENLABS_API_KEY")),
        "has_gemini": bool(_SESSION_KEYS.get("gemini_key") or cm.get_key("gemini_key") or os.environ.get("GEMINI_API_KEY")),
        "has_sambanova": bool(_SESSION_KEYS.get("sambanova_key") or cm.get_key("sambanova_key") or os.environ.get("SAMBANOVA_API_KEY")),
        "has_openrouter": bool(_SESSION_KEYS.get("openrouter_key") or cm.get_key("openrouter_key") or os.environ.get("OPENROUTER_API_KEY")),
        "has_nvidia": bool(_SESSION_KEYS.get("nvidia_key") or cm.get_key("nvidia_key") or os.environ.get("NVIDIA_API_KEY")),
        "openai_voice": cfg.get("openai_voice") or "alloy",
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
        "openai_key": "OPENAI_API_KEY",
        "elevenlabs_key": "ELEVENLABS_API_KEY",
        "gemini_key": "GEMINI_API_KEY",
        "sambanova_key": "SAMBANOVA_API_KEY",
        "openrouter_key": "OPENROUTER_API_KEY",
        "nvidia_key": "NVIDIA_API_KEY",
    }
    
    for key in ["groq_key", "cerebras_key", "openai_key", "elevenlabs_key", "openai_voice", "elevenlabs_voice", "edge_voice",
                "gemini_key", "sambanova_key", "openrouter_key", "nvidia_key"]:
        if key in data:
            val = data[key]
            if val is not None and str(val).strip() != "":
                clean_val = str(val).strip()
                _SESSION_KEYS[key] = clean_val
                cfg[key] = clean_val
                if key in env_map:
                    os.environ[env_map[key]] = clean_val
            elif data.get(f"clear_{key}") is True or val == "__CLEAR__":
                _SESSION_KEYS.pop(key, None)
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

@app.post("/api/models/refresh")
@app.get("/api/models/refresh")
@app.post("/model-discovery/refresh")
async def api_models_refresh():
    """Manuel ve UI tetiklemeli model keşfi ve otomatik onarım."""
    try:
        res = {}
        if auto_model_discovery is not None:
            res = await auto_model_discovery.run_discovery_now()
        elif model_registry is not None:
            res = await model_registry.refresh_all_providers(force=True)
        return {"ok": True, "result": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}

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
        elif provider == "openai":
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {key}"}
                )
                if resp.status_code == 200:
                    return {"ok": True, "provider": "openai"}
                else:
                    return {"ok": False, "error": f"OpenAI Doğrulama Hatası ({resp.status_code}): {resp.text}"}
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
async def transcribe_audio_api(request: Request):
    """Ses kaydını metne dönüştürür (Groq Whisper API)."""
    import config_manager as cm
    audio_bytes = None
    filename = "audio.webm"
    content_type = "audio/webm"

    content_type_header = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type_header:
        try:
            form = await request.form()
            file = form.get("file")
            if file and hasattr(file, "read"):
                audio_bytes = await file.read()
                filename = getattr(file, "filename", "audio.webm")
                content_type = getattr(file, "content_type", "audio/webm")
        except Exception as e:
            print(f"[TRANSCRIBE] Form okuma hatası: {e}")

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

# ─── HTTP: ONAYLAR / SES ──────────────────────────────────────────
@app.get("/approvals")
async def approvals_stub():
    return {"approvals": []}

@app.get("/voices")
async def voices_endpoint():
    """Seçilebilir sesler - Ayarlar'daki ses dropdown'u için (ChatGPT, ElevenLabs, Edge-TTS)."""
    import config_manager as cm
    cfg = cm.load_config()
    openai_voices = []
    eleven_voices = []
    edge_voices = []
    default_openai = "alloy"
    default_edge = "tr-TR-AhmetNeural"
    try:
        import voice
        openai_voices = getattr(voice, "OPENAI_VOICES", [])
        eleven_voices = getattr(voice, "ELEVENLABS_VOICES", [])
        edge_voices = getattr(voice, "EDGE_VOICES", [])
        default_openai = getattr(voice, "DEFAULT_OPENAI_VOICE", "alloy")
        default_edge = getattr(voice, "DEFAULT_EDGE_VOICE", "tr-TR-AhmetNeural")
    except Exception:
        pass
    all_voices = openai_voices + eleven_voices
    return {
        "voices": all_voices,
        "openai_voices": openai_voices,
        "current": cfg.get("tts_voice") or cfg.get("openai_voice") or cfg.get("elevenlabs_voice") or default_openai,
        "has_openai_key": bool(_SESSION_KEYS.get("openai_key") or cfg.get("openai_key") or cm.get_key("openai_key") or os.environ.get("OPENAI_API_KEY")),
        "has_elevenlabs_key": bool(_SESSION_KEYS.get("elevenlabs_key") or cfg.get("elevenlabs_key") or cm.get_key("elevenlabs_key") or os.environ.get("ELEVENLABS_API_KEY")),
        "edge_voices": edge_voices,
        "current_edge_voice": cfg.get("edge_voice") or default_edge,
    }

@app.post("/speak")
@app.post("/speak_test")
async def cloud_speak_api(payload: dict):
    """Bulut ve web kullanıcıları için metni sese çevirir (ChatGPT / ElevenLabs / Edge-TTS)."""
    text = (payload.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "Metin boş"}
    try:
        import voice
        import config_manager as cm
        cfg = cm.load_config()
        openai_key = (
            payload.get("openai_key")
            or _SESSION_KEYS.get("openai_key")
            or cfg.get("openai_key")
            or cm.get_key("openai_key")
            or os.environ.get("OPENAI_API_KEY", "")
        )
        eleven_key = (
            payload.get("elevenlabs_key")
            or _SESSION_KEYS.get("elevenlabs_key")
            or cfg.get("elevenlabs_key")
            or cm.get_key("elevenlabs_key")
            or os.environ.get("ELEVENLABS_API_KEY", "")
            or os.environ.get("ELEVENLABS_KEY", "")
        )
        voice_id = payload.get("voice_id") or cfg.get("tts_voice") or cfg.get("openai_voice") or cfg.get("elevenlabs_voice") or getattr(voice, "DEFAULT_OPENAI_VOICE", "alloy")
        edge_voice = payload.get("edge_voice") or cfg.get("edge_voice") or getattr(voice, "DEFAULT_EDGE_VOICE", "tr-TR-AhmetNeural")

        loop = asyncio.get_event_loop()
        clean = voice._clean_for_speech(text) if hasattr(voice, "_clean_for_speech") else text
        audio_bytes = await loop.run_in_executor(
            None,
            voice.synthesize,
            clean,
            eleven_key,
            voice_id,
            edge_voice,
            openai_key,
            voice_id
        )
        if audio_bytes:
            mime = "audio/wav" if audio_bytes.startswith(b"RIFF") else "audio/mpeg"
            b64 = base64.b64encode(audio_bytes).decode("ascii")
            return {"ok": True, "audio": b64, "mime": mime}
        return {"ok": False, "error": "Ses üretilemedi"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ─── PROFİL & KALICI API ANAHTARI YÖNETİMİ (SQLite) ───────────────
@app.post("/api/profile/save")
async def cloud_profile_save_api(data: dict):
    if not profile_manager:
        return {"ok": False, "error": "profile_manager modülü aktif değil"}
    try:
        code = (data.get("access_code") or "").strip()
        name = (data.get("name") or "").strip()
        keys = data.get("keys") or data
        res = profile_manager.save_profile(code, name, keys)
        if res.get("ok"):
            import config_manager as cm
            cfg = cm.load_config()
            env_map = {
                "groq_key": "GROQ_API_KEY",
                "cerebras_key": "CEREBRAS_API_KEY",
                "openai_key": "OPENAI_API_KEY",
                "elevenlabs_key": "ELEVENLABS_API_KEY",
                "gemini_key": "GEMINI_API_KEY",
                "sambanova_key": "SAMBANOVA_API_KEY",
                "openrouter_key": "OPENROUTER_API_KEY",
                "nvidia_key": "NVIDIA_API_KEY",
            }
            for k, env in env_map.items():
                val = keys.get(k) or keys.get(k.replace("_key", ""))
                if val and str(val).strip():
                    clean_val = str(val).strip()
                    _SESSION_KEYS[k] = clean_val
                    cfg[k] = clean_val
                    os.environ[env] = clean_val
            cm.save_config(cfg)
        return res
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/api/profile/load")
@app.get("/api/profile/load")
async def cloud_profile_load_api(request: Request):
    if not profile_manager:
        return {"ok": False, "error": "profile_manager modülü aktif değil"}
    try:
        code = ""
        if request.method == "POST":
            body = await request.json()
            code = (body.get("access_code") or "").strip()
        else:
            code = (request.query_params.get("access_code") or "").strip()

        res = profile_manager.load_profile(code)
        if res.get("ok") and res.get("keys"):
            import config_manager as cm
            cfg = cm.load_config()
            env_map = {
                "groq_key": "GROQ_API_KEY",
                "cerebras_key": "CEREBRAS_API_KEY",
                "openai_key": "OPENAI_API_KEY",
                "elevenlabs_key": "ELEVENLABS_API_KEY",
                "gemini_key": "GEMINI_API_KEY",
                "sambanova_key": "SAMBANOVA_API_KEY",
                "openrouter_key": "OPENROUTER_API_KEY",
                "nvidia_key": "NVIDIA_API_KEY",
            }
            for k, val in res["keys"].items():
                if val:
                    _SESSION_KEYS[k] = val
                    cfg[k] = val
                    if k in env_map:
                        os.environ[env_map[k]] = val
            cm.save_config(cfg)
        return res
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/profiles")
async def cloud_profiles_list_api():
    if not profile_manager:
        return {"ok": False, "profiles": []}
    try:
        return {"ok": True, "profiles": profile_manager.list_profiles()}
    except Exception as e:
        return {"ok": False, "error": str(e), "profiles": []}

# ─── GÖREV VE EYLEM PLANLAMA MOTORU (Plan Manager) ───────────────
@app.post("/api/plan/create")
async def cloud_plan_create_api(data: dict):
    if not plan_manager:
        return {"ok": False, "error": "plan_manager modülü aktif değil"}
    goal = (data.get("goal") or "").strip()
    if not goal:
        return {"ok": False, "error": "Hedef belirtilmelidir."}
    try:
        async def _llm_caller(prompt, system):
            for name, caller in _PROVIDER_CHAIN:
                ok, text = await caller(prompt, system)
                if ok:
                    return ok, text
            return False, ""

        plan = await plan_manager.generate_plan_with_llm(goal, _llm_caller)
        return {"ok": True, "plan": plan}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/api/plan/execute")
async def cloud_plan_execute_api(data: dict):
    if not plan_manager:
        return {"ok": False, "error": "plan_manager modülü aktif değil"}
    plan_id = (data.get("plan_id") or "").strip()
    if not plan_id:
        return {"ok": False, "error": "plan_id gereklidir."}
    try:
        async def _exec_tool(tool_name, args):
            if tool_name == "read_file":
                p = Path(args.get("path", "."))
                if p.exists() and p.is_file():
                    return p.read_text(encoding="utf-8", errors="ignore")[:2000]
                return "Dosya okunamadı veya bulunamadı"
            elif tool_name == "generate_pdf" and document_generator:
                res = document_generator.generate_pdf(args.get("title", "Rapor"), args.get("content", ""))
                return res.get("message", "PDF oluşturuldu")
            elif tool_name == "run_terminal_command":
                cmd = args.get("cmd") or args.get("command", "")
                import subprocess
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                return (res.stdout or res.stderr or "Tamamlandı")[:1500]
            return f"Adım tamamlandı: {tool_name}"

        res = await plan_manager.execute_plan(plan_id, _exec_tool)
        return {"ok": True, "plan": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/plans")
async def cloud_plans_list_api():
    if not plan_manager:
        return {"ok": False, "plans": []}
    return {"ok": True, "plans": plan_manager.list_plans()}

@app.get("/api/plan/{plan_id}")
async def cloud_plan_get_api(plan_id: str):
    if not plan_manager:
        return {"ok": False, "error": "plan_manager aktif değil"}
    p = plan_manager.get_plan(plan_id)
    if not p:
        return {"ok": False, "error": "Plan bulunamadı"}
    return {"ok": True, "plan": p}

@app.delete("/api/plan/{plan_id}")
async def cloud_plan_delete_api(plan_id: str):
    if not plan_manager:
        return {"ok": False, "error": "plan_manager aktif değil"}
    ok = plan_manager.delete_plan(plan_id)
    return {"ok": ok}

# ─── KODLAMA VE CANLI TERMİNAL ÇALIŞTIRICI (Coding Agent Terminal) ─
@app.post("/api/terminal/run")
async def cloud_terminal_run_api(data: dict):
    cmd = (data.get("command") or data.get("cmd") or "").strip()
    timeout = int(data.get("timeout") or 30)
    if not cmd:
        return {"ok": False, "error": "Komut boş olamaz"}
    try:
        import subprocess
        res = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(BASE_DIR)
        )
        return {
            "ok": True,
            "command": cmd,
            "exit_code": res.returncode,
            "stdout": res.stdout or "",
            "stderr": res.stderr or "",
            "time": datetime.now().isoformat()
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "command": cmd, "error": f"Komut zaman aşımına uğradı ({timeout}s)", "exit_code": -1}
    except Exception as e:
        return {"ok": False, "command": cmd, "error": str(e), "exit_code": -1}

@app.get("/api/download/pdf/{filename}")
async def download_pdf_endpoint(filename: str):
    """Oluşturulan PDF belgesini indirir."""
    if document_generator is None:
        raise HTTPException(status_code=500, detail="Belge üretim modülü aktif değil")
    p = document_generator.get_pdf_path(filename)
    if not p or not p.exists():
        raise HTTPException(status_code=404, detail="Dosya bulunamadı")
    return FileResponse(
        path=str(p),
        media_type="application/pdf",
        filename=p.name
    )

@app.get("/api/telemetry")
async def get_telemetry_endpoint():
    """Sistem performans ve başarı metriklerini döner."""
    if telemetry is None:
        return {"ok": False, "error": "Telemetri modülü aktif değil"}
    return {"ok": True, "data": telemetry.get_metrics()}

@app.post("/api/telemetry/reset")
async def reset_telemetry_endpoint():
    """Telemetri sayaçlarını sıfırlar."""
    if telemetry is None:
        return {"ok": False, "error": "Telemetri modülü aktif değil"}
    telemetry.reset_metrics()
    return {"ok": True, "message": "Metrikler sıfırlandı"}

# ─── STATİK DOSYA VE PDF ERİŞİMİ ──────────────────────────────────────
STATIC_PDFS_DIR = BACKEND_DIR / "static" / "pdfs"
STATIC_PDFS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(BACKEND_DIR / "static")), name="ales-static")

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
    port = int(os.environ.get("PORT", 10000))
    print(f"[ALES CLOUD] Starting server on 0.0.0.0:{port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
