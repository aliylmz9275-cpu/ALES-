"""
mixture_of_agents.py — MoA (Mixture of Agents) ve DMoA (Dynamic MoA) Entegrasyonu.

Referanslar:
  - "Mixture-of-Agents Enhances Large Language Model Capabilities" (ICLR 2025).
  - "Balancing Act: Diversity and Consistency in Large Language Model Ensembles" (DMoA, ICLR 2025).

Mimari:
  1. Katman 1 (Önericiler / Proposers):
     Farklı açık kaynaklı modeller (Cerebras, Groq, NVIDIA DeepSeek, Gemini, OpenRouter)
     aynı göreve paralel olarak yanıt üretir.
  2. Katman 2 (Dinamik Çeşitlilik Dengeleyici / DMoA Balancer):
     Öneriler arasındaki anlamsal çeşitlilik (diversity) ile tutarlılığı (consistency) tartar.
  3. Katman 3 (Hakem / Sentezleyici - Judge):
     Önerileri kör (anonymized) olarak puanlar ve tek bir üstün nihai yanıt sentezler.
"""
import asyncio
import difflib
import random
import time
from typing import Any, Dict, List, Optional, Tuple

import model_router
from config_manager import get_key, get_models

_stats = {
    "moa_runs": 0,
    "proposals_generated": 0,
    "synthesized_answers": 0,
    "dmoa_balanced": 0,
    "avg_elapsed_s": 0.0,
}

# Varsayılan önerici katmanları
PROPOSER_LAYERS = ["fast", "fallback", "vision", "code", "unrestricted"]

async def _query_proposer(layer_name: str, messages: list, timeout_s: float = 10.0) -> Optional[Dict[str, Any]]:
    models = get_models()
    if layer_name not in models:
        return None
    layer_cfg = models[layer_name]
    prov = layer_cfg.get("provider")
    mid = layer_cfg.get("model")
    if not model_router.get_client(prov):
        return None

    t0 = time.time()
    try:
        res = await model_router._call_layer(
            {"layer": layer_name, "provider": prov, "model": mid},
            messages,
            timeout=timeout_s,
            max_tokens=1500,
            temperature=0.7,
        )
        if res.get("ok"):
            return {
                "layer": layer_name,
                "provider": prov,
                "model": mid,
                "content": res.get("content", ""),
                "elapsed": round(time.time() - t0, 3),
            }
    except Exception as e:
        pass
    return None

def compute_diversity_score(texts: List[str]) -> float:
    """Aday metinler arasındaki ortalama metin farkını (0.0=özdeş, 1.0=tamamen farklı) hesaplar."""
    if len(texts) < 2:
        return 0.0
    diffs = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            ratio = difflib.SequenceMatcher(None, texts[i][:500], texts[j][:500]).ratio()
            diffs.append(1.0 - ratio)
    return round(sum(diffs) / len(diffs), 4) if diffs else 0.0

