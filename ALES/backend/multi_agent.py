"""
ALES Multi-Agent Analiz Motoru

"Derin analiz yap", "4 ai ne dusunur" (5 oldu ama tetikleyici kelimeler
ayni kaldi), "tartis" gibi isteklerde ALES bu motoru calistirir. 5 farkli
AI paralel calisir, her biri KISA bir gorus verir, sonra bu gorusler
"kaynak" gibi kullanilarak TEK, butunlesmis bir final cevap yazilir.

ONEMLI TASARIM KARARI (Ali'nin istegi uzerine): eskiden ilk-gorusler +
tartisma-turu + supervisor-sentezi ayri ayri, uzun uzun gosteriliyordu.
Artik kullaniciya SADECE final sentez gosteriliyor - 5 AI'nin kendi
metinleri ekrana hic basilmiyor, sadece supervisor'in ic promptuna
"kaynak" olarak besleniyor. Bu hem uzunlugu hem de "bazilari konusmuyor"
hissini azaltir (tek round, daha az API cagrisi = daha az hata yuzeyi).

API Key'ler config_manager uzerinden AppData'dan okunur (veya cloud'da
env degiskeninden). Yoksa ilgili agent atlanir, calisanlarla devam edilir.

DAYANIKLILIK:
- Bir AI rate limit (429) veya baska bir hataya takilirsa, once OpenRouter
  uzerinden ucretsiz bir modelle otomatik yedekleme denenir.
- O da basarisiz olursa o agent'in gorusu olmadan devam edilir.
- Final cevabin sonunda hangi AI'in neden katilamadigi kisaca belirtilir
  (uzun aciklama degil, tek satir).
"""
import asyncio
import os
import time
from typing import Optional

# ─── HATA SINIFLANDIRMA ───────────────────────────────────────────

def _is_rate_limit(err: Exception) -> bool:
    s = str(err).lower()
    return "429" in s or "rate limit" in s or "rate_limit" in s or "quota" in s

def _is_dead_model(err: Exception) -> bool:
    s = str(err).lower()
    return (
        "404" in s
        or "model_not_found" in s
        or "does not exist" in s
        or "decommissioned" in s
        or "resource_not_found" in s
        or "deprecated" in s
        or "not found" in s
    )

try:
    import model_registry
except ImportError:
    model_registry = None

# ─── API CAGIRICILARI (her biri (basarili: bool, metin: str) doner) ─

import functools

async def _call_nvidia(prompt: str, system: str, model: str) -> tuple[bool, str]:
    """
    Tek NVIDIA NIM cagiricisi (build.nvidia.com) - OpenAI-uyumlu tek
    endpoint uzerinden TUM modellere erisir. Tek key (nvidia_key) yeter,
    hangi model kullanilacagi asagida her agent icin functools.partial
    ile sabitlenir.
    """
    try:
        from openai import AsyncOpenAI
        from config_manager import load_config
        key = load_config().get("nvidia_key", "") or os.environ.get("NVIDIA_API_KEY", "")
        if not key:
            return False, "NVIDIA key eksik - build.nvidia.com'dan al"
        client = AsyncOpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=key)
        last_err = "bilinmeyen hata"
        for attempt in range(3):
            try:
                r = await client.chat.completions.create(
                    model=model,
                    messages=[{"role":"system","content":system},{"role":"user","content":prompt}],
                    max_tokens=700, temperature=0.7,
                )
                return True, r.choices[0].message.content.strip()
            except Exception as e:
                last_err = str(e)
                if _is_rate_limit(e):
                    await asyncio.sleep(2 ** attempt)
                else:
                    return False, f"NVIDIA hata ({model}): {e}"
        return False, f"NVIDIA ({model}): rate limit asildi ({last_err})"
    except ImportError:
        return False, "openai kutuphanesi kurulu degil (pip install openai)"
    except Exception as e:
        return False, f"NVIDIA beklenmeyen hata ({model}): {e}"

