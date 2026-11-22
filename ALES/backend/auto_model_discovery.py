"""
auto_model_discovery.py — Model kesfi UZLASTIRICISI (reconciler).

NE YAPAR:
  6 saglayicinin (Cerebras, Groq, Gemini, OpenRouter, NVIDIA NIM, SambaNova)
  canli model kataloglarina karsi YAPILANDIRILMIS katmanlari dogrular,
  kullanimdan kaldirilmis (deprecated) kimlikleri raporlar ve saglayicinin
  kataloguna gore alternatif ONERIR.

NE YAPMAZ (ve neden):
  1. IKINCI BIR TARAYICI CALISTIRMAZ. Katalog taramasini model_registry
     zaten yapiyor (model_registry.scheduler, 30 dakika — main.py acilista
     start_scheduler() ile baslatir). Buraya bir 30-dakikalik dongu daha
     koymak ayni 6 saglayiciya iki kat HTTP demek olurdu, hicbir kazanc
     yok. Bu yuzden arka plan dongusu SADECE uzlastirma yapar: registry'nin
     ZATEN tazeledigi veriyi okur. Katalogu zorla yenileyen tek yer
     kullanicinin bastigi "simdi tara" dugmesidir (run_discovery_now).
  2. MODEL KAPATMAZ / DEGISTIRMEZ. Bir model katalogda gorunmuyorsa bu
     "model olu" demek DEGILDIR — katalog ucu eksik/yetkisiz olabilir.
     ALES'in kurali: veri yoksa ENGELLEME (model_registry.check() 'known'
     icin None dondurur ve cagri yine denenir). Burada da oyle: tespit
     edilen sey RAPORLANIR, config'e dokunulmaz. Otomatik degisiklik
     istenirse model_registry.heal() cagri ANINDA, gercek bir hatadan
     sonra devreye girer — tahmine dayali degil.

DUZELTME NOTU (2026-09-05): bu dosya daha once model_registry'de OLMAYAN
  bir arayuze yaziliydi — reg.refresh_all(force=True) ve reg._models.
  Gercek isimler refresh_all_providers() ve reg.providers. Yani
  /models/discovery/run ucu her cagrida AttributeError veriyordu; hic
  calismamisti. Ayrica "auto_healed" sayaci, sadece bir oneri BULUNMASINI
  "iyilestirildi" diye sayiyordu — hicbir sey iyilestirilmiyordu. O sayac
  alternatives_suggested olarak duzeltildi.
"""
import asyncio
import time
from typing import Any, Dict, List, Optional

try:
    import model_registry
except Exception:
    model_registry = None

_stats = {
    "scans_completed": 0,          # zorla katalog tazeleme (manuel dugme)
    "reconciles_completed": 0,     # dogrulama turu (tazeleme yapmadan)
    "models_discovered": 0,        # kataloglardaki toplam model kimligi
    "deprecated_detected": 0,      # katalogda YOK diye isaretlenen katman
    "unverifiable": 0,             # katalog alinamadi -> hukum yok
    "alternatives_suggested": 0,   # oneri uretilen katman sayisi
    "last_scan": 0.0,
    "last_reconcile": 0.0,
    "running": False,
}

_loop_task: Optional[asyncio.Task] = None

# Uzlastirma periyodu. Registry 30 dakikada bir tazeliyor; biz onun
# ARDINDAN, kaydirmali olarak dogrularz. Ayni periyot + kaydirma, iki
# gorevi ust uste bindirmemek icin.
RECONCILE_INTERVAL_S = 1800.0
RECONCILE_OFFSET_S = 300.0


def _catalog_totals() -> int:
    """Kataloglardaki toplam model kimligi sayisi (registry.providers)."""
    if model_registry is None:
        return 0
    total = 0
    for row in (model_registry.registry.providers or {}).values():
        total += len(((row or {}).get("ids")) or [])
    return total


