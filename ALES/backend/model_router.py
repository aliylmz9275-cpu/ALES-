"""
model_router.py — ALES cok-katmanli akilli yonlendirici (Faz 1, Task #2).

Tum saglayicilar OpenAI-uyumlu bir /chat/completions endpoint'i sunar, bu
yuzden HEPSI tek bir AsyncOpenAI arayuzunden konusulur (streaming + tool
calling dahil). Boylece tek kod yolu; katman degistirmek = base_url + key +
model degistirmek.

Katmanlar (config_manager.DEFAULT_MODELS — TEK DOGRU KAYNAK orasidir;
asagidaki liste yalnizca okuma kolayligi icin):
  fast         Cerebras   gpt-oss-120b                      (<100ms hedef)
  fallback     Groq       openai/gpt-oss-120b               (fast duşerse)
  vision       Gemini     gemini-3.8-flash                  (gorsel)
  code         OpenRouter qwen/qwen3.8-27b                  (kod/plan)
  unrestricted NVIDIA     deepseek-ai/deepseek-v4-pro       (Cheat)
  heavy        OpenRouter moonshotai/kimi-k3                (Heavy)

Model kimligi eskidiginde "hicbir katman yanit vermedi" hatasi gorunur ama
SEBEBI gorunmez. Teshis icin: GET /test-models (bkz. probe_all, dosya sonu).

OTOMATIK MODEL KESFI (model_registry.py): her cagri oncesi kimlik canli
saglayici listesine karsi dogrulanir, saglayici "boyle bir model yok" derse
liste tazelenip ayni aileden gecerli bir kimlikle BIR KEZ yeniden denenir ve
karar kalici hale gelir. Onemli iki kural:
  - Liste alinamadiysa cagri ENGELLENMEZ (fail-open) — eksik bir liste
    calisan bir kurulumu offline birakmasin.
  - Otomatik duzeltme config.json'a YAZILMAZ; ayri bir katmanda tutulur ve
    arayuzden geri alinabilir (Ayarlar > Gelismis > MODEL KESFI).
Panel/teshis: GET /model-discovery, POST /model-discovery/refresh.

Mod (config_manager.get_mode_config) zinciri belirler:
  multi=False -> chat_chain(): sirali fallback (timeout/hata -> sonraki katman)
  multi=True  -> race_chain(): katmanlar AYNI ANDA yarisir, ilk gecerli yanit

Zaman asimlari config.json['timeouts'] ile ayarlanabilir. Key yoksa katman
sessizce atlanir (bir sonrakine duşulur).
"""
import asyncio
import re
import time
from typing import Optional, AsyncIterator

from config_manager import (get_key, get_mode_config, get_timeouts,
                            get_max_out, HEAVY_ONLY_LAYERS, layer_allowed)

# Otomatik model kesfi (model_registry.py). SAVUNMACI import: bu modul
# olmadan da router AYNEN calisir, sadece dogrulama/otomatik duzeltme
# devre disi kalir. Boylece yeni bir guvenilirlik katmani, var olan
# calisan yolu dusuren tek nokta haline gelmez.
try:
    import model_registry
except Exception as _e:            # pragma: no cover
    model_registry = None
    print(f"[ROUTER] model_registry yuklenemedi, otomatik model kesfi kapali: {_e}")

try:
    import adaptive_timeouts
except Exception as _e:
    adaptive_timeouts = None

try:
    import self_heal
except Exception as _e:
    self_heal = None

# Big ALES orkestratoru (Puter, API anahtari YOK). SAVUNMACI import:
# yuklenemezse "big_ales" modu normal zincir gibi davranir — mod adi
# yuzunden sohbetin tamamen olmesi kabul edilemez.
try:
    import puter_connector
except Exception as _e:            # pragma: no cover
    puter_connector = None
    print(f"[ROUTER] puter_connector yuklenemedi, Big ALES kapali: {_e}")

# Provider -> OpenAI-uyumlu base_url.
PROVIDER_ENDPOINTS = {
    "groq":       "https://api.groq.com/openai/v1",
    "cerebras":   "https://api.cerebras.ai/v1",
    "gemini":     "https://generativelanguage.googleapis.com/v1beta/openai/",
    "openrouter": "https://openrouter.ai/api/v1",
    "nvidia":     "https://integrate.api.nvidia.com/v1",
    "sambanova":  "https://api.sambanova.ai/v1",
}

# Provider -> config.json key adi (get_key .env fallback'i de yapar).
PROVIDER_KEY = {
    "groq": "groq_key", "cerebras": "cerebras_key", "gemini": "gemini_key",
    "openrouter": "openrouter_key", "nvidia": "nvidia_key", "sambanova": "sambanova_key",
}

# Katman anahtari -> timeouts.json alani.
_LAYER_TIMEOUT = {
    "fast": "fast_s", "fallback": "fallback_s", "vision": "vision_s",
    "code": "code_s", "unrestricted": "unrestricted_s", "heavy": "heavy_s",
}

_clients: dict = {}


class RouterError(RuntimeError):
    """Zincirdeki hicbir katman yanit veremedi."""


def _layer_timeout(layer: str, timeouts: dict = None) -> float:
    t = timeouts or get_timeouts()
    base_t = float(t.get(_LAYER_TIMEOUT.get(layer, "fallback_s"), 10.0))
    if adaptive_timeouts is not None:
        return adaptive_timeouts.get_timeout(layer, fallback=base_t)
    return base_t