# Her agent icin ayri model sabitleyen kisayollar - hepsi ayni
# NVIDIA anahtarini kullanir, sadece model adi degisir.
_call_deepseek_v4 = functools.partial(_call_nvidia, model="deepseek-ai/deepseek-v4")
_call_deepseek_v4_flash = functools.partial(_call_nvidia, model="deepseek-ai/deepseek-v4-flash")
_call_glm51 = functools.partial(_call_nvidia, model="zhipuai/glm-5.1")
_call_qwen3_coder = functools.partial(_call_nvidia, model="qwen/qwen3-coder-480b-a35b-instruct")

async def _call_groq(prompt: str, system: str) -> tuple[bool, str]:
    """Groq Cloud cagiricisi (dinamik model secimi + 404 self-healing)."""
    try:
        from config_manager import get_key
        key = get_key("groq_key") or os.environ.get("GROQ_API_KEY", "")
        if not key:
            return False, "Groq key eksik"
        try:
            from groq import AsyncGroq
            client = AsyncGroq(api_key=key)
        except ImportError:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(base_url="https://api.groq.com/openai/v1", api_key=key)

        model_name = "openai/gpt-oss-120b"
        if model_registry and hasattr(model_registry, "registry"):
            model_name = model_registry.registry.effective_model("groq", model_name)

        for attempt in range(3):
            try:
                r = await client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": prompt}],
                    max_tokens=1500, temperature=0.6,
                )
                return True, (r.choices[0].message.content or "").strip()
            except Exception as e:
                if _is_dead_model(e) and model_registry and hasattr(model_registry, "registry"):
                    try:
                        alt = await model_registry.registry.heal("groq", model_name, str(e))
                        if alt and alt != model_name:
                            model_name = alt
                            continue
                    except Exception:
                        pass
                if _is_rate_limit(e):
                    await asyncio.sleep(2 ** attempt)
                else:
                    return False, f"Groq hata: {e}"
        return False, "Groq: rate limit asildi"
    except Exception as e:
        return False, f"Groq beklenmeyen hata: {e}"


async def _call_cerebras(prompt: str, system: str) -> tuple[bool, str]:
    """Cerebras Cloud cagiricisi (dinamik model secimi + 404 self-healing)."""
    try:
        from config_manager import get_key
        key = get_key("cerebras_key") or os.environ.get("CEREBRAS_API_KEY", "")
        if not key:
            return False, "Cerebras key eksik"
        try:
            from cerebras.cloud.sdk import AsyncCerebras
            client = AsyncCerebras(api_key=key)
        except ImportError:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(base_url="https://api.cerebras.ai/v1", api_key=key)

        model_name = "gpt-oss-120b"
        if model_registry and hasattr(model_registry, "registry"):
            model_name = model_registry.registry.effective_model("cerebras", model_name)

        for attempt in range(3):
            try:
                r = await client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": prompt}],
                    max_tokens=1500, temperature=0.6,
                )
                return True, (r.choices[0].message.content or "").strip()
            except Exception as e:
                if _is_dead_model(e) and model_registry and hasattr(model_registry, "registry"):
                    try:
                        alt = await model_registry.registry.heal("cerebras", model_name, str(e))
                        if alt and alt != model_name:
                            model_name = alt
                            continue
                    except Exception:
                        pass
                if _is_rate_limit(e):
                    await asyncio.sleep(2 ** attempt)
                else:
                    return False, f"Cerebras hata: {e}"
        return False, "Cerebras: rate limit asildi"
    except Exception as e:
        return False, f"Cerebras beklenmeyen hata: {e}"

