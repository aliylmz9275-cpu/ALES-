"""
darwin_godel.py — Darwin Gödel Machine: Açık Uçlu Öz-Gelişim Ajanı (Open-Ended Evolution).

Referans:
  - "Darwin Gödel Machine: Open-Ended Evolution of Self-Improving Agents" (2025).

Prensip:
  Darwinci evrimsel arama (mutasyon, seçilim) ile Gödel makinesinin kendine-referanslı
  iyileştirme yaklaşımını birleştirir. Ajan iskelelerinin (scaffold) açık uçlu bir
  arşivini tutar; adayları GERÇEK görev sonuçlarıyla sınar ve yalnızca kanıtlanmış
  olanları şampiyon yapar.

──────────────────────────────────────────────────────────────────────────────
2026-09-05 — UYUM (FITNESS) FONKSİYONU GERÇEĞE BAĞLANDI
──────────────────────────────────────────────────────────────────────────────
ÖNCEKİ SÜRÜMDEKİ KUSUR (kasıtlı olarak burada belgeleniyor ki geri gelmesin):

    new_fitness = min(0.99, parent["fitness"] + random.uniform(0.01, 0.04))

Uyum skoru RASTGELE artırılıyordu. Hiçbir kıyaslama koşulmuyordu. Sonuç:
  • "best_fitness" hiçbir kanıt olmadan 0.99'a kadar tırmanıyordu,
  • arşiv, işe yarayıp yaramadığı BİLİNMEYEN mutasyonlarla doluyordu,
  • bu strateji metni sistem promptuna enjekte edilse ALES'e rastgele
    seçilmiş yönergeler yazılırken panelde "gelişiyorum" yazacaktı.
Yani ölçüm, ölçtüğünü iddia ettiği şeyle ilgisizdi — kendini kandıran bir
gösterge. Evrim için gereken tek şey (seçilim baskısı) tam olarak buydu.

ŞİMDİ NASIL ÇALIŞIYOR:
  1. Her turda AKTİF iskelenin kimliği (`get_active_strategy`) prompta gider.
  2. Tur bitince o kimliğe GERÇEK sonuç yazılır (`record_outcome`):
     başarı/başarısızlık, adım sayısı, hata sayısı.
  3. Uyum = Wilson alt sınırı ile hesaplanan MUHAFAZAKAR başarı oranı
     + adım verimliliği + hata cezası. Küçük örneklemde Wilson alt sınırı
     2/2'lik bir adayın 40/45'lik şampiyonu yenmesini ENGELLER.
  4. Bir aday ancak MIN_TRIALS gerçek turdan sonra ve şampiyonu GERÇEKTEN
     geçtiyse şampiyon olur; geçemezse arşivden düşürülür.

SINIR: Bu modül KOD YAZMAZ ve kaynak dosyaya DOKUNMAZ. Evrim yalnızca
strateji METNİ düzeyindedir (ör. "tıklamadan önce pencere odağını doğrula").
Kendi kodunu değiştiren bir ajan, gözetimsiz bir makinede geri alınamaz
hasar demektir; config_manager.py:122'deki kural burada da geçerlidir.
"""
import hashlib
import json
import math
import os
import random
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from config_manager import get_appdata_dir
    _ARCHIVE_FILE = get_appdata_dir() / "darwin_godel_archive.json"
except Exception:
    _ARCHIVE_FILE = Path("darwin_godel_archive.json")

_lock = threading.RLock()
_archive: List[Dict[str, Any]] = []
_generation = 1
_champion_id: Optional[str] = None
_challenger_id: Optional[str] = None

# Bir adayın şampiyonla kıyaslanabilmesi için gereken en az GERÇEK tur sayısı.
# Düşük tutmak "3 turda şanslı çıktı" sapmasına, çok yüksek tutmak evrimin
# hiç ilerlememesine yol açar. 12, tek kullanıcılı bir sistemde birkaç günde
# dolan ama gürültüyü de büyük ölçüde bastıran bir eşik.
MIN_TRIALS = 12
MAX_ARCHIVE = 25
# Deneme penceresinde isteklerin ne kadarı challenger'a gitsin (A/B oranı).
CHALLENGER_SHARE = 0.5