def _layer_max_out(layer: str, want: int, caps: dict = None) -> int:
    """Bu katman icin gonderilecek max_tokens.

    NEDEN GEREKLI: max_tokens saglayici tarafinda BAGLAM PENCERESINDEN
    REZERVE EDILIR ("istem + max_tokens <= pencere"). Cerebras'in ucretsiz
    llama-3.3-70b penceresi 8192; sabit 4096 istemek ISTEME sadece ~4096
    token birakiyordu ve ALES'in istemi (sistem + hafiza + ~35 arac semasi)
    bunu asiyordu -> aninda 400 "context length exceeded", zaman asimi bile
    degil. Katman basina tavan bunu onler (bkz. config_manager.DEFAULT_MAX_OUT).

    TAVAN mantigi: cagiran daha KUCUK bir deger istediyse ona saygi duyulur;
    sadece ust sinir uygulanir.
    """
    try:
        c = caps if caps is not None else get_max_out()
        cap = int(c.get(_LAYER_TIMEOUT.get(layer, "fallback_s"), 4096))
    except Exception:
        return want
    return max(256, min(int(want), cap))


# ─── BAGLAM PENCERESI HATASI ─────────────────────────────────────
# Yukaridaki tavanlar TAHMINDIR (saglayicilar pencereyi haber vermeden
# degistirir, ucretli/ucretsiz katman farkli olur). Bu yuzden ikinci bir
# savunma: gercek bir baglam hatasi gelirse ciktiyi kucultup BIR KEZ daha
# dene. Boylece tavan yanlis tahmin edildiginde de katman calisir.
# Kalip DAR: "context/token limit" ailesi disinda bir seye dokunmuyor.
_CTX_PAT = re.compile(
    r"(context[_ ]length|context[_ ]window|maximum context|too many tokens"
    r"|reduce the length|max_tokens.{0,40}(exceed|too large|greater)"
    r"|prompt is too long|input is too long"
    r"|please reduce|exceeds? the (maximum|model'?s) )", re.I)


def _is_context_error(text) -> bool:
    """Hata 'istem + cikti pencereye sigmiyor' diyor mu?"""
    return bool(_CTX_PAT.search(str(text)))


def get_client(provider: str):
    """Provider icin AsyncOpenAI istemcisi (key + base_url ile). Sureli
    cache'lenir. Key yoksa None doner (caller katmani atlar)."""
    key = get_key(PROVIDER_KEY.get(provider, ""))
    if not key:
        return None
    base = PROVIDER_ENDPOINTS.get(provider)
    if not base:
        return None
    cache_key = (provider, key[:8])
    if cache_key not in _clients:
        from openai import AsyncOpenAI
        _clients[cache_key] = AsyncOpenAI(base_url=base, api_key=key)
    return _clients[cache_key]


def available_providers() -> dict:
    """UI/teshis: hangi saglayicilarin key'i var."""
    return {p: bool(get_key(k)) for p, k in PROVIDER_KEY.items()}


# ─── MODEL DOGRULAMA + KENDINI IYILESTIRME ───────────────────────
# "Gecersiz model adi" hatasi saglayici basina apayri metinlerle geliyor;
# tek bir kalibin hepsini yakalamasi gerekiyor. YANLIS POZITIF PAHALIDIR:
# kota/yetki hatasini "model olmus" sanip modeli kara listeye almak, calisan
# bir katmani kalici olarak kaybettirirdi. Bu yuzden kalip DAR tutuldu ve
# model_registry.heal() ayrica "model listede duruyorsa dokunma" kontrolu
# yapiyor (iki kademeli koruma).
_MODEL_DEAD_PAT = re.compile(
    r"(model_not_found|model_decommissioned|invalid_model"
    r"|does not exist|no such model|unknown model|not a valid model"
    r"|model .{0,60}(not found|not available|decommissioned|deprecated|retired)"
    r"|is no longer (available|supported))", re.I)


def _is_dead_model_error(text) -> bool:
    """Hata metni 'bu model kimligi artik gecersiz' diyor mu?"""
    s = str(text)
    if not _MODEL_DEAD_PAT.search(s):
        return False
    # Kimlik dogrulama/kota hatalarini DISLA: bunlar model adiyla ilgili
    # degil ve kara listeye girmemeli.
    if re.search(r"(invalid[_ ]api[_ ]key|unauthorized|authentication"
                 r"|rate[_ ]limit|quota|insufficient|billing|payment"
                 r"|permission)", s, re.I):
        return False
    return True


def _resolve_model(provider: str, model: str, lname: str) -> tuple:
    """Cagri oncesi model kimligini cozumle ve dogrula.

    Doner: (kullanilacak_model, engel_sebebi_veya_None)

    KURAL — FAIL-OPEN: liste yoksa/eksikse cagri ENGELLENMEZ. Yalnizca
    KARA LISTE (yani gercek bir cagrinin reddettigi kimlik) engeller, cunku
    o tek basina kesin kanittir. Ayrintili gerekce: model_registry.py basi.
    """
    if model_registry is None or not model:
        return model, None
    reg = model_registry.registry
    try:
        eff = reg.effective_model(provider, model)
        if eff != model:
            reg._note("INFO", f"{lname}: {provider}/{model} -> {eff} "
                              f"(otomatik duzeltme uygulandi)")
        if reg.is_blacklisted(provider, eff):
            # Yedegi de yok (olsaydi effective_model onu dondururdu) ->
            # katmani atla, zincir SONRAKI saglayiciya duşsun.
            return eff, (f"{provider}/{eff}: kalici olarak kaldirilmis model "
                         f"(kara liste) ve guvenli bir yedek bulunamadi")
        st = reg.check(provider, eff)
        if st["known"] is False:
            # UYAR ama DENE: liste eksik olabilir (bkz. fail-open kurali).
            reg._note("WARN", f"{lname}: {provider}/{eff} saglayici listesinde yok "
                              f"— yine deniyorum. Oneri: "
                              f"{', '.join(st['suggestions'][:2]) or 'yok'}")
        return eff, None
    except Exception as e:
        # Dogrulama katmani ASLA cagriyi dusurmez.
        print(f"[ROUTER] model dogrulamasi atlandi ({provider}/{model}): {e}")
        return model, None