async def _call_gemini(prompt: str, system: str) -> tuple[bool, str]:
    """Google Gemini OpenAI-uyumlu endpoint (dinamik model secimi + 404 self-healing)."""
    try:
        from openai import AsyncOpenAI
        from config_manager import get_key
        key = get_key("gemini_key")
        if not key:
            return False, "Gemini key eksik"
        client = AsyncOpenAI(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=key)

        model_name = "gemini-3.8-flash"
        if model_registry and hasattr(model_registry, "registry"):
            model_name = model_registry.registry.effective_model("gemini", model_name)

        for attempt in range(3):
            try:
                r = await client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": prompt}],
                    max_tokens=1500, temperature=0.6)
                return True, (r.choices[0].message.content or "").strip()
            except Exception as e:
                if _is_dead_model(e) and model_registry and hasattr(model_registry, "registry"):
                    try:
                        alt = await model_registry.registry.heal("gemini", model_name, str(e))
                        if alt and alt != model_name:
                            model_name = alt
                            continue
                    except Exception:
                        pass
                if _is_rate_limit(e):
                    await asyncio.sleep(2 ** attempt)
                else:
                    return False, f"Gemini hata: {e}"
        return False, "Gemini: rate limit asildi"
    except ImportError:
        return False, "openai kutuphanesi kurulu degil"
    except Exception as e:
        return False, f"Gemini beklenmeyen hata: {e}"


async def _call_sambanova(prompt: str, system: str) -> tuple[bool, str]:
    """SambaNova Cloud OpenAI-uyumlu endpoint (dinamik model secimi + 404 self-healing)."""
    try:
        from openai import AsyncOpenAI
        from config_manager import get_key
        key = get_key("sambanova_key")
        if not key:
            return False, "SambaNova key eksik"
        client = AsyncOpenAI(base_url="https://api.sambanova.ai/v1", api_key=key)

        model_name = "Meta-Llama-3.3-70B-Instruct"
        if model_registry and hasattr(model_registry, "registry"):
            model_name = model_registry.registry.effective_model("sambanova", model_name)

        for attempt in range(3):
            try:
                r = await client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": prompt}],
                    max_tokens=1500, temperature=0.6)
                return True, (r.choices[0].message.content or "").strip()
            except Exception as e:
                if _is_dead_model(e) and model_registry and hasattr(model_registry, "registry"):
                    try:
                        alt = await model_registry.registry.heal("sambanova", model_name, str(e))
                        if alt and alt != model_name:
                            model_name = alt
                            continue
                    except Exception:
                        pass
                if _is_rate_limit(e):
                    await asyncio.sleep(2 ** attempt)
                else:
                    return False, f"SambaNova hata: {e}"
        return False, "SambaNova: rate limit asildi"
    except ImportError:
        return False, "openai kutuphanesi kurulu degil"
    except Exception as e:
        return False, f"SambaNova beklenmeyen hata: {e}"


async def _call_openrouter(prompt: str, system: str) -> tuple[bool, str]:
    """
    Ucretsiz yedek katman. Diger 5 AI'dan biri hata verirse ayni rolu
    OpenRouter'in ucretsiz (:free) modelleriyle doldurur. Sirada once
    NVIDIA'nin Nemotron 3 Super/Ultra modelleri denenir (120B/550B MoE,
    ucretsiz katmanda hizli ve guclu - Groq'ta henuz mevcut degil ama
    OpenRouter uzerinden ücretsiz erisilebiliyor), sonra diger yedekler.
    Key yoksa sessizce basarisiz doner (ALES calismaya devam eder).
    """
    try:
        import httpx
        from config_manager import load_config
        key = load_config().get("openrouter_key", "") or os.environ.get("OPENROUTER_API_KEY", "")
        if not key:
            return False, "OpenRouter key eksik - openrouter.ai"
        free_models = [
            "nvidia/nemotron-3-super-120b-a12b:free",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "deepseek/deepseek-r1:free",
            "qwen/qwen3-235b-a22b:free",
        ]
        async with httpx.AsyncClient(timeout=45) as client:
            last_err = "bilinmeyen hata"
            for model in free_models:
                try:
                    r = await client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                        json={"model": model, "messages":[{"role":"system","content":system},{"role":"user","content":prompt}], "max_tokens":700, "temperature":0.7},
                    )
                    if r.status_code == 429:
                        last_err = f"{model}: 429 rate limit"
                        continue
                    r.raise_for_status()
                    return True, r.json()["choices"][0]["message"]["content"].strip()
                except Exception as e:
                    last_err = f"{model}: {e}"
                    continue
        return False, f"OpenRouter: {last_err}"
    except ImportError:
        return False, "httpx kutuphanesi kurulu degil"
    except Exception as e:
        return False, f"OpenRouter beklenmeyen hata: {e}"

