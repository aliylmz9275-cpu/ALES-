"""
llm_council.py — ALES "LLM Meclisi": ayni soruyu birden fazla modele AYNI
ANDA sorup, yanitlari ANONIMLESTIRIP karistirdiktan sonra bir hakem modele
degerlendirtir ve tek bir final cevap uretir.

NEDEN ANONIMLESTIRME: hakem "bu DeepSeek'in cevabi" diye bilirse marka
onyargisi devreye girer. Yanitlar once karistirilir (shuffle), sonra
"Yanit A / Yanit B / ..." diye etiketlenir. Hakem hangi modelin hangi
etiket oldugunu BILMEZ; eslesme sadece bizde (_Response.label) durur.

STRATEJILER (strategy parametresi):
  * "synthesized"  (varsayilan) — hakem tum yanitlari kaynak alip TEK,
                    butunlesmis bir cevap yazar. En iyi kalite.
  * "best_of_n"    — hakem en iyi yaniti SECER, o yanit AYNEN dondurulur.
                    Sentez riski (hakemin uydurmasi) istenmedigi durumlar.
  * "weighted"     — hakem her yaniti 0-10 puanlar; saglayici guven
                    agirligiyla carpilir, en yuksek toplam kazanir.
  * "majority"     — model bazli oylama: hakem yanitlari anlamsal kumelere
                    ayirir, en kalabalik kume kazanir. Olgusal ("kac eder",
                    "hangi yil") sorularda en saglami.

TASARIM KURALLARI:
  * multi_agent.py'deki cagiricilar YENIDEN YAZILMAZ — _call_gemini,
    _call_sambanova, _call_openrouter, _call_nvidia oradan import edilir.
    Groq ve Cerebras icin model_router'in AsyncOpenAI istemcisi kullanilir
    (o da tek arayuzden konusur), boylece yeni HTTP kodu yazilmaz.
  * HER model kendi timeout'unda kosar (varsayilan 5s, istege gore).
    Yavas olan meclisi bekletmez — gelen yanitlarla devam edilir.
  * Meclis basarisiz olursa (0 yanit / hakem duser) ASLA patlamaz:
    council() {"ok": False} doner, main.py normal router zincirine duser.
  * Sonuclar semantic_cache'e yazilir (namespace="council").
"""

import asyncio
import random
import re
import time

import multi_agent
from config_manager import get_key, get_timeouts

# ─── VARSAYILANLAR ───────────────────────────────────────────────
DEFAULT_TIMEOUT_S = 5.0          # istenen: model basina 5 saniye
JUDGE_TIMEOUT_S = 20.0           # hakem sentez yazar, daha uzun surer
MIN_MEMBERS = 2                  # bu sayidan az yanit gelirse meclis anlamsiz
CACHE_NAMESPACE = "council"

# Saglayici guven agirliklari ("weighted" stratejisi icin). Buyuk/guclu
# modeller biraz daha agir basar; hakemin puani yine de baskin etkendir.
PROVIDER_WEIGHTS = {
    "deepseek": 1.15, "groq": 1.0, "cerebras": 1.0,
    "gemini": 1.05, "openrouter": 0.95, "sambanova": 0.95,
}


class _Response:
    """Tek bir meclis uyesinin yaniti. 'label' anonim etikettir (Yanit A...)."""

    def __init__(self, member: str, provider: str, text: str, elapsed: float):
        self.member = member          # gercek kimlik — hakeme GOSTERILMEZ
        self.provider = provider
        self.text = (text or "").strip()
        self.elapsed = elapsed
        self.label = ""               # anonim etiket, shuffle sonrasi atanir
        self.score = 0.0

    def as_dict(self) -> dict:
        return {"member": self.member, "provider": self.provider,
                "label": self.label, "score": round(self.score, 2),
                "elapsed": round(self.elapsed, 2),
                "chars": len(self.text)}


# ═════════════════════════════════════════════════════════════════
# UYELER — mevcut cagiricilar yeniden kullanilir
# ═════════════════════════════════════════════════════════════════
async def _call_openai_compatible(provider: str, model: str, prompt: str,
                                  system: str) -> tuple:
    """Groq / Cerebras / diger OpenAI-uyumlu saglayicilar icin tek yol.
    model_router'in endpoint+key haritasini kullanir; yeni HTTP kodu yok."""
    try:
        import model_router
        client = model_router.get_client(provider)
        if client is None:
            return False, f"{provider}: key yok"
        r = await client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": prompt}],
            max_tokens=900, temperature=0.6)
        return True, (r.choices[0].message.content or "").strip()
    except Exception as e:
        return False, f"{provider}/{model}: {e}"