async def _heal_model(provider: str, model: str, err: str, lname: str) -> str:
    """Gecersiz model hatasindan sonra dogru adi bul. Yoksa "" doner."""
    if model_registry is None:
        return ""
    try:
        alt = await model_registry.registry.heal(provider, model, err)
        if alt:
            print(f"[ROUTER] {lname}: {provider}/{model} -> {alt} "
                  f"(otomatik duzeltildi, yeniden deneniyor)")
        return alt
    except Exception as e:
        print(f"[ROUTER] {lname}: iyilestirme basarisiz: {e}")
        return ""


async def _retire_substitute(provider: str, configured: str, bad: str,
                             err: str, lname: str) -> str:
    """Ise yaramaz OTOMATIK YEDEGI geri al ve yenisini bul. Yoksa "" doner.

    `configured` = kullanicinin config.json'daki modeli (override anahtari).
    `bad`        = o anahtarin gosterdigi, cagriyi dusuren yedek.
    Anahtar `configured` olmali: override tablosu ONUN uzerinden yazildi.
    """
    if model_registry is None:
        return ""
    try:
        alt = await model_registry.registry.heal_substitute(
            provider, configured, err)
        if alt:
            print(f"[ROUTER] {lname}: ise yaramaz yedek {bad} geri alindi -> "
                  f"{alt} (yeniden deneniyor)")
        else:
            print(f"[ROUTER] {lname}: ise yaramaz yedek {bad} geri alindi; "
                  f"yeni yedek bulunamadi — katman atlaniyor")
        return alt
    except Exception as e:
        print(f"[ROUTER] {lname}: yedek degisimi basarisiz: {e}")
        return ""


# ─── TEK KATMAN CAGRISI (non-streaming) ──────────────────────────
async def _call_layer(layer: dict, messages: list, timeout: float,
                      tools: list = None, max_tokens: int = 4096,
                      temperature: float = 0.5, mode: str = None) -> dict:
    """Tek bir katmani cagir. Doner: {ok, layer, provider, model, message,
    content, tool_calls, elapsed, error}. Key yoksa/hata/timeout -> ok=False.

    `mode` OPSIYONELDIR (mevcut 6 cagri yeri degismeden calisir). Verilirse
    heavy-only kapisi burada IKINCI kez denetlenir: get_mode_config() zaten
    zincirden dusuruyor, ama bir cagri yolu katmani dogrudan verirse
    (ornegin elle kurulmus bir layer sozlugu) tek kapiya guvenmemek gerekir.

    MODEL KESFI: cagri oncesi kimlik model_registry ile cozumlenir; cagri
    "boyle bir model yok" diye duserse liste tazelenip DOGRU adla BIR KEZ
    yeniden denenir. Donen sozluge `healed`/`original_model` alanlari
    eklenir; mevcut alanlarin hicbiri degismedi (cagiranlar etkilenmez).
    """
    provider = layer.get("provider")
    model = layer.get("model")
    lname = layer.get("layer", provider)
    t0 = time.time()
    # GUVENLIK/MALIYET KAPISI: heavy katmani izinsiz modda cagirilamaz.
    if lname in HEAVY_ONLY_LAYERS and not layer_allowed(lname, mode):
        return {"ok": False, "layer": lname, "provider": provider, "model": model,
                "error": (f"{lname}: bu modda kapali (heavy_ok=False) — "
                          "Heavy veya Council moduna gec"),
                "elapsed": 0.0}

    # DEVRE KESİCİ DENETİMİ (Circuit Breaker)
    if self_heal is not None and not self_heal.can_call_provider(provider):
        return {"ok": False, "layer": lname, "provider": provider, "model": model,
                "error": f"{provider}: devre kesici AÇIK (cooldown sürüyor)", "elapsed": 0.0}

    client = get_client(provider)
    if client is None:
        # Heavy katmanı için akıllı kurtarma: Eğer Gemini anahtarı yoksa NVIDIA DeepSeek V4 veya Groq ile kurtar
        if lname == "heavy":
            for fb_prov, fb_mod in [("nvidia", "deepseek-ai/deepseek-v4"), ("groq", "llama-3.3-70b-versatile")]:
                fb_client = get_client(fb_prov)
                if fb_client is not None:
                    provider = fb_prov
                    model = fb_mod
                    client = fb_client
                    break
        if client is None:
            return {"ok": False, "layer": lname, "provider": provider, "model": model,
                    "error": f"{provider}: key yok", "elapsed": 0.0}

    # Cagri oncesi dogrulama (fail-open; yalnizca kara liste engeller).
    original = model
    model, blocked = _resolve_model(provider, model, lname)
    if blocked:
        return {"ok": False, "layer": lname, "provider": provider, "model": model,
                "error": blocked, "elapsed": 0.0,
                "original_model": original}

    # Cikti tavani: stream_chat ile AYNI gerekce (max_tokens baglam
    # penceresinden rezerve edilir; bkz. _layer_max_out).
    cur_out = _layer_max_out(lname, max_tokens)

    async def _attempt(mid: str, mout: int):
        kwargs = {"model": mid, "messages": messages,
                  "max_tokens": mout, "temperature": temperature}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return await asyncio.wait_for(
            client.chat.completions.create(**kwargs), timeout=timeout)

    healed = shrunk = retired = False
    for _round in (0, 1, 2, 3):        # olu-ad, ise yaramaz yedek, pencere
        try:
            r = await _attempt(model, cur_out)
            msg = r.choices[0].message
            out = {"ok": True, "layer": lname, "provider": provider,
                   "model": model, "message": msg,
                   "content": (msg.content or ""),
                   "tool_calls": getattr(msg, "tool_calls", None),
                   "elapsed": time.time() - t0, "error": None}
            if healed:
                out["healed"] = True
                out["original_model"] = original

            # Başarı raporu: Devre kesiciyi sıfırla ve gecikmeyi kaydet
            if self_heal is not None:
                self_heal.report_provider_success(provider)
            if adaptive_timeouts is not None:
                adaptive_timeouts.record_latency(lname, out["elapsed"], success=True)
                adaptive_timeouts.record_latency(provider, out["elapsed"], success=True)

            return out
        except asyncio.TimeoutError:
            # Zaman asimi model adiyla ILGISIZ — iyilestirme denenmez.
            if self_heal is not None:
                self_heal.report_provider_failure(provider, f"timeout ({timeout}s)")
            if adaptive_timeouts is not None:
                adaptive_timeouts.record_latency(lname, time.time() - t0, success=False)
            return {"ok": False, "layer": lname, "provider": provider, "model": model,
                    "error": f"{provider}/{model}: timeout ({timeout}s)",
                    "elapsed": time.time() - t0}
        except Exception as e:
            err = f"{provider}/{model}: {e}"
            # ISE YARAMAZ YEDEK: cagri ALES'in KENDI koydugu bir yedege
            # gidiyordu (model != original) ve yedek kalici olarak
            # kullanilamaz (402 / arac cagirmiyor). Bu hatalar
            # _is_dead_model_error tarafindan BILEREK dislaniyor (model adi
            # sorunu degil), dolayisiyla eski kodda hicbir dal buraya
            # bakmiyordu ve olu yedek sonsuza kadar kaliyordu. Geri al,
            # yenisini bul, BIR KEZ dene.
            if (not retired and model != original
                    and model_registry is not None
                    and model_registry.substitute_unusable(e)):
                alt = await _retire_substitute(provider, original, model,
                                               str(e), lname)
                if alt and alt != model:
                    model, retired, healed = alt, True, True
                    continue           # yeni yedekle bir kez daha dene
            if not healed and _is_dead_model_error(e):
                alt = await _heal_model(provider, model, str(e), lname)
                if alt and alt != model:
                    model, healed = alt, True
                    continue           # DOGRU adla bir kez daha dene
            if not shrunk and _is_context_error(e) and cur_out > 512:
                cur_out, shrunk = 512, True
                continue               # KUCUK ciktiyla bir kez daha dene

            if self_heal is not None:
                self_heal.report_provider_failure(provider, str(e))
            if adaptive_timeouts is not None:
                adaptive_timeouts.record_latency(lname, time.time() - t0, success=False)

            out = {"ok": False, "layer": lname, "provider": provider,
                   "model": model, "error": err, "elapsed": time.time() - t0}
            if healed:
                out["healed"] = True
                out["original_model"] = original
            return out
    # Buraya ULASILMAMASI gerekir (UC bayrak -> en fazla uc `continue`,
    # dorduncu tur mutlaka return eder). Yine de bir gun dongude bir tur
    # eklenirse None dondurup chat_chain'i res["ok"] uzerinde patlatmasin.
    return {"ok": False, "layer": lname, "provider": provider, "model": model,
            "error": f"{provider}/{model}: deneme turlari tukendi",
            "elapsed": time.time() - t0}