# ─── AGENT TANIMLARI (5 AI) ───────────────────────────────────────

AGENTS = [
    {
        "name": "Arastirmaci",
        "emoji": "🔬",
        "provider": "NVIDIA (DeepSeek V4)",
        "system": (
            "Sen deneyimli bir arastirmacisin. Kanit ve veri odakli dusunursun. "
            "Turkce yaz, kisa ve oz ol. Maksimum 130 kelime."
        ),
        "caller": _call_deepseek_v4,
    },
    {
        "name": "Yazar",
        "emoji": "✍️",
        "provider": "NVIDIA (GLM 5.1)",
        "system": (
            "Sen yaratici ve analitik bir yazarsin. Insan boyutunu on plana "
            "cikarirsin. Turkce yaz, kisa ve oz ol. Maksimum 130 kelime."
        ),
        "caller": _call_glm51,
    },
    {
        "name": "Elestirmen",
        "emoji": "🧐",
        "provider": "NVIDIA (DeepSeek V4 Flash)",
        "system": (
            "Sen elestirel dusuncenin ustasisin. Zayif noktalari ve alternatif "
            "bakis acilarini tespit edersin. Turkce yaz, kisa ve oz ol. "
            "Maksimum 130 kelime."
        ),
        "caller": _call_deepseek_v4_flash,
    },
    {
        "name": "Analist",
        "emoji": "📊",
        "provider": "NVIDIA (Qwen3 Coder 480B)",
        "system": (
            "Sen veri odakli bir analistsin. Sistemik ve istatistiksel acidan "
            "degerlendirirsin. Turkce yaz, kisa ve oz ol. Maksimum 130 kelime."
        ),
        "caller": _call_qwen3_coder,
    },
    {
        "name": "Stratejist",
        "emoji": "🎯",
        "provider": "NVIDIA (GLM 5.1)",
        "system": (
            "Sen pragmatik bir strateji uzmanisin. Konuyu somut, uygulanabilir "
            "adimlara donusturursun, riskleri ve firsatlari tartar, net bir "
            "yon onerirsin. Turkce yaz, kisa ve eyleme donuk ol. "
            "Maksimum 130 kelime."
        ),
        "caller": _call_glm51,
    },
]

# Supervisor (final sentez) icin DeepSeek V4 kullaniliyor - NVIDIA NIM
# katalogundaki en guclu akil yurutme modeli, 5 farkli gorusu tutarli
# tek bir cevaba sentezlemek gibi zor bir is icin en uygunu.
SUPERVISOR_SYSTEM = (
    "Sen cok perspektifli bir sentez uzmanisin. Sana birden fazla uzmanin "
    "BAGIMSIZ gorusu kaynak olarak verilecek. Bunlari 'X sunu dedi, Y bunu "
    "dedi' diye ayri ayri OZETLEME - hepsini bir arastirmaci gibi kaynak "
    "olarak kullanip, kullanicinin sorusuna DOGRUDAN cevap veren, akici, "
    "TEK bir metin yaz. Kendi cevabinmis gibi yaz, kaynaklara atif yapma. "
    "Turkce yaz. Net ve eyleme donusturulebilir ol. Maksimum 350 kelime."
)

# ─── DAYANIKLI AGENT CAGRISI (asil AI + OpenRouter yedegi) ────────

async def _call_agent_resilient(agent: dict, prompt: str) -> dict:
    """
    Once agent'in kendi AI'ini dener. Basarisiz olursa OpenRouter ile
    ayni rolu doldurmaya calisir. Sonucta durum bilgisini de dondurur:
    status: "ok" (asil AI calisti) | "fallback" (OpenRouter devreye girdi) | "failed" (ikisi de basarisiz)
    """
    ok, text = await agent["caller"](prompt, agent["system"])
    if ok:
        return {"text": text, "status": "ok", "primary_error": None}

    primary_error = text
    ok2, text2 = await _call_openrouter(prompt, agent["system"])
    if ok2:
        return {"text": text2, "status": "fallback", "primary_error": primary_error}

    return {"text": None, "status": "failed", "primary_error": primary_error, "fallback_error": text2}