def _deepseek_model() -> str:
    """NVIDIA NIM uzerindeki DeepSeek model kimligini config'ten al."""
    try:
        import config_manager
        return config_manager.get_models()["unrestricted"]["model"]
    except Exception:
        return "deepseek-ai/deepseek-v4-pro"


def _member_roster() -> list:
    """Key'i OLAN uyeleri dondur. Key yoksa uye sessizce meclise girmez —
    kullaniciyi "6 model" diye kandirmak yerine gercekte kac tane calisiyorsa
    o kadarini kullaniriz."""
    roster = []

    if get_key("groq_key"):
        roster.append({
            "name": "Groq (Llama 3.3 70B)", "provider": "groq",
            "call": lambda p, s: _call_openai_compatible(
                "groq", "llama-3.3-70b-versatile", p, s)})

    if get_key("cerebras_key"):
        roster.append({
            "name": "Cerebras (Llama 3.3 70B)", "provider": "cerebras",
            "call": lambda p, s: _call_openai_compatible(
                "cerebras", "llama-3.3-70b", p, s)})

    # DeepSeek — NVIDIA NIM uzerinden (multi_agent'taki hazir cagirici).
    # Model kimligi config_manager.DEFAULT_MODELS['unrestricted'] ile AYNI
    # tutulur; boylece Cheat modunda calisan model ile meclis uyesi ayni
    # olur ve tek yerden guncellenir.
    if get_key("nvidia_key"):
        roster.append({
            "name": "DeepSeek V4 (NVIDIA NIM)", "provider": "deepseek",
            "call": lambda p, s: multi_agent._call_nvidia(
                p, s, model=_deepseek_model())})

    if get_key("gemini_key"):
        roster.append({
            "name": "Gemini 2.0 Flash", "provider": "gemini",
            "call": multi_agent._call_gemini})

    if get_key("sambanova_key"):
        roster.append({
            "name": "SambaNova (Llama 3.3 70B)", "provider": "sambanova",
            "call": multi_agent._call_sambanova})

    if get_key("openrouter_key"):
        roster.append({
            "name": "OpenRouter (ucretsiz katman)", "provider": "openrouter",
            "call": multi_agent._call_openrouter})

    return roster


MEMBER_SYSTEM = (
    "Sen bir uzman danismansin. Kullanicinin sorusuna DOGRUDAN, net ve "
    "dogru cevap ver. Turkce yaz. Emin olmadigin bir sey varsa acikca "
    "belirt, UYDURMA. Kisa ve oz ol — en fazla 250 kelime."
)


async def _ask_member(member: dict, prompt: str, timeout_s: float,
                      system: str = None) -> _Response:
    """Tek uyeyi kendi zaman siniriyla cagir. Hata/timeout -> bos metin.

    `system` verilirse MEMBER_SYSTEM yerine o kullanilir — main.py kalici
    sistem promptunu (LUBV) bu yoldan gecirir, boylece meclis yaniti da ayni
    yonergeye tabidir."""
    t0 = time.time()
    try:
        ok, text = await asyncio.wait_for(
            member["call"](prompt, system or MEMBER_SYSTEM), timeout=timeout_s)
    except asyncio.TimeoutError:
        ok, text = False, f"timeout ({timeout_s}s)"
    except Exception as e:
        ok, text = False, str(e)
    return _Response(member["name"], member["provider"],
                     text if ok else "", time.time() - t0)


# ═════════════════════════════════════════════════════════════════
# HAKEM (meta-prompt)
# ═════════════════════════════════════════════════════════════════
JUDGE_SYSTEM = (
    "Sen tarafsiz bir DEGERLENDIRME hakemisin. Sana ayni soruya verilmis "
    "birden fazla ANONIM yanit sunulacak. Hangi modelin hangi yaniti "
    "yazdigini BILMIYORSUN ve tahmin etmeye CALISMA — sadece iceriklerin "
    "kalitesine bak.\n\n"
    "Degerlendirme olcutlerin: (1) olgusal dogruluk, (2) sorunun tamamini "
    "karsilama, (3) somut ve uygulanabilir olma, (4) ic tutarlilik. "
    "Suslu dil ya da uzunluk KALITE DEGILDIR; kisa ama dogru bir yanit, "
    "uzun ama bulanik bir yanittan iyidir. Yanitlar celisiyorsa hangisinin "
    "dogru oldugunu kendi bilginle degerlendir ve celiskiye dikkat cek."
)