# ─── BIG ALES: PUTER ORKESTRATORU ────────────────────────────────
# Sozlesme (Ali'nin tanimi): orkestrator YURUTMEZ. Yalnizca istegi net ve
# yasal bicimde YENIDEN YAZAR; yurutmeyi normal ALES zinciri yapar. Bu
# yuzden burasi zinciri ya da modeli DEGISTIRMEZ, sadece mesaji degistirir.
#
# EN ONEMLI OZELLIK — FAIL-OPEN: Puter yolu kullanilamazsa (arayuz penceresi
# kapali, kullanici giris yapmamis, ag yok, zaman asimi, izin verilmeyen
# model) istek OLDUGU GIBI birakilir ve zincir normal calisir. Bir mod
# secimi yuzunden calisan sohbetin tamamen olmesi kabul edilemez; projenin
# fail-open kurali tam olarak bunu soyluyor.
async def big_ales_orchestrate(messages: list, mc: dict) -> list:
    """Gerekiyorsa son kullanici mesajini yeniden yazip YENI liste dondurur.

    Mod (veya Ayarlar'daki global anahtar) kapaliysa listeyi DOKUNMADAN
    ayni nesne olarak geri verir — mutlu yolda hicbir maliyeti yoktur.
    """
    if not mc.get("big_ales") or puter_connector is None:
        return messages
    if not messages:
        return messages

    # Yeniden yazilacak mesaj: SON "user" mesaji.
    idx = None
    for i in range(len(messages) - 1, -1, -1):
        if (messages[i] or {}).get("role") == "user":
            idx = i
            break
    if idx is None:
        return messages
    original = messages[idx].get("content")
    # Cok kipli icerik (gorsel + metin) bir liste olarak gelir; onu
    # yeniden yazmaya kalkmak gorseli kaybettirirdi.
    if not isinstance(original, str) or not original.strip():
        return messages

    model_id = mc.get("big_ales_model") or puter_connector.DEFAULT_MODEL
    t0 = time.time()
    try:
        rewritten = await puter_connector.rewrite_request(
            original, model_id=model_id,
            timeout=float(mc.get("big_ales_timeout_s") or 60.0))
    except Exception as e:
        # Kullaniciya gorunen bir hata DEGIL: sadece iz. Zincir devam eder.
        print("[BIG ALES] orkestrator atlandi (%s: %s) -- istek OLDUGU GIBI "
              "zincire gidiyor" % (type(e).__name__, e))
        return messages

    if not rewritten or rewritten.strip() == original.strip():
        return messages
    print("[BIG ALES] istek yeniden yazildi (%s, %.1fs): %d -> %d karakter"
          % (model_id, time.time() - t0, len(original), len(rewritten)))
    # Yeni LISTE uretiyoruz: cagiran tarafin elindeki liste (ve onun
    # icindeki sozlukler) DEGISMEZ. Yerinde degistirseydik ayni mesaj
    # nesnesini tutan sohbet gecmisi de sessizce yeniden yazilmis olurdu.
    out = list(messages)
    out[idx] = {**messages[idx], "content": rewritten}
    return out


