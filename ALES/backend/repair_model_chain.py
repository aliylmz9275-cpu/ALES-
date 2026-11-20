"""
repair_model_chain.py — sohbeti olduren OTOMATIK YEDEKLERI gercek cagriyla
bulur, geri alir ve yerine CALISAN bir model koyar.

NEDEN VAR — olculmus ariza (backend-dist/ALES_log.txt, 2026-09-05 10:47):
    [AGENT] mod zinciri tamamen basarisiz oldu:
      cerebras/gemma-4-31b: Error code: 402 - payment_required
      groq/allam-2-7b: Error code: 400 - `tool calling` is not supported
Bu iki model kullanicinin SECIMI DEGILDI. ALES kendi koymustu: 2026-08-26'da
cerebras/llama-3.3-70b ve groq/llama-3.3-70b-versatile 404 verdi,
model_registry.heal() ikisine birer yedek atadi ve %APPDATA%\\ALES\\
model_cache.json icine YAZDI. Yedekler ise yaramaz cikti; ama set_override
bir kez yazildiktan sonra hicbir kod yolunda gozden gecirilmiyordu.
performance modunun zinciri de yalnizca ["fast","fallback"] oldugu icin iki
katmanin IKISI de olu yedege bagliydi: sohbet KALICI olarak calismiyordu.

BU BETIK NE YAPAR:
  1. Her katmanin GERCEKTE cagrilan modelini (override uygulanmis hali)
     ARAC LISTESIYLE gercek bir istekle dener.
  2. Ise yaramaz bir YEDEK bulursa, YENI YEDEK ARAMADAN ONCE kullanicinin
     KENDI modelini bir daha dener. Sebep: bu makinede iki katmanin da
     configured modeli 2026-08-26'da 404 aldigi icin kara listede, ama o
     404 O GUNE ait bir olcum. Katalog degisir. pick_alternative o adi
     asla geri veremez (suggest kara listeyi suzer), yani sormazsak Ali'nin
     secimi kalici kaybedilir. Calisiyorsa: yedek geri alinir, kara liste
     kaydi silinir, katman Ali'nin sectigi modele DONER.
  3. Kendi modeli de calismiyorsa yedegi geri alir, kara listeye atar ve
     taze listeden yenisini secer (model_registry.heal_substitute).
  4. Olu bir model ADI bulursa dogru adi arar (model_registry.heal).
  5. Kara listedeki bir model GERCEKTEN cevap veriyorsa kara listeden
     cikarir — basarili bir cagri, o kaydin yanlis oldugunun KANITIDIR.
  6. Sonunda katman katman dogru/yanlis tablosu basar.

NE YAPMAZ: kullanicinin config.json'a KENDI yazdigi modeli kara listeye
almaz ve silmez. Bu betigin geri aldigi sey yalnizca ALES'in kendi koydugu
yedeklerdir. 402 bir faturalandirma tercihi olabilir; kullanicinin modelini
bizim kaldirmamiz onu habersiz baska bir modele tasimak olurdu.

KULLANIM:
    cd ...\\ALES\\backend
    python repair_model_chain.py            # onar + rapor
    python repair_model_chain.py --dry-run   # sadece rapor, DEGISIKLIK YOK

Cikis kodu: 0 = birincil zincir (fast/fallback) calisiyor. 1 = calismiyor
(sohbet hala olu; tablodaki hata metni sebebi soyler).
"""
import asyncio
import sys

import config_manager
import model_registry
import model_router

DRY = "--dry-run" in sys.argv[1:]

# ARAC LISTESIYLE deniyoruz. NEDEN onemli: allam-2-7b duz sohbette
# CALISIYOR, yalnizca arac cagirirken 400 donuyor. Aracsiz bir ping onu
# "saglam" gosterirdi ve sohbetin neden olu oldugunu bulamazdik. ALES'in
# butun akisi arac cagirdigi icin dogru test BUDUR.
_PROBE_TOOL = [{
    "type": "function",
    "function": {
        "name": "ales_baglanti_testi",
        "description": "Baglanti dogrulamasi icin bos arac.",
        "parameters": {"type": "object",
                       "properties": {"x": {"type": "string"}},
                       "required": []},
    },
}]
_PROBE_MSGS = [{"role": "user", "content": "ping"}]

MAX_SWAPS = 3          # katman basina en fazla ucuncu yedek denenir


