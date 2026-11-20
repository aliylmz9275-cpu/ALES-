"""
ALES — model zinciri teshis araci (diag_chain.py)

TEK CALISTIRMADA su sorulari canli olarak yanitlar:
  1. Hangi saglayicinin anahtari var, hangisi YANLIS TURDE
  2. Her saglayici GERCEKTEN ulasilabilir mi (liste + kucuk bir cagri)
  3. Gercek istem KAC TOKEN (saglayicinin usage.prompt_tokens'i ile — tahmin degil)
  4. Zincir (aktif mod) gercek arac semalariyla acilabiliyor mu, hangi katman
  5. Model ARAC CAGIRIYOR mu (google_search gerektiren bir soru ile)

Kullanim:
    python diag_chain.py

GUVENLIK: anahtar DEGERLERI hicbir zaman yazdirilmaz. Sadece "var/yok",
uzunluk ve tur tespiti gosterilir.

NOT: main.py IMPORT EDILMEZ (import etmek tum uygulamayi ayaga kaldirirdi).
TOOLS listesi ast.literal_eval ile main.py'den YAN ETKISIZ okunur.
"""
import ast
import asyncio
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import config_manager as cm
import model_router as mr

LINE = "─" * 68


def hdr(t):
    print(f"\n{LINE}\n  {t}\n{LINE}")


# ─── 1. ANAHTARLAR ───────────────────────────────────────────────
def check_keys():
    hdr("1. ANAHTARLAR (degerler ASLA yazdirilmaz)")
    raw = cm.load_config()
    for prov, field in mr.PROVIDER_KEY.items():
        in_cfg = (raw.get(field) or "").strip()
        usable = cm.get_key(field)
        if not in_cfg and not usable:
            state = "YOK (ne config.json ne .env)"
        elif in_cfg and not usable:
            state = f"VAR ama REDDEDILDI (yanlis tur, {len(in_cfg)} karakter)"
        elif not in_cfg and usable:
            state = f"VAR (.env'den, {len(usable)} karakter)"
        else:
            state = f"VAR (config.json, {len(usable)} karakter)"
        print(f"  {prov:<11} {field:<17} {state}")
    probs = cm.credential_problems()
    if probs:
        print("\n  YANLIS TURDE KIMLIK BILGISI:")
        for p in probs:
            print(f"    - {p['field']}: {p['problem']}")
    else:
        print("\n  Yanlis turde kimlik bilgisi yok.")


# ─── 2. AKTIF YAPILANDIRMA ───────────────────────────────────────
def check_config():
    hdr("2. AKTIF YAPILANDIRMA")
    mc = cm.get_mode_config()
    print(f"  Mod            : {mc['mode']} ({mc['label']})")
    print(f"  Zincir         : " + " -> ".join(
        f"{l['layer']}={l['provider']}/{l['model']}" for l in mc["chain"]))
    print(f"  Zaman asimlari : {mc['timeouts']}")
    print(f"  Cikti tavanlari: {mc.get('max_out')}")
    if mc.get("dropped_layers"):
        print(f"  Zincirden dusen: {mc['dropped_layers']}")
    return mc


# ─── 3. GERCEK ARAC SEMALARI (main.py'den yan etkisiz) ───────────
def load_tools():
    """main.py'yi CALISTIRMADAN TOOLS listesini oku."""
    src = (HERE / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "TOOLS":
                    return ast.literal_eval(node.value)
    return []


def build_payload():
    """select_relevant_tools'un basit bir soru icin DONDURDUGU gercek set."""
    import tool_router
    tools = load_tools()
    q = "bugun hava nasil, internetten arastir"
    active = tool_router.select_relevant_tools(q, tools)
    return q, tools, active


# ─── 4. SAGLAYICI YOKLAMASI ──────────────────────────────────────
async def probe(provider, model, timeout=30.0):
    """Kucuk bir gercek cagri: ulasilabilirlik + usage.prompt_tokens."""
    client = mr.get_client(provider)
    if client is None:
        return {"ok": False, "err": "key yok/reddedildi"}
    t0 = time.time()
    try:
        r = await asyncio.wait_for(client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": "ping"}],
            max_tokens=8, temperature=0), timeout=timeout)
        return {"ok": True, "s": round(time.time() - t0, 2),
                "txt": (r.choices[0].message.content or "")[:40]}
    except Exception as e:
        return {"ok": False, "s": round(time.time() - t0, 2),
                "err": f"{type(e).__name__}: {str(e)[:300]}"}


async def probe_all_layers():
    hdr("4. SAGLAYICI YOKLAMASI (her katman icin kucuk gercek cagri)")
    models = cm.get_models()
    res = {}
    for lname, spec in models.items():
        p, m = spec["provider"], spec["model"]
        r = await probe(p, m)
        res[lname] = r
        if r["ok"]:
            print(f"  OK    {lname:<13} {p}/{m}  ({r['s']}s)")
        else:
            print(f"  HATA  {lname:<13} {p}/{m}\n        -> {r['err']}")
    return res