_stats = {
    "generations_evolved": 0,
    "variants_evaluated": 0,
    "mutations_applied": 0,
    "promotions": 0,
    "rejections": 0,
    "outcomes_recorded": 0,
}

# Başlangıç tohum iskele stratejileri. fitness YOK: hepsi kanıtlanmamış
# başlar (trials=0). "0.75 / 0.82 / 0.88" gibi elle yazılmış skorlar da
# uydurmaydı — onlar da kaldırıldı.
DEFAULT_SEEDS = [
    {
        "id": "seed_01",
        "name": "Hızlı Doğrudan İcra",
        "strategy": "Kısa ve öz yanıtlar ver. Gereksiz araç çağırmadan ilk turda çözüme odaklan.",
    },
    {
        "id": "seed_02",
        "name": "Savunmacı Adım Denetimi",
        "strategy": "Her eylemden önce hedef kaynağın varlığını ve pencere odağını kontrol et.",
    },
    {
        "id": "seed_03",
        "name": "Çift Yansımalı Akıl Yürütme",
        "strategy": "Karmaşık adımlarda önce planı zihinsel olarak simüle et, sonra icra et.",
    },
]


def _blank_metrics() -> Dict[str, Any]:
    return {"trials": 0, "successes": 0, "steps_total": 0, "errors_total": 0}


def _new_variant(vid: str, name: str, strategy: str, generation: int = 0,
                 parent_id: Optional[str] = None) -> Dict[str, Any]:
    v = {
        "id": vid,
        "name": name,
        "strategy": strategy,
        "generation": generation,
        "parent_id": parent_id,
        "created": time.time(),
    }
    v.update(_blank_metrics())
    return v


def _load_archive():
    global _archive, _generation, _champion_id
    with _lock:
        if _archive:
            return
        loaded = None
        if _ARCHIVE_FILE.exists():
            try:
                raw = json.loads(_ARCHIVE_FILE.read_text(encoding="utf-8"))
                loaded = raw.get("archive") or None
                _generation = raw.get("generation", 1)
                _champion_id = raw.get("champion_id")
                for k, v in (raw.get("stats") or {}).items():
                    if k in _stats:
                        _stats[k] = v
            except Exception:
                loaded = None
        if loaded:
            # Eski (rastgele fitness'lı) arşivleri göç ettir: uydurma skorları
            # at, ölçüm alanlarını sıfırdan başlat. Kanıt yoksa skor yok.
            _archive = []
            for v in loaded:
                if "trials" not in v:
                    v = dict(v)
                    v.pop("fitness", None)
                    v.pop("tests_passed", None)
                    v.update(_blank_metrics())
                _archive.append(v)
        else:
            _archive = [_new_variant(s["id"], s["name"], s["strategy"])
                        for s in DEFAULT_SEEDS]
        if not _champion_id or not any(v["id"] == _champion_id for v in _archive):
            _champion_id = _archive[0]["id"] if _archive else None


def _save_archive():
    try:
        _ARCHIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _ARCHIVE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "generation": _generation,
            "champion_id": _champion_id,
            "challenger_id": _challenger_id,
            "stats": _stats,
            "archive": _archive,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(_ARCHIVE_FILE))
    except Exception:
        pass


def _find(vid: Optional[str]) -> Optional[Dict[str, Any]]:
    if not vid:
        return None
    return next((v for v in _archive if v.get("id") == vid), None)


# ─── UYUM (FITNESS) ──────────────────────────────────────────────────────
def _wilson_lower_bound(successes: int, trials: int, z: float = 1.96) -> float:
    """Başarı oranının %95 güven aralığının ALT sınırı.

    Neden düz oran (successes/trials) değil: 2 turda 2 başarı düz oranla
    1.00 verir ve 45 turda 40 başarı yapan şampiyonu anında devirir. Wilson
    alt sınırı örneklem küçükken skoru aşağı çeker, yani bir aday ancak
    YETERİNCE denendiyse yüksek skor alabilir. Seçilim baskısının gürültüye
    değil kanıta dayanmasını sağlayan tek satır budur.
    """
    if trials <= 0:
        return 0.0
    p = successes / trials
    denom = 1.0 + (z * z) / trials
    centre = p + (z * z) / (2 * trials)
    margin = z * math.sqrt((p * (1 - p) + (z * z) / (4 * trials)) / trials)
    return max(0.0, (centre - margin) / denom)