def _sort_chain_by_latency(chain: list) -> list:
    """Gerçek gecikmeye (adaptive_timeouts EWMA) ve devre kesiciye göre zinciri sıralar."""
    if len(chain) <= 1:
        return chain
    st = adaptive_timeouts.get_stats() if adaptive_timeouts else {}
    def _score(layer_dict):
        lname = layer_dict.get("layer", "")
        prov = layer_dict.get("provider", "")
        if self_heal is not None and not self_heal.can_call_provider(prov):
            return 9999.0
        return st.get(lname, {}).get("avg_s", st.get(prov, {}).get("avg_s", 15.0))
    return sorted(chain, key=_score)


# ─── SIRALI ZINCIR (multi=False) ─────────────────────────────────
async def chat_chain(messages: list, mode: str = None, tools: list = None,
                     max_tokens: int = 4096, temperature: float = 0.5) -> dict:
    """Modun zincirini dinamik gecikme önceliğiyle SIRAYLA dener; ilk basarili yaniti dondurur."""
    mc = get_mode_config(mode)
    timeouts = mc["timeouts"]
    errors = []
    sorted_chain = _sort_chain_by_latency(mc["chain"])
    if mc.get("mode") == "heavy":
        sorted_chain = sorted(sorted_chain, key=lambda l: 0 if l.get("layer") == "heavy" else 1)
    for layer in sorted_chain:
        res = await _call_layer(layer, messages, _layer_timeout(layer["layer"], timeouts),
                                tools=tools, max_tokens=max_tokens,
                                temperature=temperature, mode=mc["mode"])
        if res["ok"]:
            res["mode"] = mc["mode"]
            res["errors"] = errors
            return res
        errors.append(res["error"])
    raise RouterError(f"[{mc['mode']}] zincirde hicbir katman yanit vermedi: " + " | ".join(errors))


# ─── PARALEL YARIS (multi=True) ──────────────────────────────────
async def race_chain(messages: list, mode: str = None, tools: list = None,
                     max_tokens: int = 4096, temperature: float = 0.5) -> dict:
    """Modun zincirindeki katmanlari AYNI ANDA cagirir, ILK gecerli yaniti
    dondurur (en hizli). Kalan istekler iptal edilir. Multi/Heavy modlari
    icin. Zincirdeki en buyuk timeout genel siniri belirler."""
    mc = get_mode_config(mode)
    timeouts = mc["timeouts"]
    layers = mc["chain"]
    if mc.get("mode") == "heavy":
        layers = sorted(layers, key=lambda l: 0 if l.get("layer") == "heavy" else 1)
    if not layers:
        raise RouterError(f"[{mc['mode']}] zincir bos")
    tasks = [asyncio.ensure_future(
        _call_layer(l, messages, _layer_timeout(l["layer"], timeouts),
                    tools=tools, max_tokens=max_tokens,
                    temperature=temperature, mode=mc["mode"])
    ) for l in layers]
    errors = []
    try:
        pending = set(tasks)
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for d in done:
                res = d.result()
                if res["ok"]:
                    res["mode"] = mc["mode"]
                    res["errors"] = errors
                    return res
                errors.append(res["error"])
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
    raise RouterError(f"[{mc['mode']}] yarista hicbir katman yanit vermedi: " + " | ".join(errors))


async def route_chat(messages: list, mode: str = None, tools: list = None,
                     max_tokens: int = 4096, temperature: float = 0.5) -> dict:
    """Moda gore chat_chain (sirali) veya race_chain (paralel) secer."""
    mc = get_mode_config(mode)
    # Big ALES: zincire GIRMEDEN once orkestrator gecisi (fail-open).
    messages = await big_ales_orchestrate(messages, mc)
    fn = race_chain if mc["multi"] else chat_chain
    return await fn(messages, mode=mc["mode"], tools=tools,
                    max_tokens=max_tokens, temperature=temperature)


