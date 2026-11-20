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
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException
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
HAS_ANY_KEY = any(os.environ.get(k) for k in (
    "GROQ_API_KEY", "CEREBRAS_API_KEY", "GEMINI_API_KEY",
    "SAMBANOVA_API_KEY", "OPENROUTER_API_KEY", "NVIDIA_API_KEY",
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

# ─── SISTEM PROMPTU (main.py'nin freelance uzmanlik bolumu + PC kisiti notu) ─
SYSTEM_PROMPT = """Sen ALES (Advanced Logic Execution System), Ali'nin kisisel AI asistanisin.
Su an CLOUD/TELEFON modunda calisiyorsun - Ali'nin bilgisayarinda DEGIL, internette bir sunucudasin.

BU MOD ICIN ONEMLI KISIT: Bilgisayara fiziksel erisimin YOK. Su ozellikleri
SUNAMAZSIN, biri istenirse "bu ozellik sadece bilgisayarindaki ALES'te
calisir, PC'yi acip oradan dene" de:
- Fiverr/Bionluk tarayici otomasyonu (mesaj kontrolu, siparis takibi)
- Ekran goruntusu alma/analiz etme
- Ali'nin bilgisayarindaki dosyalari okuma/yazma
- Yerel uygulama acma
- Sesli yanit (TTS su an sadece PC hoparlorunde calar)

YAPABILDIKLERIN: Sohbet, genel bilgi, tavsiye, 4-AI derin analiz/tartisma
modu ("derin analiz", "tartis", "4 ai" gibi ifadelerle tetiklenir).

FREELANCE UZMANLIGI (HER ZAMAN AKTIF): Ali'nin Fiverr/Bionluk'ta sattigi
hizmetler web scraping, otomasyon ve AI chatbot gelistirme. Bu konularda
her zaman uzman bir is ortagi gibi davran: brief netlestir, kapsam
tasmasina izin verme, fiyat sorulursa kesin rakam yerine gerekceli bir
aralik oner (karmasiklik/veri hacmi/sureye gore), musteri mesaji taslagi
hazirla, red-flag musteri davranislarini (scope buyutme, on odemesiz is,
platform disi anlasma baskisi) fark edip Ali'yi uyar.

Turkce konus, kisa ve net ol. Tarih: {now}"""

# ─── TEK-TURLU SOHBET: 5 SAGLAYICI DUSEN SIRA ─────────────────────
# multi_agent.py'daki caller'lari (_call_groq vb.) DOGRUDAN reuse ediyoruz -
# ayni rate-limit / hata yakalama mantigi burada da gecerli.
_PROVIDER_CHAIN = [
    ("Qwen3.6", multi_agent._call_qwen),
    ("Groq", multi_agent._call_groq),
    ("Cerebras", multi_agent._call_cerebras),
    ("Gemini", multi_agent._call_gemini),
    ("SambaNova", multi_agent._call_sambanova),
    ("OpenRouter", multi_agent._call_openrouter),
]

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

            if not HAS_ANY_KEY:
                await websocket.send_json({"type": "error", "content": "❌ Sunucuda hic AI API key tanimli degil (Railway/Render ortam degiskenlerini kontrol et)."})
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
    return {
        "status": "online",
        "mode": "cloud",
        "has_groq": bool(os.environ.get("GROQ_API_KEY")),
        "has_cerebras": bool(os.environ.get("CEREBRAS_API_KEY")),
        "has_gemini": bool(os.environ.get("GEMINI_API_KEY")),
        "has_sambanova": bool(os.environ.get("SAMBANOVA_API_KEY")),
        "has_openrouter": bool(os.environ.get("OPENROUTER_API_KEY")),
        "has_nvidia": bool(os.environ.get("NVIDIA_API_KEY")),
        "auth_enabled": bool(ACCESS_KEY),
        "time": datetime.now().isoformat(),
    }

# ─── HTTP: KONFIGURASYON (SADECE OKUMA - key'ler env'den, degistirilemez) ──
@app.get("/config")
async def get_config(x_ales_key: str = Header(default="")):
    if not _key_ok(x_ales_key):
        raise HTTPException(status_code=401)
    return {
        "has_groq": bool(os.environ.get("GROQ_API_KEY")),
        "has_cerebras": bool(os.environ.get("CEREBRAS_API_KEY")),
        "has_elevenlabs": False,
        "has_openrouter": bool(os.environ.get("OPENROUTER_API_KEY")),
        "has_nvidia": bool(os.environ.get("NVIDIA_API_KEY")),
        "cloud_readonly": True,
    }

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
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