def compute_fitness(v: Dict[str, Any]) -> Optional[float]:
    """Ölçülmüş uyum skoru. Hiç denenmemişse None döner (0.0 DEĞİL — "kötü"
    ile "bilinmiyor" farklı şeylerdir ve arayüzde de farklı görünmeleri
    gerekir)."""
    trials = int(v.get("trials", 0) or 0)
    if trials <= 0:
        return None
    succ = int(v.get("successes", 0) or 0)
    base = _wilson_lower_bound(succ, trials)

    # Adım verimliliği: aynı işi daha az adımda bitiren iskele daha iyidir.
    avg_steps = (v.get("steps_total", 0) or 0) / trials
    step_eff = 1.0 / (1.0 + avg_steps / 10.0)

    # Hata cezası: tur başına ortalama araç hatası.
    avg_err = (v.get("errors_total", 0) or 0) / trials
    err_score = 1.0 / (1.0 + avg_err)

    return round(0.75 * base + 0.15 * step_eff + 0.10 * err_score, 4)


def _is_proven(v: Dict[str, Any]) -> bool:
    return int(v.get("trials", 0) or 0) >= MIN_TRIALS


# ─── AKTİF İSKELE SEÇİMİ (A/B) ───────────────────────────────────────────
def get_active_strategy() -> Dict[str, Any]:
    """Bu tur için kullanılacak iskeleyi seçer.

    Deneme (challenger) varsa istekler şampiyon ile challenger arasında
    CHALLENGER_SHARE oranında bölünür — ikisinin de skoru AYNI koşullarda
    birikir, yoksa kıyaslama adil olmaz. Deneme yoksa şampiyon döner.

    Dönüş: {"id", "name", "strategy", "role"} — id'yi caller saklamalı ve
    tur bitince record_outcome'a GERİ VERMELİ, yoksa sonuç yanlış adaya
    yazılır ve tüm ölçüm bozulur.
    """
    _load_archive()
    with _lock:
        champ = _find(_champion_id) or (_archive[0] if _archive else None)
        chal = _find(_challenger_id)
        pick, role = champ, "champion"
        if chal is not None and random.random() < CHALLENGER_SHARE:
            pick, role = chal, "challenger"
        if pick is None:
            return {"id": None, "name": "", "strategy": "", "role": "none"}
        return {"id": pick["id"], "name": pick.get("name", ""),
                "strategy": pick.get("strategy", ""), "role": role}


def record_outcome(success: bool, steps: int = 0, errors: int = 0,
                   scaffold_id: Optional[str] = None) -> Dict[str, Any]:
    """Bir GERÇEK turun sonucunu ilgili iskeleye yazar. Uyum skoru bundan
    türer — başka hiçbir yerden skor üretilmez.

    scaffold_id verilmezse şampiyona yazılır (geriye dönük uyumluluk).
    """
    _load_archive()
    with _lock:
        v = _find(scaffold_id) or _find(_champion_id)
        if v is None:
            return {"ok": False, "error": "arşivde iskele yok"}
        v["trials"] = int(v.get("trials", 0) or 0) + 1
        if success:
            v["successes"] = int(v.get("successes", 0) or 0) + 1
        v["steps_total"] = int(v.get("steps_total", 0) or 0) + max(0, int(steps or 0))
        v["errors_total"] = int(v.get("errors_total", 0) or 0) + max(0, int(errors or 0))
        v["fitness"] = compute_fitness(v)
        _stats["outcomes_recorded"] += 1
        _save_archive()
        out = {"ok": True, "id": v["id"], "trials": v["trials"],
               "fitness": v["fitness"]}
    # Deneme yeterince veri topladıysa hükmü hemen ver.
    if _challenger_id and scaffold_id != "__no_judge__":
        try:
            out["verdict"] = _judge_challenger()
        except Exception:
            pass
    return out