# ─── STREAMING (token token) ─────────────────────────────────────
async def stream_chat(messages: list, mode: str = None, tools: list = None,
                      max_tokens: int = 4096, temperature: float = 0.5,
                      on_layer=None) -> AsyncIterator[dict]:
    """Modun zincirini SIRAYLA dener; ilk BAGLANABILEN katmandan token'lari
    yield eder. Her chunk: {"type":"token","text":...} veya
    {"type":"tool_calls","tool_calls":[...]} veya {"type":"done","layer":...}.
    Bir katman baglanamazsa (key yok / ilk chunk'tan once hata) sonrakine
    duşer. Not: streaming'de multi=True yine SIRALI ele alinir (ilk calisan
    katmandan yayin yapmak, paralel yaristan daha oz kaynak kullanir).

    IKI GECIS (2026-08-26'da eklendi). Zincir tukendiginde HEMEN vazgecmek
    yerine ayni zincir bir kez daha, GEVSETILMIS butcelerle denenir:
    zaman asimi x3 (en az 45s) ve cikti 512 token. NEDEN: main.py'de zincir
    tamamen duserse ARAC DESTEGI OLMAYAN duz-metin yedegine iniliyor
    ("bu turda arac/otomasyon kullanilamadi"). Yani kullanicinin araclarini
    kaybettiren sey cogu zaman modelin yetenegi degil bir BUTCE hatasidir;
    ikinci gecis onu telafi eder ve arac cagrilari calismaya devam eder.
    Mutlu yolda HIC calismaz (yalnizca her sey basarisiz olduysa), yani
    normal gecikmeye hicbir etkisi yoktur."""
    mc = get_mode_config(mode)
    timeouts = mc["timeouts"]
    caps = mc.get("max_out")
    # Big ALES: ANA SOHBET YOLU burasi. Zincir denenmeden once istek
    # Puter'daki orkestratorle netlestirilir. Kullanilamazsa (giris yok /
    # arayuz kapali) mesaj oldugu gibi devam eder — bkz. fail-open notu.
    messages = await big_ales_orchestrate(messages, mc)
    errors = []
    for _pass in (0, 1):
      if _pass == 1:
        print("[ROUTER] zincir tukendi — gevsetilmis butcelerle IKINCI GECIS "
              f"({len(mc['chain'])} katman, arac destegi korunuyor)")
        errors.append("--- ikinci gecis (gevsetilmis butce) ---")
      for layer in mc["chain"]:
        provider, model = layer.get("provider"), layer.get("model")
        # Heavy-only kapisi: zincir zaten filtreli ama akis ANA sohbet
        # yolu; burada da denetlemek bedava (bkz. _call_layer).
        if layer.get("layer") in HEAVY_ONLY_LAYERS and not layer_allowed(
                layer.get("layer"), mc["mode"]):
            errors.append(f"{layer.get('layer')}: bu modda kapali")
            continue
        client = get_client(provider)
        if client is None:
            errors.append(f"{provider}: key yok")
            continue
        timeout = _layer_timeout(layer["layer"], timeouts)
        # Katman basina cikti tavani: max_tokens baglam penceresinden
        # REZERVE EDILDIGI icin sabit 4096, kucuk pencereli katmanlari
        # tamamen kiriyordu (bkz. _layer_max_out).
        cur_out = _layer_max_out(layer["layer"], max_tokens, caps)
        if _pass == 1:
            timeout = max(45.0, timeout * 3)
            cur_out = min(cur_out, 512)

        # Cagri oncesi dogrulama (fail-open; bkz. _resolve_model).
        original = model
        model, blocked = _resolve_model(provider, model, layer.get("layer"))
        if blocked:
            errors.append(blocked)
            continue

        async def _open(mid: str, mout: int):
            kwargs = {"model": mid, "messages": messages, "max_tokens": mout,
                      "temperature": temperature, "stream": True}
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            return await asyncio.wait_for(
                client.chat.completions.create(**kwargs), timeout=timeout)

        # AKISI ACMA ile AKISI OKUMA ayri try'larda. NEDEN: gecersiz model
        # hatasi HER ZAMAN acilista gelir (ilk chunk'tan once). Yalnizca o
        # noktada iyilestirme deniyoruz; yayin ortasinda kopan bir baglantiyi
        # bastan tekrarlamak kullaniciya ayni metni IKI KEZ yazdirirdi.
        #
        # Acilista UC ayri iyilestirme var, her biri EN FAZLA BIR KEZ:
        #   (a) olu model adi     -> saglayicinin listesinden dogru adi al
        #   (b) ise yaramaz yedek -> ALES'in koydugu yedegi geri al, yenisini bul
        #   (c) pencere tasmasi   -> ciktiyi kucult (tavan tahmini yanlissa)
        #
        # (b) OLCULMUS bir arizanin karsiligidir ve tam BURADA olmali:
        # 2026-09-05 gunlugunde sohbetin oldugu yer bu satirdi —
        # cerebras/gemma-4-31b 402 payment_required, groq/allam-2-7b
        # "tool calling is not supported". Ikisi de ALES'in kendi koydugu
        # yedeklerdi, ikisi de akis ACILISINDA duser ve (a) onlari bilerek
        # dislar (model adi sorunu degil). Dolayisiyla eski kodda bu iki
        # katman her cagride ayni sekilde duserdi.
        stream, healed, shrunk, retired = None, False, False, False
        for _round in (0, 1, 2, 3):
            try:
                stream = await _open(model, cur_out)
                break
            except Exception as e:
                if (not retired and model != original
                        and model_registry is not None
                        and model_registry.substitute_unusable(e)):
                    alt = await _retire_substitute(
                        provider, original, model, str(e), layer.get("layer"))
                    if alt and alt != model:
                        model, retired, healed = alt, True, True
                        continue
                if not healed and _is_dead_model_error(e):
                    alt = await _heal_model(provider, model, str(e), layer.get("layer"))
                    if alt and alt != model:
                        model, healed = alt, True
                        continue
                if not shrunk and _is_context_error(e) and cur_out > 512:
                    cur_out, shrunk = 512, True
                    print(f"[ROUTER] {provider}/{model}: baglam penceresi "
                          f"tasti, cikti 512 token'a cekilip tekrar deneniyor")
                    continue
                errors.append(f"{provider}/{model}: {e}")
                break
        if stream is None:
            continue

        try:
            if on_layer:
                try: on_layer({**layer, "model": model})
                except Exception: pass
            tool_acc = {}
            saw_any = False
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if getattr(delta, "content", None):
                    saw_any = True
                    yield {"type": "token", "text": delta.content}
                if getattr(delta, "tool_calls", None):
                    for tc in delta.tool_calls:
                        idx = tc.index
                        slot = tool_acc.setdefault(idx, {"id": None, "name": "", "args": ""})
                        if tc.id: slot["id"] = tc.id
                        if tc.function and tc.function.name: slot["name"] = tc.function.name
                        if tc.function and tc.function.arguments: slot["args"] += tc.function.arguments
            if tool_acc:
                yield {"type": "tool_calls",
                       "tool_calls": [tool_acc[i] for i in sorted(tool_acc)]}
            done = {"type": "done", "layer": layer["layer"], "provider": provider,
                    "model": model, "had_tools": bool(tool_acc), "had_text": saw_any}
            if healed:
                done["healed"] = True
                done["original_model"] = original
            yield done
            return
        except Exception as e:
            errors.append(f"{provider}/{model}: {e}")
            continue
    yield {"type": "error", "error": "stream: hicbir katman baglanamadi: " + " | ".join(errors)}