async def _run_judge(prompt: str, judge_prompt: str, timeout_s: float,
                     system: str = None) -> tuple:
    """Hakemi cagir. Once en guclu uyeyi dener, duserse sirayla digerlerini."""
    candidates = []
    if get_key("nvidia_key"):
        # Uye listesiyle AYNI model kimligini kullan (config_manager tek kaynak);
        # boylece hakem ile uye farkli DeepSeek surumlerine dusmez.
        candidates.append(("deepseek", lambda p, s: multi_agent._call_nvidia(
            p, s, model=_deepseek_model())))
    if get_key("gemini_key"):
        candidates.append(("gemini", multi_agent._call_gemini))
    if get_key("groq_key"):
        candidates.append(("groq", lambda p, s: _call_openai_compatible(
            "groq", "llama-3.3-70b-versatile", p, s)))
    if get_key("openrouter_key"):
        candidates.append(("openrouter", multi_agent._call_openrouter))

    for name, caller in candidates:
        try:
            ok, text = await asyncio.wait_for(
                caller(judge_prompt, system or JUDGE_SYSTEM), timeout=timeout_s)
            if ok and (text or "").strip():
                return True, text.strip(), name
        except Exception:
            continue
    return False, "", ""


def _anonymize(responses: list) -> list:
    """Yanitlari KARISTIR ve anonim etiket ata. Sira her cagriside farkli
    olur — boylece hakemin 'hep ilki secme' egilimi de kirilir."""
    valid = [r for r in responses if r.text]
    random.shuffle(valid)
    for i, r in enumerate(valid):
        r.label = f"Yanit {chr(65 + i)}"       # Yanit A, Yanit B, ...
    return valid


def _format_for_judge(valid: list) -> str:
    return "\n\n".join(f"### {r.label}\n{r.text}" for r in valid)


def _parse_scores(text: str, valid: list) -> dict:
    """Hakemin puanlarini ayikla: 'Yanit A: 8' / 'Yanit A - 8/10' gibi."""
    scores = {}
    for r in valid:
        letter = r.label.split()[-1]
        m = re.search(rf"Yanit\s*{letter}\s*[:\-–]\s*(\d+(?:[.,]\d+)?)",
                      text, re.IGNORECASE)
        if m:
            try:
                scores[r.label] = float(m.group(1).replace(",", "."))
            except ValueError:
                pass
    return scores


def _pick_label(text: str, valid: list) -> str:
    """Hakemin sectigi kazanan etiketi bul (ilk gecen 'Yanit X')."""
    m = re.search(r"Yanit\s*([A-Z])\b", text or "")
    if not m:
        return ""
    want = f"Yanit {m.group(1)}"
    return want if any(r.label == want for r in valid) else ""


# ═════════════════════════════════════════════════════════════════
# STRATEJILER
# ═════════════════════════════════════════════════════════════════
async def _strategy_synthesized(prompt, valid, timeout_s, judge_system=None):
    jp = (f"KULLANICININ SORUSU:\n{prompt}\n\n"
          f"ASAGIDA {len(valid)} ANONIM YANIT VAR:\n\n{_format_for_judge(valid)}\n\n"
          "GOREV: Bu yanitlari KAYNAK olarak kullanip kullanicinin sorusuna "
          "DOGRUDAN cevap veren, TEK ve akici bir metin yaz. 'Yanit A sunu "
          "dedi' gibi atif YAPMA — kendi cevabinmis gibi yaz. Yanitlar "
          "celisiyorsa dogru olani sec ve celiskiyi kisaca belirt. "
          "Hicbiri yeterli degilse kendi bilginle tamamla.")
    ok, text, judge = await _run_judge(prompt, jp, timeout_s, judge_system)
    if not ok:
        return None
    return {"answer": text, "judge": judge, "winner": None}