# ─── YENİ NESİL MANAGER-EXECUTOR MİMARİSİNE YÖNLENDİRME ─────────

async def run_multi_agent_discussion(
    topic: str,
    progress_callback=None,
) -> str:
    """
    Manager-Executor mimarisi üzerinden hedefi alt adımlara böler,
    öğrenilmiş kuralları plana dahil eder ve adımları güvenle yürütür.
    """
    try:
        import manager_agent
        return await manager_agent.run_goal(topic, progress_callback)
    except Exception as e:
        print(f"[MULTI_AGENT] manager_agent hatası, klasik senteze dönülüyor: {e}")

    cb = progress_callback or (lambda m: None)
    start = time.time()
    notes = []

    cb("5 AI görüşlerini topluyor...")
    r1_prompt = (
        f"Konu: {topic}\n\n"
        "Bu konu hakkinda kendi uzmanlik alanin cercevesinde kisa ve ozlu bir gorus yaz."
    )
    r1_tasks = [_call_agent_resilient(a, r1_prompt) for a in AGENTS]
    r1_raw = await asyncio.gather(*r1_tasks)

    sources = {}  # SADECE supervisor'a girdi - kullaniciya gosterilmiyor
    for agent, res in zip(AGENTS, r1_raw):
        if res["status"] == "ok":
            sources[agent["name"]] = res["text"]
        elif res["status"] == "fallback":
            sources[agent["name"]] = res["text"]
            notes.append(f"⚠️ {agent['name']} ({agent['provider']}) → OpenRouter yedegiyle devam edildi.")
        else:
            notes.append(f"❌ {agent['name']} ({agent['provider']}) yanit veremedi: {res['primary_error']}")

    if not sources:
        return (
            f"🤖 **5 AI Analizi** — {topic}\n\n"
            "❌ Hicbir AI'dan yanit alinamadi.\n\n" + "\n".join(notes)
        )

    cb("Görüşler tek bir cevapta birleştiriliyor...")

    sources_text = "\n\n".join(f"[{name}]: {text}" for name, text in sources.items())
    supervisor_prompt = (
        f"KULLANICININ KONUSU: {topic}\n\n"
        f"ASAGIDA {len(sources)} FARKLI UZMANIN BAGIMSIZ GORUSU VAR (bunlar "
        f"SADECE senin icin ham kaynak, kullaniciya ayri gosterilmeyecek):\n\n"
        f"{sources_text}\n\n"
        "Bu gorusleri kaynak olarak kullanarak kullanicinin konusuna DOGRUDAN "
        "cevap veren, TEK ve akici bir metin yaz."
    )

    final = None
    sup_ok, sup_text = await _call_deepseek_v4(supervisor_prompt, SUPERVISOR_SYSTEM)
    if sup_ok:
        final = sup_text
    else:
        notes.append(f"⚠️ Sentez icin DeepSeek V4 basarisiz oldu, yedek deneniyor. Sebep: {sup_text}")
        for caller in (_call_glm51, _call_qwen3_coder, _call_deepseek_v4_flash):
            ok, text = await caller(supervisor_prompt, SUPERVISOR_SYSTEM)
            if ok:
                final = text
                break
        if final is None:
            ok, text = await _call_openrouter(supervisor_prompt, SUPERVISOR_SYSTEM)
            if ok:
                final = text
            else:
                final = "[Sentez yapilamadi, tum AI saglayicilari basarisiz oldu.]"
                notes.append(f"❌ Final sentez de basarisiz oldu. Sebep: {text}")

    elapsed = time.time() - start
    lines = [f"🤖 **5 AI Analizi** — {topic}\n", final]
    if notes:
        lines.append("\n---")
        lines.extend(notes)
    lines.append(f"\n_{len(sources)}/5 AI katildi · {elapsed:.1f}s_")
    return "\n".join(lines)


def run_discussion_sync(topic: str, progress_callback=None) -> str:
    """Sync wrapper - execute_tool icinden cagrilabilir"""
    return asyncio.run(run_multi_agent_discussion(topic, progress_callback))