async def probe(provider: str, model: str, timeout: float = 25.0) -> tuple:
    """Gercek, arac listeli, kucuk bir istek. Doner: (durum, hata_metni).

    durum: "OK" | "FAIL" | "NOKEY"
    """
    client = model_router.get_client(provider)
    if client is None:
        return "NOKEY", "anahtar yok"

    async def _attempt(extra: dict):
        return await asyncio.wait_for(
            client.chat.completions.create(
                model=model, messages=_PROBE_MSGS, tools=_PROBE_TOOL,
                tool_choice="auto", **extra),
            timeout=timeout)

    try:
        await _attempt({"max_tokens": 16})
        return "OK", ""
    except asyncio.TimeoutError:
        # Zaman asimi model hakkinda KESIN bir sey soylemez: ne kara listeye
        # alinir ne yedek geri alinir. Sadece bildirilir.
        return "FAIL", f"timeout ({timeout:.0f}s)"
    except Exception as e:
        first = f"{type(e).__name__}: {e}"
        # max_tokens'i reddeden modeller var (akil yurutme modelleri
        # max_completion_tokens istiyor). Bunu "model bozuk" saymak YANLIS
        # NEGATIF olurdu ve calisan bir katmani olu gosterirdi — dahasi,
        # yedegi bu yuzden geri alsaydik saglam bir modeli kaybederdik.
        if "max_tokens" in first.lower() or "max_completion_tokens" in first.lower():
            try:
                await _attempt({})
                return "OK", ""
            except asyncio.TimeoutError:
                return "FAIL", f"timeout ({timeout:.0f}s)"
            except Exception as e2:
                first = f"{type(e2).__name__}: {e2}"
        return "FAIL", first


async def fix_layer(lname: str, provider: str, configured: str) -> dict:
    """Tek katmani onar. Doner: rapor sozlugu."""
    reg = model_registry.registry
    eff = reg.effective_model(provider, configured)
    trail = []                        # denenen model adlari, sirayla
    # Kullanicinin KENDI modelini bir daha denedik mi? Override yoksa
    # zaten onu deniyoruz demektir.
    tried_configured = (eff == configured)
    for _ in range(MAX_SWAPS):
        trail.append(eff)
        status, err = await probe(provider, eff)

        if status == "OK":
            # KANIT: cagri gecti. Kara listede duruyorsa kayit YANLISTI.
            if reg.is_blacklisted(provider, eff):
                if DRY:
                    trail.append("(kara listeden cikarilacak)")
                else:
                    reg.clear_blacklist(provider, eff)
                    trail.append("(kara listeden CIKARILDI - cagri gecti)")
            return {"layer": lname, "provider": provider,
                    "configured": configured, "effective": eff,
                    "status": "OK", "error": "", "trail": trail}

        if status == "NOKEY":
            return {"layer": lname, "provider": provider,
                    "configured": configured, "effective": eff,
                    "status": "NOKEY", "error": err, "trail": trail}

        # ── basarisiz: ne tur bir basarisizlik? ──────────────────────
        is_substitute = (eff != configured)
        if is_substitute and model_registry.substitute_unusable(err):
            if DRY:
                return {"layer": lname, "provider": provider,
                        "configured": configured, "effective": eff,
                        "status": "OLU YEDEK", "error": err, "trail": trail}

            # ONCE KULLANICININ KENDI MODELINI BIR DAHA DENE.
            # Neden: bu makinede iki katmanin configured modeli de
            # 2026-08-26'da 404 aldigi icin kara listede. O 404 O GUNE ait
            # bir olcum; saglayici katalogu degisir, model geri gelebilir
            # ya da o gunku hata gecici olabilir. pick_alternative bu adi
            # ASLA geri veremez (suggest kara listeyi suzuyor), yani biz
            # sormazsak Ali'nin secimi kalici olarak kaybedilir ve yerine
            # habersiz baska bir model konur. Bir cagri bu sorunun kesin
            # cevabini veriyor — soralim.
            if not tried_configured:
                tried_configured = True
                st2, err2 = await probe(provider, configured)
                trail.append(f"{configured}(kendi modeli: {st2}"
                             + (f" - {err2[:70]}" if st2 != "OK" else "") + ")")
                if st2 == "OK":
                    retired = reg.retire_override(provider, configured, err)
                    reg.clear_blacklist(provider, configured)
                    return {"layer": lname, "provider": provider,
                            "configured": configured, "effective": configured,
                            "status": "OK",
                            "error": "", "trail": trail + [
                                f"(yedek {retired} geri alindi; {configured} "
                                f"kara listeden cikti - CAGRI GECTI)"]}

            alt = await reg.heal_substitute(provider, configured, err)
            if alt and alt != eff:
                eff = alt
                continue                      # yeni yedegi de DENE
            return {"layer": lname, "provider": provider,
                    "configured": configured, "effective": eff,
                    "status": "YEDEK YOK", "error": err, "trail": trail}

        if not is_substitute and model_router._is_dead_model_error(err):
            if DRY:
                return {"layer": lname, "provider": provider,
                        "configured": configured, "effective": eff,
                        "status": "OLU AD", "error": err, "trail": trail}
            alt = await reg.heal(provider, configured, err)
            if alt and alt != eff:
                eff = alt
                continue
            return {"layer": lname, "provider": provider,
                    "configured": configured, "effective": eff,
                    "status": "OLU AD", "error": err, "trail": trail}

        # Kota / yetki / zaman asimi / bilinmeyen: DOKUNMUYORUZ. Bunlar
        # gecici olabilir ve bir modeli bu yuzden kaybettirmek istemiyoruz.
        return {"layer": lname, "provider": provider,
                "configured": configured, "effective": eff,
                "status": "FAIL", "error": err, "trail": trail}

    return {"layer": lname, "provider": provider, "configured": configured,
            "effective": eff, "status": "FAIL",
            "error": f"{MAX_SWAPS} yedek denendi, hicbiri calismadi",
            "trail": trail}