def _judge_challenger() -> Optional[Dict[str, Any]]:
    """Challenger ve şampiyon YETERİNCE denendiyse kararı verir:
    challenger ölçülmüş uyumda şampiyonu geçtiyse terfi, geçemediyse ret."""
    global _champion_id, _challenger_id
    with _lock:
        chal = _find(_challenger_id)
        champ = _find(_champion_id)
        if chal is None or champ is None:
            return None
        if not _is_proven(chal):
            return None
        f_chal = compute_fitness(chal) or 0.0
        f_champ = compute_fitness(champ) or 0.0
        # Şampiyon henüz kanıtlanmadıysa onu da beklet: iki taraf da aynı
        # eşiği geçmeden karşılaştırma anlamsız.
        if not _is_proven(champ):
            return None
        if f_chal > f_champ:
            _champion_id, _challenger_id = chal["id"], None
            _stats["promotions"] += 1
            _save_archive()
            return {"decision": "promoted", "new_champion": chal["id"],
                    "fitness": f_chal, "beat": f_champ}
        _challenger_id = None
        _stats["rejections"] += 1
        # Reddedilen aday arşivde KALIR (ölçümüyle birlikte) — aynı mutasyonun
        # tekrar denenmesini önler ve neyin işe yaramadığı kaydı olur.
        chal["rejected"] = True
        _save_archive()
        return {"decision": "rejected", "id": chal["id"],
                "fitness": f_chal, "champion_fitness": f_champ}


# ─── MUTASYON / EVRİM ────────────────────────────────────────────────────
_FALLBACK_MUTATIONS = [
    "Hata durumunda parametreleri en sade hale getirip alternatif araca yönel.",
    "Kullanıcı onay kapısı gerektiren kritik işlemlerde geri dönüş planı hazırla.",
    "Büyük veri veya dosya taramalarında hafıza tamponunu kontrol et.",
    "Masaüstü otomasyonunda tıklama sonrası ekran tazeleme gecikmesini 0.2 saniye uzat.",
]


def mutate_strategy(strategy: str) -> str:
    """Evrimsel mutasyon operatörü (LLM yoksa kullanılan yedek)."""
    chosen = random.choice(_FALLBACK_MUTATIONS)
    if chosen not in strategy:
        return f"{strategy} [Evrilmiş Kural: {chosen}]"
    return strategy


async def _llm_mutate(parent: Dict[str, Any], ask_llm: Callable) -> str:
    """Mutasyonu modele ürettir. Sabit listeden seçmekten daha anlamlı:
    ebeveynin ÖLÇÜLMÜŞ zayıf noktasını (hata/adım ortalaması) görerek
    hedefli bir kural önerir."""
    trials = int(parent.get("trials", 0) or 0)
    avg_steps = (parent.get("steps_total", 0) or 0) / trials if trials else 0
    avg_err = (parent.get("errors_total", 0) or 0) / trials if trials else 0
    prompt = (
        "Bir bilgisayar-kullanan yapay zeka ajanının davranış stratejisini "
        "iyileştiriyorsun.\n\n"
        f"MEVCUT STRATEJİ: {parent.get('strategy','')}\n"
        f"ÖLÇÜLEN PERFORMANS: {trials} gerçek görev, "
        f"başarı oranı %{round(100*(parent.get('successes',0)/trials)) if trials else '?'}, "
        f"görev başına ortalama {avg_steps:.1f} adım, {avg_err:.2f} araç hatası.\n\n"
        "Bu ölçümlere bakarak stratejiye eklenecek TEK bir somut davranış "
        "kuralı yaz. Sadece kuralı yaz (tek cümle, en fazla 25 kelime), "
        "açıklama veya numara ekleme."
    )
    res = await ask_llm([
        {"role": "system", "content": "Kısa ve somut davranış kuralları yazan bir ajan mimarısın."},
        {"role": "user", "content": prompt},
    ])
    rule = (res if isinstance(res, str) else str(res.get("content", ""))).strip()
    rule = rule.strip(" \"'*-–—\n")[:200]
    if not rule or len(rule) < 10:
        return mutate_strategy(parent.get("strategy", ""))
    return f"{parent.get('strategy','')} [Evrilmiş Kural: {rule}]"