async def run_moa(prompt: str, system: str = "", max_proposers: int = 4,
                  judge_layer: str = "heavy") -> Dict[str, Any]:
    """
    Standart MoA döngüsü:
    1. Önericileri paralel çalıştırır.
    2. Yanıtları toplar ve anonimleştirir.
    3. Hakem modeline (Kimi K3 veya en güçlü açık katman) değerlendirtip sentezletir.
    """
    t0 = time.time()
    _stats["moa_runs"] += 1

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # 1. Önericileri çağır
    tasks = [_query_proposer(l, messages, timeout_s=12.0) for l in PROPOSER_LAYERS[:max_proposers]]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    proposals = [r for r in results if isinstance(r, dict) and r.get("content")]

    _stats["proposals_generated"] += len(proposals)

    if not proposals:
        # Yedek: Normal router zincirine düş
        res = await model_router.route_chat(messages, max_tokens=2048)
        return {
            "ok": res.get("ok", False),
            "content": res.get("content", ""),
            "mode": "fallback_single",
            "proposers_count": 0,
            "elapsed": round(time.time() - t0, 3),
        }

    # Tek bir önerici geldiyse doğrudan döndür
    if len(proposals) == 1:
        return {
            "ok": True,
            "content": proposals[0]["content"],
            "mode": "single_proposer",
            "proposers_count": 1,
            "proposals": proposals,
            "elapsed": round(time.time() - t0, 3),
        }

    # 2. Anonimleştir ve Hakem için bağlam hazırla
    random.shuffle(proposals)
    judge_prompt = "Aşağıda aynı soruya farklı bağımsız uzman modeller tarafından üretilmiş aday yanıtlar yer almaktadır:\n\n"
    for i, p in enumerate(proposals):
        label = chr(65 + i)  # A, B, C...
        p["label"] = f"Yanıt {label}"
        judge_prompt += f"=== {p['label']} ===\n{p['content']}\n\n"

    judge_prompt += (
        f"Kullanıcının asıl sorusu: '{prompt}'\n\n"
        "GÖREV: Yukarıdaki aday yanıtların en doğru, eksiksiz ve güçlü yönlerini birleştirerek "
        "en üstün nihai cevabı sentezle. Hangi modelin hangi yanıt olduğunu belirtme; "
        "yalnızca doğrudan, akıcı ve eksiksiz sentez yanıtı ver."
    )

    # 3. Hakem modeli çağır
    models = get_models()
    j_cfg = models.get(judge_layer, models.get("unrestricted", models.get("fast")))
    judge_client = model_router.get_client(j_cfg.get("provider"))

    if not judge_client:
        # Hakem anahtarı yoksa en uzun/kapsamlı öneriyi seç
        best = max(proposals, key=lambda x: len(x["content"]))
        return {
            "ok": True,
            "content": best["content"],
            "mode": "best_length_fallback",
            "proposers_count": len(proposals),
            "proposals": proposals,
            "elapsed": round(time.time() - t0, 3),
        }

    judge_messages = [
        {"role": "system", "content": "Sen tarafsız, üst düzey bir sentezleyici ve hakem yapay zekasın."},
        {"role": "user", "content": judge_prompt},
    ]

    try:
        j_res = await model_router._call_layer(
            j_cfg, judge_messages, timeout=25.0, max_tokens=3000, temperature=0.3
        )
        final_content = j_res.get("content") if j_res.get("ok") else proposals[0]["content"]
    except Exception:
        final_content = proposals[0]["content"]

    _stats["synthesized_answers"] += 1
    elapsed = round(time.time() - t0, 3)
    tot = _stats["moa_runs"]
    _stats["avg_elapsed_s"] = round((_stats["avg_elapsed_s"] * (tot - 1) + elapsed) / tot, 2)

    return {
        "ok": True,
        "content": final_content,
        "mode": "moa_synthesized",
        "proposers_count": len(proposals),
        "proposals": proposals,
        "diversity_score": compute_diversity_score([p["content"] for p in proposals]),
        "elapsed": elapsed,
    }

async def run_dmoa(prompt: str, system: str = "", diversity_threshold: float = 0.35) -> Dict[str, Any]:
    """
    Dynamic MoA (DMoA):
    Önericiler arasındaki anlamsal farkı ölçer.
    Eğer modeller zaten hemfikirse (düşük çeşitlilik), hakem sentezini atlayıp en hızlı yanıtı onaylar.
    Eğer görüş ayrılığı varsa (yüksek çeşitlilik), MoA hakem sentezini devreye sokar.
    """
    _stats["dmoa_balanced"] += 1
    t0 = time.time()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # İlk 3 hızlı önericiyi çalıştır
    tasks = [_query_proposer(l, messages, timeout_s=8.0) for l in ["fast", "fallback", "vision"]]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    proposals = [r for r in results if isinstance(r, dict) and r.get("content")]

    if not proposals:
        return await run_moa(prompt, system=system)

    div_score = compute_diversity_score([p["content"] for p in proposals])

    if div_score < diversity_threshold and len(proposals) >= 2:
        # Konsensüs sağlandı: en hızlı gelen önericiyi döndür
        fastest = min(proposals, key=lambda x: x.get("elapsed", 99.0))
        return {
            "ok": True,
            "content": fastest["content"],
            "mode": "dmoa_consensus_fastpath",
            "diversity_score": div_score,
            "proposers_count": len(proposals),
            "proposals": proposals,
            "elapsed": round(time.time() - t0, 3),
        }

    # Çeşitlilik yüksek: tam MoA sentezi uygula
    return await run_moa(prompt, system=system, max_proposers=4)

def stats() -> Dict[str, Any]:
    return dict(_stats)


def info() -> Dict[str, Any]:
    """runtime_state.refresh_modules() bunu okur.

    available: router katmanlarini kullanir, ek bagimlilik yok — ama
    "acik" olmasi PAHALIDIR: her cagri 3-4 onerici + 1 hakem, yani tek
    soruya 4-5 model cagrisi. Bu yuzden heavy_local=True isaretli ve
    yalnizca Multi modunda, arac gerektirmeyen sorularda devreye girer
    (bkz. main.py 2.6 blogu). Meclis (council) aciksa hic calismaz.
    """
    n = int(_stats.get("moa_runs") or 0)
    if n:
        note = (f"{n} MoA turu · {_stats.get('proposals_generated')} oneri "
                f"· {_stats.get('synthesized_answers')} sentez "
                f"· ortalama {_stats.get('avg_elapsed_s')}s.")
    else:
        note = ("Henuz calismadi. Multi modunda ve arac gerektirmeyen sorularda "
                "devreye girer; her cagri 4-5 model isteğidir.")
    return {"available": True, "note": note}