async def main() -> int:
    models = config_manager.get_models()
    reg = model_registry.registry

    print("=" * 72)
    print("ALES MODEL ZINCIRI ONARIMI" + ("  [DRY-RUN: hicbir sey yazilmaz]"
                                          if DRY else ""))
    print("=" * 72)

    ov = {p: dict(m) for p, m in (reg.overrides or {}).items() if m}
    if ov:
        print("\nMEVCUT OTOMATIK YEDEKLER (ALES'in koydugu, kullanicinin degil):")
        for p, m in ov.items():
            for dead, live in m.items():
                print(f"  {p}: {dead}  ->  {live}")
    else:
        print("\nOtomatik yedek yok — butun katmanlar config.json'daki adi kullaniyor.")

    print("\nHer katman ARAC LISTESIYLE gercekten cagriliyor...\n")
    rows = []
    for lname, spec in models.items():
        provider = (spec or {}).get("provider") or ""
        configured = (spec or {}).get("model") or ""
        if not provider or not configured:
            continue
        r = await fix_layer(lname, provider, configured)
        rows.append(r)
        mark = {"OK": "[OK]  ", "NOKEY": "[KEY] "}.get(r["status"], "[FAIL]")
        print(f"  {mark} {lname:<13} {provider}/{r['effective']}")
        if r["status"] != "OK":
            print(f"         durum: {r['status']} · {r['error'][:150]}")
        if len(r["trail"]) > 1:
            print(f"         denenen: {' -> '.join(r['trail'])}")

    # ── ozet ────────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    okl = [r["layer"] for r in rows if r["status"] == "OK"]
    print(f"CALISAN KATMANLAR : {', '.join(okl) if okl else 'YOK'}")
    bad = [r for r in rows if r["status"] not in ("OK",)]
    if bad:
        print("CALISMAYANLAR     : " + ", ".join(
            f"{r['layer']}({r['status']})" for r in bad))

    # Sohbetin canli olmasi icin performance zincirinin (fast, fallback)
    # EN AZ BIR katmani calismali. Baska katmanlarin durumu sohbeti
    # oldurmez, o yuzden cikis kodunu onlar belirlemez.
    primary = [r for r in rows if r["layer"] in ("fast", "fallback")]
    live = [r for r in primary if r["status"] == "OK"]
    print("-" * 72)
    if live:
        print(f"SOHBET: CALISIR — birincil zincirde {len(live)}/"
              f"{len(primary)} katman canli ({', '.join(r['layer'] for r in live)})")
        rc = 0
    else:
        print("SOHBET: OLU — birincil zincirde (fast/fallback) calisan katman "
              "YOK.\n"
              "        Yukaridaki hata metni sebebi soyler. Kota/odeme "
              "hatasiysa\n"
              "        saglayici hesabi, 'anahtar yok' ise config.json "
              "gerekiyor.")
        rc = 1
    if not DRY:
        reg.save_cache()
        print("model_cache.json guncellendi.")
    print("=" * 72)
    return rc


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