async def evolve_generation(ask_llm: Optional[Callable] = None) -> Dict[str, Any]:
    """Bir evrim nesli işletir: en iyi KANITLANMIŞ ebeveynden mutasyonla
    yeni bir challenger üretir ve denemeye sokar.

    ÖNEMLİ: yeni aday uyum skoruyla DOĞMAZ (fitness=None). Skoru ancak
    gerçek turlarda çalışıp record_outcome ile veri biriktirerek kazanır.
    Zaten bir deneme sürüyorsa yeni deneme açılmaz — iki adayı aynı anda
    sınamak ölçümü kirletir.
    """
    _load_archive()
    global _generation, _challenger_id

    with _lock:
        if _challenger_id and _find(_challenger_id) is not None:
            chal = _find(_challenger_id)
            return {"ok": False, "reason": "deneme_suruyor",
                    "challenger": chal["id"],
                    "trials": chal.get("trials", 0),
                    "needed": MIN_TRIALS,
                    "message": (f"'{chal.get('name')}' halen deneniyor "
                                f"({chal.get('trials',0)}/{MIN_TRIALS} tur). "
                                "Hüküm verilmeden yeni nesil açılmaz.")}
        champ = _find(_champion_id) or (_archive[0] if _archive else None)
        if champ is None:
            return {"ok": False, "error": "arşiv boş"}
        parent = champ

    # LLM çağrısı kilit DIŞINDA (ağ beklemesi kilidi tutmasın).
    if ask_llm is not None:
        try:
            new_strategy = await _llm_mutate(parent, ask_llm)
        except Exception:
            new_strategy = mutate_strategy(parent.get("strategy", ""))
    else:
        new_strategy = mutate_strategy(parent.get("strategy", ""))

    with _lock:
        if any(v.get("strategy") == new_strategy for v in _archive):
            return {"ok": False, "reason": "tekrar_mutasyon",
                    "message": "Bu mutasyon zaten arşivde; yeni bir tane denenmeli."}
        _generation += 1
        _stats["generations_evolved"] += 1
        _stats["mutations_applied"] += 1
        _stats["variants_evaluated"] += 1
        new_id = f"gen{_generation}_{hashlib.sha256(new_strategy.encode('utf-8')).hexdigest()[:8]}"
        child = _new_variant(new_id, f"Evrilmiş İskele v{_generation}",
                             new_strategy, generation=_generation,
                             parent_id=parent["id"])
        _archive.append(child)
        _challenger_id = new_id

        # Arşivi sınırla: KANITLANMIŞ olanları ölçülmüş uyuma göre tut,
        # kanıtlanmamışları (şampiyon/challenger hariç) at.
        if len(_archive) > MAX_ARCHIVE:
            keep = {_champion_id, _challenger_id}
            proven = sorted([v for v in _archive if _is_proven(v) and v["id"] not in keep],
                            key=lambda x: compute_fitness(x) or 0.0, reverse=True)
            unproven = [v for v in _archive if not _is_proven(v) and v["id"] not in keep]
            merged = [v for v in _archive if v["id"] in keep] + proven + unproven
            _archive = merged[:MAX_ARCHIVE]
        _save_archive()
        return {"ok": True, "generation": _generation, "new_variant": child,
                "parent": parent["id"], "trials_needed": MIN_TRIALS,
                "message": (f"Yeni aday denemeye alındı. Şampiyon olabilmesi için "
                            f"{MIN_TRIALS} gerçek turda ölçülüp şampiyonu geçmesi gerekiyor.")}


