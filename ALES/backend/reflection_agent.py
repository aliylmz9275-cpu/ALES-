"""
reflection_agent.py — Reflexion, RetroAct ve SAGE Öz-Yansıma ve Denetim Ajanı.

Referanslar:
  - Reflexion (NeurIPS 2023 / 2025 SOTA uzantıları)
  - RetroAct (NAACL 2025): Çift optimizasyon (adım düzeltme + uzun vadeli plan evrimi)
  - SAGE (2025): Üçlü İşbirlikçi Ajan Modeli (User, Assistant, Checker)

Bileşenler:
  1. Reflexion: Hata gerçekleştiğinde "Neden başarısız oldu? Kök neden nedir?
     Nasıl düzeltilir?" sorularını yanıtlar ve yeni plan üretir.
  2. RetroAct:
     - Hızlı döngü (Fast loop): Adım düzeyinde anında parametre düzeltmesi.
     - Yavaş döngü (Slow loop): Görev planlama politikasını kalıcı olarak iyileştirme.
  3. SAGE Üçlü İşbirliği:
     - User Temsilcisi: Kullanıcı niyetini ve kısıtlarını netleştirir.
     - Assistant Temsilcisi: Eylemleri ve araç çağrılarını üretir.
     - Checker (Denetçi) Temsilcisi: Sonuçları doğrular, eksiklikleri tespit eder.
"""
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

_stats = {
    "reflections_triggered": 0,
    "corrections_successful": 0,
    "sage_triads_run": 0,
    "checker_catches": 0,
}

async def reflect_on_failure(task: str, action: str, error: str, ask_llm: Optional[Callable] = None) -> Dict[str, Any]:
    """
    Bir araç veya adım başarısız olduğunda Reflexion/RetroAct analizi üretir.
    """
    _stats["reflections_triggered"] += 1
    t0 = time.time()

    prompt = (
        f"GÖREV: {task}\n"
        f"DENENEN EYLEM: {action}\n"
        f"ALINAN HATA: {error}\n\n"
        "Lütfen RetroAct formatında şu üç noktayı net ve kısa olarak açıkla:\n"
        "1. KÖK NEDEN (Root Cause): Neden başarısız oldu?\n"
        "2. ANINDA DÜZELTME (Fast-loop fix): Bu adım nasıl değiştirilip tekrar denenmeli?\n"
        "3. STRATEJİK DERS (Slow-loop lesson): Gelecekte benzer hataları önlemek için hangi ilke izlenmeli?"
    )

    reflection_text = ""
    if ask_llm:
        try:
            res = await ask_llm([
                {"role": "system", "content": "Sen kıdemli bir hata denetim ve öz-yansıma (reflection) uzmanısın."},
                {"role": "user", "content": prompt}
            ])
            reflection_text = str(res) if isinstance(res, str) else str(res.get("content", ""))
        except Exception as e:
            reflection_text = f"LLM yansıma hatası: {e}"

    if not reflection_text:
        # Heuristik kural tabanlı yansıma
        reflection_text = (
            f"Kök neden: '{action}' eylemi '{error}' ile sonuçlandı.\n"
            "Anında düzeltme: Parametreleri sadeleştir ve alternatif araçla tekrar dene.\n"
            "Stratejik ders: İşlem öncesinde hedef kaynağın erişilebilirliğini doğrula."
        )

    return {
        "ok": True,
        "reflection": reflection_text,
        "elapsed": round(time.time() - t0, 3),
    }

async def run_sage_pipeline(task: str, ask_llm: Callable, execute_tool: Optional[Callable] = None) -> Dict[str, Any]:
    """
    SAGE Üçlü İşbirlikçi Döngüsü:
    1. User Agent görevi ayrıştırır.
    2. Assistant Agent çözüm/kod üretir.
    3. Checker Agent çözümü titizlikle denetler.
    """
    _stats["sage_triads_run"] += 1
    t0 = time.time()

    # 1. User Agent (Hedef Netleştirme)
    user_prompt = f"Kullanıcı görevi: '{task}'. Bu görevin net başarı kriterlerini ve kısıtlarını 2-3 maddede özetle."
    user_analysis = await ask_llm([{"role": "user", "content": user_prompt}])
    user_specs = str(user_analysis.get("content", user_analysis))

    # 2. Assistant Agent (Eylem Üretimi)
    asst_prompt = (
        f"GÖREV: {task}\n"
        f"KRİTERLER: {user_specs}\n"
        "Bu görevi tamamlayacak en uygun adımları veya yanıtı üret."
    )
    asst_reply = await ask_llm([{"role": "user", "content": asst_prompt}])
    asst_text = str(asst_reply.get("content", asst_reply))

    # 3. Checker Agent (Eleştirel Doğrulama)
    checker_prompt = (
        f"GÖREV: {task}\n"
        f"BAŞARI KRİTERLERİ: {user_specs}\n"
        f"ÜRETİLEN ÇÖZÜM: {asst_text}\n\n"
        "GÖREV: Yukarıdaki çözümü kriterlere göre denetle. Hata, eksiklik veya güvenlik riski var mı? "
        "Eğer çözüm kusursuzsa 'ONAYLANDI' de. Değilse eksikleri belirt."
    )
    check_reply = await ask_llm([{"role": "user", "content": checker_prompt}])
    check_text = str(check_reply.get("content", check_reply))

    approved = "onaylandı" in check_text.lower() or "approved" in check_text.lower()
    if not approved:
        _stats["checker_catches"] += 1
        # Bir kez düzeltme turu yap
        refine_prompt = (
            f"Ürettiğin çözüm denetçi (Checker) tarafından incelendi ve şu eleştiriler yapıldı:\n{check_text}\n\n"
            "Lütfen eleştirileri dikkate alarak nihai düzeltilmiş çözümü üret."
        )
        asst_reply2 = await ask_llm([{"role": "user", "content": refine_prompt}])
        asst_text = str(asst_reply2.get("content", asst_reply2))
        _stats["corrections_successful"] += 1

    return {
        "ok": True,
        "final_output": asst_text,
        "user_specs": user_specs,
        "checker_critique": check_text,
        "checker_approved_first_try": approved,
        "elapsed": round(time.time() - t0, 3),
    }

def stats() -> Dict[str, Any]:
    return dict(_stats)


def info() -> Dict[str, Any]:
    """runtime_state.refresh_modules() bunu okur.

    available: True — ama bu modul LLM cagrisi yapar (ask_llm), yani
    "acik" olmasi bedava DEGILDIR: her tur hatasinda arka planda bir
    model cagrisi daha olur. Bu yuzden runtime_state'te heavy_local=True
    isaretlendi; Performance modunda / kaynak baskisinda ilk kesilenler
    arasindadir.

    Uretilen dersin SADECE "stratejik ders" bolumu MUSE'e yazilir
    (main.py:_extract_strategic_lesson); bolum yoksa hicbir kural
    eklenmez — kasitli, cop kural biriktirmemek icin.
    """
    n = int(_stats.get("reflections_triggered") or 0)
    if n:
        note = (f"{n} hata analiz edildi · {_stats.get('sage_triads_run')} SAGE ucluso "
                f"· {_stats.get('checker_catches')} denetci yakalamasi.")
    else:
        note = ("Henuz yansima yapilmadi (yalnizca arac hatasi olan turlarda "
                "tetiklenir, arka planda ve fazladan bir LLM cagrisiyla).")
    return {"available": True, "note": note}