# ─── 5. GERCEK ISTEM BOYUTU ──────────────────────────────────────
async def measure_prompt(mc, system, active):
    """Saglayicinin KENDI sayacindan istem token sayisi. Tahmin degil."""
    hdr("5. GERCEK ISTEM BOYUTU (saglayicinin usage.prompt_tokens'i)")
    sch = json.dumps(active, ensure_ascii=False)
    print(f"  Arac sayisi        : {len(active)}")
    print(f"  Arac semasi (bayt) : {len(sch.encode('utf-8')):,}")
    print(f"  Sistem istemi(bayt): {len(system.encode('utf-8')):,}")
    # Buyuk pencereli bir katman uzerinden say (Groq 128k) — sayim icin
    # basarili olmasi yeterli, uretim onemli degil.
    for lname in ("fallback", "fast"):
        spec = cm.get_models().get(lname)
        if not spec:
            continue
        client = mr.get_client(spec["provider"])
        if client is None:
            continue
        try:
            r = await asyncio.wait_for(client.chat.completions.create(
                model=spec["model"],
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": "merhaba"}],
                tools=active, tool_choice="auto",
                max_tokens=16, temperature=0), timeout=60)
            u = r.usage
            print(f"  {spec['provider']} sayimi   : prompt={u.prompt_tokens} "
                  f"token  (bu, max_tokens ile TOPLANIP pencereye sigmali)")
            return u.prompt_tokens
        except Exception as e:
            print(f"  {spec['provider']}: sayilamadi -> {type(e).__name__}: {str(e)[:200]}")
    return None


# ─── 6. ZINCIR + ARAC CAGRISI (uctan uca) ────────────────────────
async def e2e(system, active, question, label):
    print(f"\n  >>> {label}")
    print(f"      Soru: {question}")
    msgs = [{"role": "system", "content": system},
            {"role": "user", "content": question}]
    text, calls, layer, err = [], [], None, None
    t0 = time.time()

    def on_layer(l):
        nonlocal layer
        layer = f"{l.get('layer')}={l.get('provider')}/{l.get('model')}"

    async for ch in mr.stream_chat(msgs, tools=active, on_layer=on_layer):
        if ch["type"] == "token":
            text.append(ch["text"])
        elif ch["type"] == "tool_calls":
            calls = ch["tool_calls"]
        elif ch["type"] == "error":
            err = ch["error"]
        elif ch["type"] == "done":
            pass
    el = round(time.time() - t0, 2)
    if err:
        print(f"      SONUC: BASARISIZ ({el}s)\n      {err[:600]}")
        return False, None
    print(f"      Katman: {layer}   sure: {el}s")
    if calls:
        for c in calls:
            print(f"      ARAC CAGRISI: {c['name']}({c['args'][:120]})")
    body = "".join(text).strip()
    if body:
        print(f"      Metin: {body[:200]}")
    return True, calls


async def main():
    check_keys()
    mc = check_config()
    question, all_tools, active = build_payload()

    # Gercekci bir sistem istemi: ALES'in BASE_SYSTEM'i (varsa) + biraz baglam.
    system = ""
    try:
        src = (HERE / "main.py").read_text(encoding="utf-8")
        m = re.search(r'BASE_SYSTEM\s*=\s*(?:f?""")(.*?)"""', src, re.S)
        if m:
            system = m.group(1)
    except Exception:
        pass
    if not system:
        system = "Sen ALES'sin, Turkce konusan bir masaustu asistani."
    print(f"\n  Tum araclar: {len(all_tools)} · bu soru icin secilen: {len(active)}")

    await probe_all_layers()
    await measure_prompt(mc, system, active)

    hdr("6. UCTAN UCA (zincir -> katman secimi -> arac cagrisi -> yanit)")
    ok1, _ = await e2e(system, active,
                       "Merhaba, kisaca kendini tanit.", "A) Duz sohbet")
    ok2, calls = await e2e(
        system, active,
        "Google'da 'NVIDIA hisse fiyati' diye ara ve bulduklarini soyle.",
        "B) Arac gerektiren soru (google_search beklenir)")

    hdr("SONUC")
    print(f"  Zincir aciliyor          : {'EVET' if ok1 else 'HAYIR'}")
    print(f"  Arac cagrisi geliyor     : {'EVET' if calls else 'HAYIR'}")
    if calls:
        print(f"  Cagrilan arac(lar)       : {[c['name'] for c in calls]}")
    if not ok1:
        print("  -> Zincir hala kapali; yukaridaki HATA satirlari sebebi soyler.")
    return 0 if (ok1 and ok2) else 1


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