async def _strategy_best_of_n(prompt, valid, timeout_s, judge_system=None):
    jp = (f"KULLANICININ SORUSU:\n{prompt}\n\n"
          f"ANONIM YANITLAR:\n\n{_format_for_judge(valid)}\n\n"
          "GOREV: EN IYI yaniti sec. Cevabina TAM OLARAK su formatta basla:\n"
          "KAZANAN: Yanit <harf>\n"
          "Ardindan tek cumlede nedenini yaz. Yanitlari YENIDEN YAZMA.")
    ok, text, judge = await _run_judge(prompt, jp, timeout_s, judge_system)
    if not ok:
        return None
    label = _pick_label(text, valid)
    win = next((r for r in valid if r.label == label), valid[0])
    return {"answer": win.text, "judge": judge, "winner": win}


async def _strategy_weighted(prompt, valid, timeout_s, judge_system=None):
    jp = (f"KULLANICININ SORUSU:\n{prompt}\n\n"
          f"ANONIM YANITLAR:\n\n{_format_for_judge(valid)}\n\n"
          "GOREV: HER yaniti 0-10 arasi puanla. Once SADECE puanlari su "
          "formatta yaz (her biri ayri satir):\n"
          "Yanit A: <puan>\nYanit B: <puan>\n...\n"
          "Sonra en yuksek puanli yanitin neden kazandigini tek cumleyle yaz.")
    ok, text, judge = await _run_judge(prompt, jp, timeout_s, judge_system)
    if not ok:
        return None
    scores = _parse_scores(text, valid)
    if not scores:
        return None
    for r in valid:
        base = scores.get(r.label, 0.0)
        r.score = base * PROVIDER_WEIGHTS.get(r.provider, 1.0)
    win = max(valid, key=lambda r: r.score)
    return {"answer": win.text, "judge": judge, "winner": win}