# ─── OZEL YONLENDIRMELER (gorsel / kod) ──────────────────────────
async def route_vision(messages: list, mode: str = None,
                       max_tokens: int = 2048) -> dict:
    """Gorsel gorevler: modun 'vision' katmani (Gemini 2.0 Flash), key
    yoksa OpenRouter vision'a duşer. messages OpenAI vision formatinda
    (image_url part'lari) olmali."""
    mc = get_mode_config(mode)
    layer = mc["vision"]
    res = await _call_layer(layer, messages, _layer_timeout("vision", mc["timeouts"]),
                            max_tokens=max_tokens, temperature=0.2)
    if res["ok"]:
        return res
    # yedek: OpenRouter uzerinden ucuz vision.
    # ESKIDEN google/gemini-flash-1.5 idi -> OpenRouter katalogunda ARTIK YOK
    # (dogrulandi 2026-08-26). Ayni rolun guncel karsiligi kullaniliyor:
    # ucuz + hizli + gorsel okuyan Gemini Flash.
    fb = {"layer": "vision", "provider": "openrouter", "model": "google/gemini-3.7-flash"}
    res2 = await _call_layer(fb, messages, _layer_timeout("vision", mc["timeouts"]),
                             max_tokens=max_tokens, temperature=0.2)
    if res2["ok"]:
        return res2
    raise RouterError(f"vision basarisiz: {res['error']} | {res2['error']}")


async def route_code(messages: list, mode: str = None,
                     max_tokens: int = 4096) -> dict:
    """Kod/plan uretimi: modun 'code' katmani (Qwen). Cheat modunda
    unrestricted katman kod da uretebilir ama spec geregi kod->Qwen'e
    yonlenir (guclu kod modeli)."""
    mc = get_mode_config(mode)
    res = await _call_layer(mc["code"], messages, _layer_timeout("code", mc["timeouts"]),
                            max_tokens=max_tokens, temperature=0.2)
    if res["ok"]:
        return res
    raise RouterError(f"code basarisiz: {res['error']}")


# ═══════════════════════════════════════════════════════════════════════
# TESHIS: /test-models
# ═══════════════════════════════════════════════════════════════════════
# NEDEN BU VAR: "anahtar gecerli ama model baglanmiyor" hatasinin tek
# sebebi neredeyse her zaman model kimliginin ESKIMESI oluyor. Saglayicilar
# model adlarini sessizce kaldiriyor, geriye 404/400 kaliyor ve zincir
# "hicbir katman yanit vermedi" diyor -- hangi katmanin NEDEN dustugu
# gorunmuyor.
#
# Bu yuzden iki ayri sey olculuyor:
#   1) GET {base_url}/models  -> anahtarin GECERLI oldugunu ve model
#      kimliginin saglayicinin listesinde OLUP OLMADIGINI soyler.
#      TOKEN HARCAMAZ. Kimlik listede yoksa yakin adlari onerir; boylece
#      bir daha model adi tahmin etmek gerekmez.
#   2) 1 token'lik gercek sohbet cagrisi -> anahtarin O MODELE erisimi
#      var mi (listede olup plana dahil olmayan modeller olabiliyor).
#
# KAPI NOTU: burada heavy-only kapisi (layer_allowed) BILINCLI OLARAK
# uygulanmiyor. Sorulan soru "su an kullanabilir miyim" degil, "anahtar +
# model ulasilabilir mi". Kapi durumu ayri alanlarda (heavy_only /
# allowed_in_mode) yine raporlaniyor. Maliyet sinirli: katman basina
# max_tokens=1.
_PING_MESSAGES = [{"role": "user", "content": "ping"}]


def _scrub(text) -> str:
    """Hata metinlerinden API anahtarlarini temizle.

    GUVENLIK: bazi saglayicilar 401 govdesinde gonderilen anahtari geri
    yansitiyor. Bu endpoint 0.0.0.0 uzerinden LAN'a acik oldugu icin ham
    hata metnini oldugu gibi dondurmek anahtar sizdirabilirdi.
    """
    out = str(text)
    for _kname in set(PROVIDER_KEY.values()):
        try:
            v = get_key(_kname)
        except Exception:
            continue
        if v and len(v) >= 8:
            out = out.replace(v, "***")
    return out