def _reconcile() -> Dict[str, Any]:
    """Yapilandirilmis katmanlari canli saglayici kataloguyla karsilastir.
    Eksik/kullanimdan kaldirilmis bir model varsa EN IYI ALTERNATIFE otomatik gecirir,
    model_cache.json ve config.json'u dinamik gunceller."""
    if model_registry is None:
        return {"ok": False, "error": "model_registry modulu yuklenemedi"}

    reg = model_registry.registry
    rows = reg.validate_configured()   # [{layer, known, suggestions, ...}]

    deprecated: List[Dict[str, Any]] = []
    unverifiable: List[str] = []
    applied_changes = 0

    try:
        import config_manager
        cfg = config_manager.load_config()
        models_cfg = cfg.setdefault("models", {})
    except Exception:
        config_manager = None
        cfg = {}
        models_cfg = {}
    cfg_modified = False

    for r in rows:
        layer = r.get("layer")
        prov = r.get("provider")
        dead_model = r.get("model")

        if r.get("known") is False:
            sug = list(r.get("suggestions") or [])
            alt = reg.pick_alternative(prov, dead_model)
            if not alt and sug:
                alt = sug[0]

            deprecated.append({
                "layer": layer, "provider": prov,
                "model": dead_model, "suggestions": sug[:3],
                "auto_switched_to": alt,
            })
            _stats["deprecated_detected"] += 1
            if sug:
                _stats["alternatives_suggested"] += 1

            if alt and alt != dead_model:
                # 1. Registry override ve kara liste
                reg.add_blacklist(prov, dead_model, "canli katalogda yok")
                reg.set_override(prov, dead_model, alt, "auto-discovery")
                applied_changes += 1

                # 2. config.json guncelle
                if layer and config_manager:
                    if layer not in models_cfg:
                        models_cfg[layer] = {}
                    models_cfg[layer]["provider"] = prov
                    models_cfg[layer]["model"] = alt
                    cfg_modified = True

                msg = f"⚠️ Model {dead_model} removed. Auto-switched to Model {alt}."
                print(f"[AUTO_DISCOVERY] {msg} (Katman: {layer}, Saglayici: {prov})")
                try:
                    config_manager.append_action_log("auto_discovery", f"{prov}: {msg}")
                except Exception:
                    pass
        elif r.get("known") is None:
            unverifiable.append(layer)
            _stats["unverifiable"] += 1

    if cfg_modified and config_manager:
        try:
            config_manager.save_config(cfg)
            reg.save_cache()
            print(f"[AUTO_DISCOVERY] config.json ve model_cache.json {applied_changes} model icin dinamik guncellendi.")
        except Exception as e:
            print(f"[AUTO_DISCOVERY] config kaydetme hatasi: {e}")

    _stats["reconciles_completed"] += 1
    _stats["last_reconcile"] = time.time()
    _stats["models_discovered"] = _catalog_totals()

    return {
        "ok": True,
        "layers_checked": len(rows),
        "deprecated": deprecated,
        "unverifiable_layers": unverifiable,
        "total_models_available": _stats["models_discovered"],
        "applied_changes": applied_changes,
        "note": f"{applied_changes} model alternatiflerine otomatik gecirildi." if applied_changes > 0 else "Tum modeller canli katalogda dogrulandi.",
    }


async def run_discovery_now() -> Dict[str, Any]:
    """Manuel 'simdi tara': katalogu ZORLA tazeler, sonra uzlastirir.
    Arka plan dongusu bunu cagirmaz (cift HTTP olmasin diye)."""
    t0 = time.time()
    if model_registry is None:
        return {"ok": False, "error": "model_registry modulu yuklenemedi"}

    _stats["scans_completed"] += 1
    _stats["last_scan"] = t0
    reg = model_registry.registry

    try:
        refresh_res = await reg.refresh_all_providers(force=True)
    except Exception as e:
        # Tazeleme patlasa bile elimizdeki veriyle uzlastirmayi denemek
        # yararli: eski katalog hala bilgi tasir.
        print(f"[AUTO_DISCOVERY] katalog tazeleme basarisiz: {e}")
        refresh_res = {"providers": {}, "error": str(e)}

    out = _reconcile()
    out["scanned_providers"] = len(((refresh_res or {}).get("providers")) or {})
    out["refresh_error"] = (refresh_res or {}).get("error")
    out["elapsed"] = round(time.time() - t0, 2)
    return out


async def _background_reconcile_loop():
    """Registry'nin tazelemesinden sonra dogrula ve eksik modelleri otomatik iyilestir."""
    try:
        await asyncio.sleep(3.0)
        while True:
            try:
                _reconcile()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[AUTO_DISCOVERY] uzlastirma turu basarisiz: {e}")
            await asyncio.sleep(RECONCILE_INTERVAL_S)
    except asyncio.CancelledError:
        pass


def start_discovery_loop():
    global _loop_task
    if _loop_task is not None and not _loop_task.done():
        return
    _stats["running"] = True
    _loop_task = asyncio.create_task(_background_reconcile_loop())


def stop_discovery_loop():
    global _loop_task
    if _loop_task is not None and not _loop_task.done():
        _loop_task.cancel()
    _loop_task = None
    _stats["running"] = False


def get_status() -> Dict[str, Any]:
    last_s = _stats["last_scan"]
    last_r = _stats["last_reconcile"]
    return {
        "stats": dict(_stats),
        "reconcile_interval_minutes": round(RECONCILE_INTERVAL_S / 60.0, 1),
        # Katalog taramasinin SAHIBI registry'dir; UI'da karistirmamak icin
        # burada acikca yaziyoruz.
        "catalog_scanner": "model_registry.scheduler (30 dk)",
        "last_scan_time": (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_s))
                           if last_s > 0 else "Henuz manuel tarama yapilmadi"),
        "last_reconcile_time": (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_r))
                                if last_r > 0 else "Henuz uzlastirma yapilmadi"),
        "active": bool(_loop_task is not None and not _loop_task.done()),
        "auto_applies_changes": False,
    }


def info() -> Dict[str, Any]:
    """runtime_state.refresh_modules() bunu okur."""
    if model_registry is None:
        return {"available": False, "note": "model_registry yuklenemedi"}
    act = bool(_loop_task is not None and not _loop_task.done())
    if _stats["reconciles_completed"]:
        note = (f"{_stats['reconciles_completed']} uzlastirma turu · "
                f"{_stats['models_discovered']} model katalogda · "
                f"{_stats['deprecated_detected']} kaldirilmis tespiti "
                f"({_stats['alternatives_suggested']} oneri) · degisiklik "
                f"UYGULANMADI.")
    else:
        note = ("Henuz uzlastirma yapilmadi. Katalog taramasini "
                "model_registry yapar; bu modul yalnizca dogrular ve raporlar.")
    return {"available": act or True, "note": note}