def _similarity(a: str, b: str) -> float:
    """Bagimliliksiz kelime-kumesi (Jaccard) benzerligi."""
    ta = set(re.findall(r"\w+", (a or "").lower()))
    tb = set(re.findall(r"\w+", (b or "").lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


async def _strategy_majority(prompt, valid, timeout_s, judge_system=None):
    """Anlamsal kumeleme ile oylama. Hakem cagrisi GEREKTIRMEZ — olgusal
    sorularda modeller ayni seyi soyluyorsa o cevap kazanir."""
    clusters = []
    for r in valid:
        for c in clusters:
            if _similarity(r.text, c[0].text) >= 0.45:
                c.append(r)
                break
        else:
            clusters.append([r])
    clusters.sort(key=len, reverse=True)
    top = clusters[0]
    if len(top) < 2 and len(valid) > 2:
        # Uzlasma yok -> sentezle (daha guvenli)
        return await _strategy_synthesized(prompt, valid, timeout_s, judge_system)
    win = max(top, key=lambda r: len(r.text))
    return {"answer": win.text, "judge": f"oylama ({len(top)}/{len(valid)} uzlasti)",
            "winner": win, "consensus": len(top)}


STRATEGIES = {
    "synthesized": _strategy_synthesized,
    "best_of_n": _strategy_best_of_n,
    "weighted": _strategy_weighted,
    "majority": _strategy_majority,
}


# ═════════════════════════════════════════════════════════════════
# ANA GIRIS
# ═════════════════════════════════════════════════════════════════
def _ns(system_extra: str) -> str:
    """Onbellek ad alani kalici sistem promptuna BAGLIDIR.

    NEDEN: LUBV acilip kapandiginda ya da metni degistiginde eski yanitlar
    servis edilmemeli — onlar BASKA bir yonergeyle uretilmisti. Ad alanina
    metnin kisa parmak izini koyarak her yonerge kendi onbellegini kullanir;
    yonerge geri alinirsa eski onbellek yine gecerli olur."""
    s = (system_extra or "").strip()
    if not s:
        return CACHE_NAMESPACE
    h = 0
    for ch in s:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return f"{CACHE_NAMESPACE}:{h:08x}"


async def council(prompt: str, strategy: str = "synthesized",
                  timeout_s: float = None, judge_timeout_s: float = None,
                  use_cache: bool = True, progress_cb=None,
                  system_extra: str = None) -> dict:
    """Meclisi calistir.

    Doner: {ok, answer, strategy, members[], judge, elapsed, cached}
    ok=False ise cagiran NORMAL router zincirine dusmelidir (asla patlamaz).

    system_extra: kalici sistem promptu (LUBV). Verilirse HEM uyelerin HEM
    hakemin sistem mesajinin BASINA eklenir — meclis yolu run_agent'taki
    enjeksiyondan once dondugu icin, yonergenin meclis yanitlarina da
    islemesinin tek yolu budur.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "error": "bos istem"}

    strategy = strategy if strategy in STRATEGIES else "synthesized"
    timeout_s = float(timeout_s or DEFAULT_TIMEOUT_S)
    judge_timeout_s = float(judge_timeout_s or JUDGE_TIMEOUT_S)
    t0 = time.time()
    cb = progress_cb or (lambda m: None)

    extra = (system_extra or "").strip()
    member_sys = (extra + "\n\n" + MEMBER_SYSTEM) if extra else MEMBER_SYSTEM
    judge_sys = (extra + "\n\n" + JUDGE_SYSTEM) if extra else JUDGE_SYSTEM
    ns = _ns(extra)

    # ── 1) CACHE ────────────────────────────────────────────────
    if use_cache:
        try:
            import semantic_cache
            hit = semantic_cache.lookup(prompt, namespace=ns)
            if hit and hit.get("answer"):
                return {"ok": True, "answer": hit["answer"], "cached": True,
                        "strategy": strategy, "members": [], "judge": None,
                        "elapsed": time.time() - t0}
        except Exception:
            pass

    # ── 2) UYELER ───────────────────────────────────────────────
    roster = _member_roster()
    if len(roster) < MIN_MEMBERS:
        return {"ok": False, "error": f"meclis icin en az {MIN_MEMBERS} saglayici "
                                      f"key'i gerekli (su an {len(roster)})"}

    cb(f"{len(roster)} model paralel calisiyor...")
    responses = await asyncio.gather(
        *[_ask_member(m, prompt, timeout_s, member_sys) for m in roster],
        return_exceptions=False)

    # ── 3) ANONIMLESTIR + KARISTIR ──────────────────────────────
    valid = _anonymize(list(responses))
    if not valid:
        return {"ok": False, "error": "hicbir uye yanit vermedi"}
    if len(valid) == 1:
        # Tek yanit — hakeme gerek yok, dogrudan dondur.
        only = valid[0]
        _store(prompt, only.text, use_cache, ns)
        return {"ok": True, "answer": only.text, "strategy": "single",
                "members": [r.as_dict() for r in responses], "judge": None,
                "elapsed": time.time() - t0, "cached": False}

    # ── 4) HAKEM / STRATEJI ─────────────────────────────────────
    cb(f"{len(valid)} yanit degerlendiriliyor ({strategy})...")
    try:
        result = await STRATEGIES[strategy](prompt, valid, judge_timeout_s, judge_sys)
    except Exception as e:
        result = None
        print(f"[COUNCIL] strateji hatasi ({strategy}): {e}")

    if not result or not (result.get("answer") or "").strip():
        # Hakem duserse: en uzun/en dolu yaniti dondur (bos donmekten iyi).
        fb = max(valid, key=lambda r: len(r.text))
        result = {"answer": fb.text, "judge": None, "winner": fb,
                  "degraded": True}

    answer = result["answer"]
    _store(prompt, answer, use_cache, ns)

    win = result.get("winner")
    return {
        "ok": True,
        "answer": answer,
        "strategy": strategy,
        "judge": result.get("judge"),
        "winner": win.member if win else None,
        "consensus": result.get("consensus"),
        "degraded": bool(result.get("degraded")),
        "members": [r.as_dict() for r in responses],
        "responded": len(valid),
        "asked": len(roster),
        "elapsed": round(time.time() - t0, 2),
        "cached": False,
    }


def _store(prompt: str, answer: str, use_cache: bool, namespace: str = None):
    if not use_cache or not (answer or "").strip():
        return
    try:
        import semantic_cache
        semantic_cache.store(prompt, answer,
                             namespace=namespace or CACHE_NAMESPACE)
    except Exception:
        pass


def council_sync(prompt: str, strategy: str = "synthesized", **kw) -> dict:
    """Senkron sarmalayici (arac/test icinden cagrilabilir)."""
    return asyncio.run(council(prompt, strategy=strategy, **kw))


def status() -> dict:
    """UI/teshis: meclis su an calisabilir mi, kim uye?"""
    roster = _member_roster()
    return {
        "available": len(roster) >= MIN_MEMBERS,
        "member_count": len(roster),
        "members": [{"name": m["name"], "provider": m["provider"]} for m in roster],
        "strategies": list(STRATEGIES),
        "min_members": MIN_MEMBERS,
        "default_timeout_s": DEFAULT_TIMEOUT_S,
    }