def get_best_scaffold() -> Dict[str, Any]:
    """KANITLANMIŞ en iyi iskele. Kanıtlanmış hiçbir şey yoksa şampiyon
    (varsayılan tohum) döner — uydurma skorlu bir mutasyon ASLA dönmez."""
    _load_archive()
    with _lock:
        proven = [v for v in _archive if _is_proven(v) and not v.get("rejected")]
        if proven:
            return max(proven, key=lambda x: compute_fitness(x) or 0.0)
        return _find(_champion_id) or (_archive[0] if _archive else dict(DEFAULT_SEEDS[0]))


def get_archive() -> List[Dict[str, Any]]:
    _load_archive()
    with _lock:
        out = []
        for v in _archive:
            d = dict(v)
            d["fitness"] = compute_fitness(v)          # None = henüz ölçülmedi
            d["proven"] = _is_proven(v)
            d["success_rate"] = (round(v.get("successes", 0) / v["trials"], 3)
                                 if v.get("trials") else None)
            d["role"] = ("champion" if v["id"] == _champion_id else
                         "challenger" if v["id"] == _challenger_id else "archived")
            out.append(d)
        return out


def stats() -> Dict[str, Any]:
    _load_archive()
    with _lock:
        champ = _find(_champion_id)
        chal = _find(_challenger_id)
        proven = [v for v in _archive if _is_proven(v)]
        return {
            "generation": _generation,
            "generations_evolved": _stats["generations_evolved"],
            "variants_evaluated": _stats["variants_evaluated"],
            "mutations_applied": _stats["mutations_applied"],
            "outcomes_recorded": _stats["outcomes_recorded"],
            "promotions": _stats["promotions"],
            "rejections": _stats["rejections"],
            "archive_count": len(_archive),
            "proven_count": len(proven),
            "min_trials": MIN_TRIALS,
            "champion": ({"id": champ["id"], "name": champ.get("name"),
                          "trials": champ.get("trials", 0),
                          "fitness": compute_fitness(champ),
                          "proven": _is_proven(champ)} if champ else None),
            "challenger": ({"id": chal["id"], "name": chal.get("name"),
                            "trials": chal.get("trials", 0),
                            "needed": MIN_TRIALS,
                            "fitness": compute_fitness(chal)} if chal else None),
            # Ölçülmüş en iyi uyum. Hiç veri yoksa None döner; panelde
            # "henüz ölçülmedi" yazması, uydurma bir 0.99'dan iyidir.
            "best_fitness": max((compute_fitness(v) or 0.0 for v in proven),
                                default=None),
        }


def trial_status() -> Dict[str, Any]:
    """UI için kısa deneme durumu."""
    s = stats()
    return {"champion": s["champion"], "challenger": s["challenger"],
            "min_trials": MIN_TRIALS, "promotions": s["promotions"],
            "rejections": s["rejections"]}


def info() -> Dict[str, Any]:
    """runtime_state.refresh_modules() bunu okur.

    available: yerel JSON arsivi, harici bagimlilik yok.

    NOTTA UYDURMA SAYI YOK: bir aday MIN_TRIALS denemeyi tamamlamadan
    "uyum" (fitness) bildirilmez — olculmemis bir aday KOTU degildir,
    BILINMEYENDIR (compute_fitness None doner). Eski surumde fitness
    rastgele artiyordu ve panel kanit olmadan 0.99 gosteriyordu; o hata
    bir daha girmesin diye durum burada acikca "X/Y deneme" olarak yazilir.
    """
    s = stats()
    champ = s.get("champion") or {}
    chal = s.get("challenger")
    parts = [f"nesil {s.get('generation')}",
             f"{s.get('archive_count')} iskele arsivde"]
    if champ:
        f = champ.get("fitness")
        parts.append(f"sampiyon '{champ.get('name')}' "
                     + (f"uyum={f}" if f is not None else
                        f"{champ.get('trials', 0)}/{s.get('min_trials')} deneme"))
    if chal:
        parts.append(f"aday deneniyor {chal.get('trials', 0)}/{s.get('min_trials')}")
    else:
        parts.append("aday yok")
    parts.append(f"{s.get('promotions')} terfi / {s.get('rejections')} red")
    return {"available": True, "note": " · ".join(parts) + "."}