async def _probe_list(provider: str, timeout: float) -> dict:
    """GET {base_url}/models — token harcamaz."""
    client = get_client(provider)
    if client is None:
        return {"ok": False, "error": "anahtar yok", "ids": []}
    try:
        page = await asyncio.wait_for(client.models.list(), timeout=timeout)
        ids = sorted({str(getattr(m, "id", "") or "") for m in (page.data or [])} - {""})
        return {"ok": True, "error": None, "ids": ids}
    except Exception as e:
        # Bazi saglayicilar /models sunmuyor; bu bir HATA DEGIL, sadece
        # "oneri veremiyorum" demek. Ping yine de gercegi soyler.
        return {"ok": False, "error": _scrub(f"{type(e).__name__}: {e}"), "ids": []}


async def _probe_ping(provider: str, model: str, timeout: float) -> dict:
    """1 token'lik gercek istek. Model kimligi + erisim dogrulamasi."""
    client = get_client(provider)
    if client is None:
        return {"ok": False, "error": "anahtar yok", "ms": 0}
    t0 = time.time()

    async def _attempt(kwargs):
        return await asyncio.wait_for(
            client.chat.completions.create(model=model, messages=_PING_MESSAGES,
                                           **kwargs), timeout=timeout)
    try:
        await _attempt({"max_tokens": 1})
        return {"ok": True, "error": None, "ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        first = f"{type(e).__name__}: {e}"
        low = first.lower()
        # max_tokens'i reddeden modeller var (akil yurutme modelleri
        # max_completion_tokens istiyor). Bunu "model bozuk" saymak YANLIS
        # negatif olurdu, o yuzden bir kez de sinirsiz deniyoruz.
        if "max_tokens" in low or "max_completion_tokens" in low:
            try:
                await _attempt({})
                return {"ok": True, "error": None,
                        "ms": int((time.time() - t0) * 1000),
                        "note": "max_tokens desteklenmiyor, sinirsiz istek calisti"}
            except Exception as e2:
                first = f"{type(e2).__name__}: {e2}"
        return {"ok": False, "error": _scrub(first),
                "ms": int((time.time() - t0) * 1000)}


def _suggest(model: str, ids: list) -> list:
    """Gecersiz model kimligi icin yakin adlar. Once ayni satici oneki."""
    if not ids:
        return []
    import difflib
    vendor = model.split("/")[0] + "/" if "/" in model else ""
    pool = [i for i in ids if vendor and i.startswith(vendor)] or ids
    out = difflib.get_close_matches(model, pool, n=6, cutoff=0.3)
    if not out:
        out = pool[:6]
    return out


async def probe_all(ping: bool = True, timeout: float = 8.0) -> dict:
    """Her saglayiciyi ve her katmani dener. /test-models bunu dondurur."""
    from config_manager import get_models, get_mode
    models = get_models()
    mode = get_mode()

    # 1) Saglayici bazli model listesi (token harcamaz). PROVIDER_ENDPOINTS'in
    #    TAMAMI taranir -- hicbir katmanin kullanmadigi saglayicilar
    #    (ornegin sambanova) da anahtar dogrulamasi almis olsun.
    provs = sorted(PROVIDER_ENDPOINTS)
    lres = await asyncio.gather(*[_probe_list(p, timeout) for p in provs],
                                return_exceptions=True)
    ids_by_provider, providers = {}, {}
    for p, r in zip(provs, lres):
        if isinstance(r, BaseException):
            r = {"ok": False, "error": _scrub(repr(r)), "ids": []}
        ids_by_provider[p] = r.get("ids") or []
        providers[p] = {
            "endpoint": PROVIDER_ENDPOINTS[p],
            "has_key": bool(get_key(PROVIDER_KEY.get(p, ""))),
            "model_list_ok": bool(r.get("ok")),
            "model_count": len(ids_by_provider[p]),
            "error": r.get("error"),
        }

    # 2) Katman bazli 1 token'lik ping.
    lnames = list(models)
    pings = {}
    if ping:
        pres = await asyncio.gather(
            *[_probe_ping(models[l].get("provider"), models[l].get("model"), timeout)
              for l in lnames], return_exceptions=True)
        for l, r in zip(lnames, pres):
            pings[l] = (r if not isinstance(r, BaseException)
                        else {"ok": False, "error": _scrub(repr(r)), "ms": 0})

    layers, broken = [], []
    for l in lnames:
        prov = models[l].get("provider", "")
        mid = models[l].get("model", "")
        ids = ids_by_provider.get(prov) or []
        listed = (mid in ids) if ids else None      # None = liste alinamadi
        row = {
            "layer": l, "provider": prov, "model": mid,
            "has_key": providers.get(prov, {}).get("has_key", False),
            "model_listed": listed,
            "suggestions": ([] if listed is not False else _suggest(mid, ids)),
            "heavy_only": l in HEAVY_ONLY_LAYERS,
            "allowed_in_mode": layer_allowed(l, mode),
            "ping": pings.get(l) if ping else None,
        }
        layers.append(row)
        if ping and not (row["ping"] or {}).get("ok"):
            broken.append(l)
        elif not ping and listed is False:
            broken.append(l)

    working = [l["layer"] for l in layers if l["layer"] not in broken]
    hint = None
    if broken:
        dead = [l for l in layers
                if l["layer"] in broken and l["model_listed"] is False]
        if dead:
            hint = ("Model kimliği artık sağlayıcının listesinde yok: "
                    + ", ".join(f"{d['layer']}={d['model']}" for d in dead)
                    + ". 'suggestions' alanındaki adlardan birini "
                      "config.json > models > <katman> > model alanına yazın.")
        elif not any(p["has_key"] for p in providers.values()):
            hint = "Hiçbir sağlayıcının anahtarı yok. Ayarlar'dan anahtar girin."
    return {
        "ok": bool(working),
        "mode": mode,
        "pinged": bool(ping),
        "timeout_s": timeout,
        "working": working,
        "broken": broken,
        "layers": layers,
        "providers": providers,
        "hint": hint,
    }
