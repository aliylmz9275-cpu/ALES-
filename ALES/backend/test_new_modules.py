"""
test_new_modules.py — ALES yeni modul dogrulama betigi.

Bash/otomatik dogrulama kullanilamadigi icin bu betik ELLE calistirilmak
uzere yazildi. Hicbir gercek veriyi bozmaz:
  * long_term_memory  -> GECICI bir .db dosyasi kullanir, sonunda siler
  * browser_profiles  -> "__test_profile" adli profili olusturur ve siler
  * credentials       -> yalnizca "ales_test_secret" adli test sirriyla
                         oynar, sonunda siler. GERCEK key'lere DOKUNMAZ
                         (migrate cagrilmaz).
  * resource_monitor  -> sadece olcum yapar, hicbir sey kapatmaz
  * runtime_state     -> mod degistirir ama SONUNDA eski haline dondurur

KULLANIM:
    cd  ...\\ALES\\backend
    python test_new_modules.py

Cikti: her modul icin [OK]/[FAIL] satirlari + sonda ozet. Cikis kodu
basarisizlik sayisidir (0 = her sey gecti).
"""

import asyncio
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

PASS, FAIL = [], []


def ok(name, detail=""):
    PASS.append(name)
    print(f"  [OK]   {name}" + (f"  — {detail}" if detail else ""))


def bad(name, err):
    FAIL.append((name, err))
    print(f"  [FAIL] {name}\n         -> {err}")


def section(title):
    print(f"\n{'='*62}\n{title}\n{'='*62}")


def check(name, fn):
    """Tek bir kontrolu calistir, hatayi yakala."""
    try:
        detail = fn()
        ok(name, detail or "")
    except AssertionError as e:
        bad(name, f"beklenti karsilanmadi: {e}")
    except Exception as e:
        bad(name, f"{type(e).__name__}: {e}")


# ══════════════════════════════════════════════════════════════════
# 0) IMPORT / SOZDIZIMI
# ══════════════════════════════════════════════════════════════════
section("0) IMPORT + SOZDIZIMI (hepsi derleniyor mu?)")

MODULES = ["long_term_memory", "resource_monitor", "runtime_state",
           "batch_queue", "credentials", "retry_util", "browser_profiles"]
loaded = {}
for m in MODULES:
    try:
        loaded[m] = __import__(m)
        ok(f"import {m}")
    except Exception as e:
        bad(f"import {m}", f"{type(e).__name__}: {e}")
        traceback.print_exc()


# ══════════════════════════════════════════════════════════════════
# 1) LONG TERM MEMORY  (gecici db)
# ══════════════════════════════════════════════════════════════════
section("1) long_term_memory — ekle / hatirla / pekistir / unut")
if "long_term_memory" in loaded:
    ltm = loaded["long_term_memory"]
    tmp_db = Path(tempfile.gettempdir()) / f"ales_ltm_test_{int(time.time())}.db"
    ltm.DB_PATH = tmp_db
    ltm._conn = None                      # yeni yola baglan

    def t_add():
        r = ltm.add("Ali Fiverr icin logo tasarimi yapiyor", kind="fact", importance=2.0)
        assert r["ok"], r
        assert not r["reinforced"], "ilk ekleme pekistirme olmamali"
        return f"id={r['id']}"

    def t_add2():
        ltm.add("Kullanici Python ve FastAPI ile calisiyor", kind="fact")
        ltm.add("Hava bugun yagmurlu", kind="note")
        return "2 kayit daha"

    def t_dup():
        r = ltm.add("Hava bugun yagmurlu", kind="note")
        assert r["reinforced"], "ayni metin pekistirilmeliydi"
        return "tekrar kayit -> pekistirme"

    def t_recall():
        r = ltm.recall("logo tasarim isi", k=3)
        assert r, "hic sonuc donmedi"
        assert "logo" in r[0]["text"].lower(), f"beklenen kayit ilk sirada degil: {r[0]['text']}"
        return f"en iyi='{r[0]['text'][:34]}...' skor={r[0]['score']}"

    def t_recall_empty():
        assert ltm.recall("") == [], "bos sorgu bos liste dondurmeli"
        return "bos sorgu guvenli"

    def t_stats():
        s = ltm.stats()
        assert s["total"] == 3, f"3 kayit bekleniyordu, {s['total']} var"
        return f"total={s['total']} embedding={s['embedding']} vec_ext={s['vec_extension']}"

    def t_forget():
        n = ltm.forget_stale()          # taze kayitlar -> hicbiri silinmemeli
        assert n == 0, f"taze kayitlar silinmemeliydi ({n} silindi)"
        return "taze kayitlar korundu"

    for n, f in [("ekleme", t_add), ("ek kayitlar", t_add2), ("tekrar->pekistirme", t_dup),
                 ("anlamsal hatirlama", t_recall), ("bos sorgu", t_recall_empty),
                 ("istatistik", t_stats), ("unutma (taze korunur)", t_forget)]:
        check(n, f)

    try:
        if ltm._conn:
            ltm._conn.close()
        os.remove(tmp_db)
        print(f"  (gecici db silindi: {tmp_db.name})")
    except Exception as e:
        print(f"  (uyari: gecici db silinemedi: {e})")


# ══════════════════════════════════════════════════════════════════
# 2) RESOURCE MONITOR  (sadece olcum)
# ══════════════════════════════════════════════════════════════════
section("2) resource_monitor — olcum + esik degerlendirme")
if "resource_monitor" in loaded:
    rm = loaded["resource_monitor"]

    def t_sample():
        s = rm.sample()
        assert "self" in s and "system" in s, "self/system anahtarlari yok"
        if not s["psutil"]:
            return "psutil YOK -> olcum atlandi (pip install psutil)"
        assert s["system"]["ram"] > 0, "sistem RAM yuzdesi 0 olamaz"
        return (f"ALES: CPU {s['self'].get('cpu')}% RAM {s['self'].get('ram')}% "
                f"({s['self'].get('ram_mb')}MB, {s['self'].get('procs')} surec) | "
                f"Sistem: CPU {s['system']['cpu']}% RAM {s['system']['ram']}%")

    def t_gpu():
        g = rm.read_gpu(force=True)
        return (f"GPU {g['util_pct']}% ({g['mem_used_mb']}/{g['mem_total_mb']}MB) "
                f"backend={rm._gpu_backend}") if g else "GPU okunamadi (normal — NVIDIA yoksa)"

    def t_eval_breach():
        fake = {"self": {"cpu": 90.0, "ram": 80.0}, "system": {}, "gpu": None}
        r = rm.evaluate(fake, {"cpu": 20.0, "ram": 30.0, "gpu": 10.0}, "self")
        assert len(r["breached"]) == 2, f"2 asim bekleniyordu: {r['breached']}"
        assert r["critical"], "90 > 20*2 -> kritik olmaliydi"
        return "yuksek degerler -> 2 asim + kritik"

    def t_eval_calm():
        fake = {"self": {"cpu": 5.0, "ram": 10.0}, "system": {}, "gpu": None}
        r = rm.evaluate(fake, {"cpu": 20.0, "ram": 30.0, "gpu": 10.0}, "self")
        assert not r["breached"], f"asim olmamaliydi: {r['breached']}"
        return "dusuk degerler -> asim yok"

    def t_gpu_skip():
        fake = {"self": {"cpu": 1.0, "ram": 1.0}, "system": {}, "gpu": None}
        r = rm.evaluate(fake, {"cpu": 20.0, "ram": 30.0, "gpu": 10.0}, "self")
        assert r["values"]["gpu"] is None, "GPU yoksa None olmali (uydurulmamali)"
        return "GPU olculemedi -> esik atlandi"

    def t_tick():
        r = rm.monitor.tick()
        assert "values" in r and "thresholds" in r
        return f"tick calisti, degerler={r['values']}"

    def t_status():
        st = rm.monitor.status()
        assert "thresholds" in st and "scope" in st
        return f"scope={st['scope']} esikler={st['thresholds']} guard={st['guard']}"

    for n, f in [("anlik olcum", t_sample), ("GPU okuma", t_gpu),
                 ("esik: asim+kritik", t_eval_breach), ("esik: sakin", t_eval_calm),
                 ("GPU yoksa atla", t_gpu_skip), ("tick", t_tick), ("status", t_status)]:
        check(n, f)


# ══════════════════════════════════════════════════════════════════
# 3) RUNTIME STATE  (sonunda geri alinir)
# ══════════════════════════════════════════════════════════════════
section("3) runtime_state — modul duraklatma / modlar / uyku")
if "runtime_state" in loaded:
    rs = loaded["runtime_state"]
    _orig_mode = None
    try:
        from config_manager import get_mode
        _orig_mode = get_mode()
    except Exception:
        pass

    def t_snapshot():
        s = rs.snapshot()
        assert "modules" in s and len(s["modules"]) >= 8
        return f"{len(s['modules'])} modul kayitli"

    def t_deferred():
        s = rs.snapshot()
        by = {m["id"]: m for m in s["modules"]}
        for mid in ("agent_s3", "aguvis", "gui_thinker", "nanobrowser"):
            assert not by[mid]["available"], f"{mid} available=False olmaliydi (ertelendi)"
        return "computer-use modulleri available=False (karar korundu)"

    def t_pause():
        assert rs.pause_module("tts", "test")
        assert rs.is_paused("tts"), "tts duraklatilmadi"
        assert rs.resume_module("tts")
        assert not rs.is_paused("tts"), "tts geri acilmadi"
        return "pause/resume calisiyor"

    def t_bad_module():
        assert not rs.pause_module("olmayan_modul"), "bilinmeyen modul kabul edilmemeli"
        return "bilinmeyen modul reddedildi"

    def t_sleep():
        rs.touch()
        assert rs.idle_seconds() < 2, "touch idle sayacini sifirlamali"
        rs.sleep_now("test")
        assert rs.snapshot()["asleep"], "uyku moduna gecmedi"
        rs.wake("test")
        assert not rs.snapshot()["asleep"], "uyanmadi"
        return "uyku/uyanma calisiyor"

    def t_headless():
        rs.set_headless(True, persist=False)
        assert rs.snapshot()["headless_mode"], "headless acilmadi"
        rs.set_headless(False, persist=False)
        assert not rs.snapshot()["headless_mode"], "headless kapanmadi"
        return "headless ac/kapa"

    def t_degrade():
        rs.on_resource_degrade({"breached": [{"metric": "cpu", "value": 95, "limit": 20}]})
        s = rs.snapshot()
        assert s["degraded"], "degraded olmaliydi"
        assert s["paused"].get("tts"), "TTS duraklatilmaliydi"
        rs.on_resource_restore({})
        assert not rs.snapshot()["degraded"], "restore olmadi"
        return "kaynak baskisi -> dusur + geri al"

    def t_tempdir():
        d = rs.temp_dir()
        assert Path(d).exists(), f"gecici dizin yok: {d}"
        return d

    for n, f in [("snapshot", t_snapshot), ("ertelenmis moduller", t_deferred),
                 ("pause/resume", t_pause), ("gecersiz modul", t_bad_module),
                 ("uyku modu", t_sleep), ("headless", t_headless),
                 ("kaynak baskisi kopruleri", t_degrade), ("temp dizin", t_tempdir)]:
        check(n, f)

    if _orig_mode:                       # modu eski haline dondur
        try:
            from config_manager import set_mode
            set_mode(_orig_mode)
            print(f"  (mod geri alindi: {_orig_mode})")
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════
# 4) BATCH QUEUE
# ══════════════════════════════════════════════════════════════════
section("4) batch_queue — toplu istek + guvenlik listesi")
if "batch_queue" in loaded:
    bq = loaded["batch_queue"]

    def t_denylist():
        for bad_a in ("run_python", "delete_file", "click", "shell", "kill_process"):
            assert not bq.is_batchable(bad_a), f"{bad_a} toplanabilir GORUNUYOR — guvenlik acigi"
        for good in ("get_weather", "read_note", "list_tasks"):
            assert bq.is_batchable(good), f"{good} toplanabilir olmaliydi"
        assert not bq.is_batchable(""), "bos eylem reddedilmeli"
        return "yikici eylemler toplanmiyor, okuma eylemleri toplaniyor"

    def t_batching():
        async def run():
            seen = []
            async def handler(items):
                seen.append(len(items))
                return [f"ok:{i['n']}" for i in items]
            q = bq.BatchQueue(handler=handler, min_batch=5, max_batch=10, max_wait_s=0.2)
            results = await asyncio.gather(*[q.add({"n": i}) for i in range(5)])
            assert results == [f"ok:{i}" for i in range(5)], results
            assert seen == [5], f"tek bir toplu cagri bekleniyordu, oldu: {seen}"
            assert q.stats["saved_calls"] == 4, q.stats
            return f"5 istek -> {len(seen)} cagri (kazanc: {q.stats['saved_calls']} cagri)"
        return asyncio.run(run())

    def t_timeout_flush():
        async def run():
            async def handler(items):
                return ["x"] * len(items)
            q = bq.BatchQueue(handler=handler, min_batch=5, max_batch=10, max_wait_s=0.15)
            t0 = time.time()
            r = await q.add({"n": 1})          # tek istek -> zaman asimiyla gonderilir
            assert r == "x", r
            return f"tek istek {round(time.time()-t0,2)}s sonra pencere dolunca gonderildi"
        return asyncio.run(run())

    def t_handler_error():
        async def run():
            async def handler(items):
                raise RuntimeError("patladi")
            q = bq.BatchQueue(handler=handler, min_batch=2, max_batch=5, max_wait_s=0.1)
            try:
                await asyncio.gather(q.add({"n": 1}), q.add({"n": 2}))
            except RuntimeError as e:
                return f"handler hatasi cagirana ulasti: {e}"
            raise AssertionError("hata yutuldu — cagiran haberdar olmali")
        return asyncio.run(run())

    for n, f in [("guvenlik listesi", t_denylist), ("toplama", t_batching),
                 ("zaman asimiyla gonderim", t_timeout_flush), ("handler hatasi", t_handler_error)]:
        check(n, f)


# ══════════════════════════════════════════════════════════════════
# 5) RETRY UTIL
# ══════════════════════════════════════════════════════════════════
section("5) retry_util — geri-alimli yeniden deneme")
if "retry_util" in loaded:
    ru = loaded["retry_util"]

    def t_classify():
        assert ru.is_retryable(TimeoutError("timed out")), "timeout yeniden denenmeli"
        assert ru.is_retryable(Exception("HTTP 503 unavailable"))
        assert not ru.is_retryable(ValueError("invalid selector syntax")), \
            "kalici hata yeniden denenmemeli"
        return "gecici/kalici hata ayrimi dogru"

    def t_succeeds_after_2():
        calls = {"n": 0}
        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise TimeoutError("timed out")
            return "sonuc"
        r = ru.retry(flaky, attempts=3, base_s=0.01)
        assert r == "sonuc" and calls["n"] == 3, (r, calls)
        return f"3. denemede basarili (toplam {calls['n']} cagri)"

    def t_permanent_no_retry():
        calls = {"n": 0}
        def broken():
            calls["n"] += 1
            raise ValueError("invalid selector syntax")
        try:
            ru.retry(broken, attempts=3, base_s=0.01)
        except ValueError:
            assert calls["n"] == 1, f"kalici hatada 1 deneme olmaliydi, {calls['n']} oldu"
            return "kalici hata -> bosuna tekrar yok"
        raise AssertionError("hata firlatilmaliydi")

    def t_backoff_growth():
        d1 = ru.sleep_before(1, 1.0, 30.0, jitter=False)
        d2 = ru.sleep_before(2, 1.0, 30.0, jitter=False)
        d3 = ru.sleep_before(3, 1.0, 30.0, jitter=False)
        assert (d1, d2, d3) == (1.0, 2.0, 4.0), (d1, d2, d3)
        assert ru.sleep_before(10, 1.0, 15.0, jitter=False) == 15.0, "max_s siniri calismali"
        return "1s -> 2s -> 4s, ust sinir 15s"

    def t_async():
        async def run():
            calls = {"n": 0}
            async def flaky():
                calls["n"] += 1
                if calls["n"] < 2:
                    raise ConnectionError("connection reset")
                return "ok"
            r = await ru.aretry(flaky, attempts=3, base_s=0.01)
            assert r == "ok", r
            return f"asenkron yeniden deneme ({calls['n']} cagri)"
        return asyncio.run(run())

    for n, f in [("hata siniflandirma", t_classify), ("2 hatadan sonra basari", t_succeeds_after_2),
                 ("kalici hata", t_permanent_no_retry), ("geri-alim buyumesi", t_backoff_growth),
                 ("asenkron", t_async)]:
        check(n, f)


# ══════════════════════════════════════════════════════════════════
# 6) CREDENTIALS  (gercek key'lere DOKUNMAZ)
# ══════════════════════════════════════════════════════════════════
section("6) credentials — kasa (gercek key'ler DEGISTIRILMEZ)")
if "credentials" in loaded:
    cr = loaded["credentials"]
    TEST_NAME = "ales_test_secret"

    def t_backend():
        return f"kasa={'VAR' if cr.available() else 'YOK'} backend={cr.backend_name()}"

    def t_mask():
        assert cr.mask("sk-abcdef123456") == "...3456", cr.mask("sk-abcdef123456")
        assert cr.mask("short") == "****"
        assert cr.mask("") == ""
        return "maskeleme sirri ifsa etmiyor"

    def t_roundtrip():
        if not cr.available():
            return "kasa yok -> atlandi (pip install keyring)"
        assert cr.set_secret(TEST_NAME, "deger-123"), "yazilamadi"
        assert cr.get_secret(TEST_NAME) == "deger-123", "okunan deger farkli"
        assert cr.has_secret(TEST_NAME)
        assert cr.delete_secret(TEST_NAME), "silinemedi"
        assert not cr.has_secret(TEST_NAME), "silindikten sonra hala var"
        return "yaz/oku/sil dongusu tamam"

    def t_audit():
        a = cr.audit()
        assert "findings" in a
        exposed = a["exposed"]
        return (f"config.json'da DUZ METIN {a['exposed_count']} key: {exposed}"
                if exposed else "config.json'da duz metin key YOK")

    for n, f in [("kasa backend", t_backend), ("maskeleme", t_mask),
                 ("yaz/oku/sil", t_roundtrip), ("denetim", t_audit)]:
        check(n, f)


# ══════════════════════════════════════════════════════════════════
# 7) BROWSER PROFILES  (test profili olusturup siler)
# ══════════════════════════════════════════════════════════════════
section("7) browser_profiles — izole profil kayit defteri")
if "browser_profiles" in loaded:
    bp = loaded["browser_profiles"]
    TEST_PID = "__test_profile"

    def t_create():
        bp.delete_profile(TEST_PID, wipe=True)      # kalinti varsa temizle
        r = bp.create_profile(TEST_PID, "Test Profili", "otomatik test")
        assert r["ok"], r
        return f"olusturuldu: {r['profile']['id']}"

    def t_duplicate():
        r = bp.create_profile(TEST_PID)
        assert not r["ok"], "ayni kimlik iki kez kabul edilmemeli"
        return "tekrar olusturma reddedildi"

    def t_invalid():
        r = bp.create_profile("!!!")
        assert not r["ok"], "gecersiz kimlik kabul edilmemeli"
        return "gecersiz kimlik reddedildi"

    def t_list():
        ids = [p["id"] for p in bp.list_profiles()]
        assert TEST_PID in ids, ids
        return f"{len(ids)} profil listelendi"

    def t_no_secrets():
        """Onemli: profil dosyasinda sifre alani OLMAMALI."""
        raw = bp.PROFILES_FILE.read_text(encoding="utf-8").lower()
        for word in ("password", "sifre", "api_password", "secret"):
            assert word not in raw, f"profiles.json'da '{word}' gecmemeli!"
        return "profil dosyasinda sir yok (tasarim geregi)"

    def t_delete():
        r = bp.delete_profile(TEST_PID, wipe=True)
        assert r["ok"], r
        assert TEST_PID not in [p["id"] for p in bp.list_profiles()]
        return "silindi + temizlendi"

    for n, f in [("olustur", t_create), ("tekrar olustur", t_duplicate),
                 ("gecersiz kimlik", t_invalid), ("listele", t_list),
                 ("sir icermiyor", t_no_secrets), ("sil", t_delete)]:
        check(n, f)


# ══════════════════════════════════════════════════════════════════
# 8) MAIN.PY  (route kaydi — sunucu baslatmadan)
# ══════════════════════════════════════════════════════════════════
section("8) main.py — endpoint kaydi + kazanc ozeti")

def t_main_import():
    import main
    paths = {r.path for r in main.app.routes}
    need = ["/earnings", "/credentials/audit", "/credentials/migrate",
            "/browser-profiles", "/stats", "/modes",
            # Faz 2-6 uclari: yeni panellerin okudugu her uc burada.
            # Bir uc silinir/adi degisirse panel sessizce bos gorunur,
            # bu yuzden route kaydi testte tutuluyor.
            "/env-status", "/jit", "/predictive/stats",
            "/batch-inference/stats", "/spec-cache/stats",
            "/token-optimizer/stats", "/moa/stats", "/cer/stats",
            "/reflection/stats", "/self-evolution/stats",
            "/darwin-godel/trial", "/openclaw/status", "/evocua/status",
            "/adaptive-timeouts/stats", "/config-versions",
            "/auto-discovery/status"]
    missing = [p for p in need if p not in paths]
    assert not missing, f"eksik endpoint: {missing}"
    return f"{len(paths)} route kayitli, hepsi var"

def t_earnings_summary():
    import main
    from datetime import datetime as dt
    now = dt.now().isoformat()
    s = main._earnings_summary([
        {"amount": 100, "currency": "TRY", "source": "fiverr", "time": now},
        {"amount": 50,  "currency": "TRY", "source": "bionluk", "time": now},
        {"amount": 25,  "currency": "TRY", "source": "fiverr", "time": "2020-01-01T10:00:00"},
    ])
    assert s["total"] == 175.0, s["total"]
    assert s["today"] == 150.0, s["today"]
    assert len(s["daily"]) == 30, len(s["daily"])
    top = s["by_source"][0]
    assert top["source"] == "fiverr" and top["amount"] == 125.0, s["by_source"]
    return (f"total={s['total']} today={s['today']} "
            f"kaynak={[(x['source'], x['amount']) for x in s['by_source']]} "
            f"trend={len(s['daily'])} gun")

def t_stats_shape():
    import main
    s = asyncio.run(main.get_stats())
    for k in ("activity_by_minute", "earnings", "activity_by_day", "top_tools"):
        assert k in s, f"/stats icinde '{k}' yok"
    assert len(s["activity_by_minute"]) == 60, len(s["activity_by_minute"])
    return f"/stats anahtarlari tamam ({len(s['activity_by_minute'])} dakika kovasi)"

for n, f in [("main import + routeler", t_main_import),
             ("kazanc ozeti (kaynak+trend)", t_earnings_summary),
             ("/stats sekli", t_stats_shape)]:
    check(n, f)


# ══════════════════════════════════════════════════════════════════
# 9) FAZ 2-6 MODULLERI — DAVRANIS
# ══════════════════════════════════════════════════════════════════
# NEDEN AYRI BIR BOLUM: verify_phases.py "modul yuklendi mi, panelin
# okudugu anahtar var mi" sorusuna bakar (SOZLESME). Burada sorulan
# baska: mekanizma GERCEKTEN calisiyor mu (DAVRANIS). Onbellek yaziliyor
# ama okunamiyorsa iki kontrolden yalnizca bu ikincisi fark eder.
#
# Bu dosyanin bastaki sozu ("hicbir gercek veriyi bozmaz") burada da
# gecerli: agent_jit / CER / adaptive_timeouts APPDATA'ya kalici JSON
# yaziyor, testte o dosyalara DOKUNULMAZ — _isolate() ile gecici bir
# dizine yonlendirilip sonunda geri alinirlar.
import contextlib
import shutil

section("9) Faz 2-6 — davranis (gecici dosyalar, gercek veri bozulmaz)")


@contextlib.contextmanager
def _isolate(mod, file_attr, resets):
    """Modulun kalici dosyasini gecici bir yola cevirir, cikista geri alir.

    resets: {global_adi: taze_deger} — tembel yuklenen onbellek/sayac
    globallerini sifirlamak icin (yoksa test disk'teki gercek veriyi
    gorur ve sayac beklentileri tutmaz).
    """
    old_file = getattr(mod, file_attr)
    old_vals = {k: getattr(mod, k) for k in resets}
    td = tempfile.mkdtemp(prefix="ales_test_")
    try:
        setattr(mod, file_attr, Path(td) / "test.json")
        for k, v in resets.items():
            setattr(mod, k, v)
        yield
    finally:
        setattr(mod, file_attr, old_file)
        for k, v in old_vals.items():
            setattr(mod, k, v)
        shutil.rmtree(td, ignore_errors=True)


PHASE_MODULES = ["agent_jit", "speculative_cache", "token_optimizer",
                 "contextual_experience_replay", "adaptive_timeouts",
                 "darwin_godel", "batch_inference", "mixture_of_agents",
                 "self_evolution", "reflection_agent", "versioned_config",
                 "auto_model_discovery", "predictive", "evo_cua_bridge",
                 "openclaw_bridge"]
ph = {}
for m in PHASE_MODULES:
    try:
        ph[m] = __import__(m)
        ok(f"import {m}")
    except Exception as e:
        bad(f"import {m}", f"{type(e).__name__}: {e}")

if "agent_jit" in ph:
    _jit = ph["agent_jit"]

    def t_jit_typing():
        """`Optional` importu eksikti: modul NameError ile hic yuklenmiyordu."""
        _jit.lookup_graph("herhangi bir gorev metni")   # NameError vermemeli
        return "lookup_graph cagrilabiliyor (Optional importu yerinde)"

    def t_jit_roundtrip():
        with _isolate(_jit, "_JIT_FILE",
                      {"_entries": None,
                       "_stats": {k: 0 for k in _jit._stats}}):
            task = "ekran goruntusu al ve aktif pencere adini yaz"
            _jit.store(task, "print('x')", "python")
            p = _jit.peek(task)
            assert p is not None, "store edilen gorev peek() ile bulunamadi"
            assert _jit._stats["hits"] == 0, \
                f"peek() hit sayacina dokunmamali: {_jit._stats}"
            hit = _jit.lookup(task)
            assert hit is not None, "lookup() isabet vermedi"
            assert _jit._stats["hits"] == 1, _jit._stats
            assert _jit.invalidate(hit["key"]) is True
            assert _jit.peek(task) is None, "invalidate sonrasi hala bulunuyor"
        return "store -> peek(sayac artmaz) -> lookup(artar) -> invalidate"

    def t_jit_graph_id():
        """store_graph ve lookup_graph AYNI kimligi uretmeli.

        Eskiden __init__ task.encode(), lookup_graph task.strip().encode()
        kullaniyordu: bosluklu her gorevde onbellek sessizce hic tutmazdi.
        """
        task = "  bosluklu gorev metni  "
        g = _jit.ExecutionGraph(task=task)
        _jit.store_graph(g)
        try:
            assert _jit.lookup_graph(task) is g, "ayni metinle bulunamadi"
            assert _jit.lookup_graph(task.strip()) is g, \
                "store/lookup ayni kimligi uretmiyor (bosluk farki)"
        finally:
            _jit._compiled_graphs.pop(g.graph_id, None)
        return "cizge kimligi bosluk farkina dayanikli"

    # ── CIZGE DERLEME: main.py'ye BAGLANAN yol ────────────────────────
    # Bu uc test, "cizge katmani yazildi ama hicbir yerden cagrilmiyor"
    # durumunun geri donmesini engelliyor. Eski compile_task_to_graph
    # gorev METNINDEN dugum uyduruyordu ve urettigi "execute_task" adli
    # arac main.py'nin arac tablosunda YOKTU; yani derlenen her cizge
    # calisma aninda basarisiz olurdu. Yeni yol modelin KENDI cagrilarini
    # zamanliyor, o yuzden arac adlari tanimi geregi dogru.
    _SAFE = {"get_weather", "get_crypto_prices", "web_search"}

    def t_jit_graph_would_help():
        """Kapi dogru yerde acilip kapanmali."""
        assert _jit.graph_would_help([("get_weather", {})], _SAFE) is False, \
            "tek cagri icin cizge kurulmamali"
        assert _jit.graph_would_help(
            [("get_weather", {}), ("click_at", {})], _SAFE) is False, \
            "1 guvenli + 1 yan etkili: paralellesecek bir sey yok"
        assert _jit.graph_would_help(
            [("get_weather", {}), ("get_crypto_prices", {}),
             ("click_at", {})], _SAFE) is True, \
            "2 guvenli cagri ayni katmanda: cizge ise yarar"
        assert _jit.graph_would_help(
            [("click_at", {}), ("get_weather", {}),
             ("type_text", {}), ("get_crypto_prices", {})], _SAFE) is False, \
            "guvenli cagrilar yan etkililerle ayrilmis: hicbiri eslesmiyor"
        return "kapi: <2 ayni-katman guvenli cagri -> False"

    def t_jit_graph_layers():
        """Bagimlilik kurali: guvenliler paralel, yan etkili BARIYER."""
        calls = [("get_weather", {"city": "Ankara"}),
                 ("get_crypto_prices", {}),
                 ("click_at", {"x": 1, "y": 2}),
                 ("web_search", {"query": "x"})]
        g = _jit.compile_calls_to_graph("karisik tur", calls, _SAFE)
        try:
            assert len(g.nodes) == 4, g.to_dict()
            # main.py sonuclari n1..nN sirasiyla geri esliyor; adlandirma
            # SOZLESMEDIR, degisirse tool_call_id eslesmesi bozulur.
            assert [g.nodes[f"n{i}"].tool for i in range(1, 5)] == \
                [c[0] for c in calls], "dugum sirasi cagri sirasindan farkli"
            assert g.nodes["n1"].depends_on == [], "ilk guvenli cagri serbest"
            assert g.nodes["n2"].depends_on == [], "ikinci guvenli cagri serbest"
            assert set(g.nodes["n3"].depends_on) == {"n1", "n2"}, \
                f"yan etkili cagri bariyer olmali: {g.nodes['n3'].depends_on}"
            assert g.nodes["n4"].depends_on == ["n3"], \
                "bariyerden sonraki cagri bariyeri beklemeli"
        finally:
            _jit._compiled_graphs.pop(g.graph_id, None)
        return "n1,n2 paralel · n3 bariyer · n4 bariyerden sonra"

    def t_jit_graph_execute():
        """execute_graph gercekten paralellestirmeli ve HATAYI GIZLEMEMELI."""
        calls_seen = []

        async def _fake(tool, args):
            calls_seen.append(tool)
            if tool == "get_crypto_prices":
                raise RuntimeError("saglayici cevap vermedi")
            await asyncio.sleep(0.01)
            return f"{tool}-ok"

        calls = [("get_weather", {}), ("get_crypto_prices", {}),
                 ("click_at", {})]
        g = _jit.compile_calls_to_graph("hata testi", calls, _SAFE)
        try:
            r = asyncio.run(_jit.execute_graph(g, _fake))
            # HER DUGUM TAM BIR KEZ: n2 hata verdi ama n3 yine calisti ve
            # hicbir dugum iki kez cagrilmadi (main.py'nin yedek yoluna
            # dusmemesi tam buna bagli).
            assert sorted(calls_seen) == sorted(c[0] for c in calls), calls_seen
            assert r["steps_run"] == 3, r
            assert r["layers"] == 2, f"2 katman beklenir (n1|n2, sonra n3): {r}"
            assert r["ok"] is False, "basarisiz dugum varken ok=True olmamali"
            outs = r["outputs"]
            # KRITIK: basarisiz dugum None DONMEMELI. main.py sonuclari
            # metin olarak gecmise yaziyor; None gelirse model aracin bos
            # cevap verdigini sanar ve hata modelden SAKLANMIS olur.
            assert outs["n2"] is not None, "hata modelden saklandi (None)"
            assert outs["n2"].startswith("❌"), outs["n2"]
            assert "saglayici cevap vermedi" in outs["n2"], outs["n2"]
            assert outs["n1"] == "get_weather-ok", outs
            assert outs["n3"] == "click_at-ok", \
                "bariyer, kardesi hata verse bile calismali"
            # main.py'nin geri esleme bicimi: n1..nN, hepsi dolu olmali
            mapped = [outs.get(f"n{i+1}") for i in range(len(calls))]
            assert all(m is not None for m in mapped), mapped
        finally:
            _jit._compiled_graphs.pop(g.graph_id, None)
        return "3 dugum / 2 katman · hatali dugum '❌' ile modele ulasiyor"

    for n, f in [("agent_jit typing", t_jit_typing),
                 ("agent_jit blok onbellegi", t_jit_roundtrip),
                 ("agent_jit cizge kimligi", t_jit_graph_id),
                 ("agent_jit cizge kapisi", t_jit_graph_would_help),
                 ("agent_jit cizge katmanlari", t_jit_graph_layers),
                 ("agent_jit cizge yurutme", t_jit_graph_execute)]:
        check(n, f)

if "speculative_cache" in ph:
    _spec = ph["speculative_cache"]

    def t_spec_roundtrip():
        before = _spec.stats()["hits"]
        _spec.put("__ales_test_key", {"v": 1}, category="__test")
        got = _spec.get("__ales_test_key", category="__test")
        assert got == {"v": 1}, got
        assert _spec.stats()["hits"] == before + 1, \
            f"isabet sayaci artmadi: {before} -> {_spec.stats()['hits']}"
        assert _spec.get("__ales_yok", category="__test") is None
        _spec.invalidate("__test")
        assert _spec.get("__ales_test_key", category="__test") is None, \
            "invalidate sonrasi girdi hala duruyor"
        return "put/get isabet, olmayan anahtar None, invalidate temizledi"

    def t_spec_kv():
        prompt = "Sen ALES adli bir yardimcisin. Kurallar: " * 4
        _spec.cache_kv_prefix(prompt, {"tokens": 40})
        assert _spec.get_kv_prefix(prompt) is not None, \
            "ayni prompt icin KV onek bulunamadi"
        s = _spec.stats()
        assert s["kv_entries"] >= 1, s
        return f"KV onek isabeti, kv_entries={s['kv_entries']}"

    def t_spec_transitions_are_read():
        """SpecCache'in OGRENDIGI gecis, predictive tarafindan OKUNMALI.

        Bu test bir REGRESYON kapisi. Onceden main.py her turda
        register_transition() cagiriyordu ama predict_next_steps() hicbir
        yerden okunmuyordu: modul YALNIZCA yaziyordu, ogrendigi hicbir sey
        bir ise yaramiyordu. main.py'deki yorum "predictive bunu kullanir"
        diyordu, kod DEMIYORDU. Asagidaki iddia o baglantiyi kilitliyor.
        """
        _prd = ph.get("predictive")
        if _prd is None:
            return "predictive yuklenemedi - baglanti dogrulanamadi"
        assert _prd.speculative_cache is not None, \
            "predictive, speculative_cache'i import etmiyor"
        # ALLOWLIST'te OLAN bir hedef ogretiyoruz: read_file.
        _spec.register_transition("__ales_kaynak", "read_file")
        out = _prd.predict_next("__ales_kaynak", {}, user_message="")
        assert ("read_file", {}) in out, \
            f"SpecCache gecisi on-getirme listesine girmedi: {out}"
        # GUVENLIK KAPISI: SpecCache serbest metin de ogrenir ("click" gibi).
        # READONLY_PREFETCHABLE'da olmayan hicbir ad buradan sizmamali.
        _spec.register_transition("__ales_kaynak2", "click_at")
        out2 = _prd.predict_next("__ales_kaynak2", {}, user_message="")
        assert all(t in _prd.READONLY_PREFETCHABLE for t, _ in out2), out2
        assert not any(t == "click_at" for t, _ in out2), \
            f"yan etkili arac on-getirmeye sizdi: {out2}"
        return "SpecCache gecisi okunuyor · yan etkili ad allowlist'te elendi"

    for n, f in [("spec cache yaz/oku", t_spec_roundtrip),
                 ("KV onek yeniden kullanimi", t_spec_kv),
                 ("SpecCache gecisleri okunuyor", t_spec_transitions_are_read)]:
        check(n, f)

if "token_optimizer" in ph:
    _tok = ph["token_optimizer"]

    def t_tok_messages():
        msgs = ([{"role": "system", "content": "kural " * 50}]
                + [{"role": "user", "content": "eski soru " * 40},
                   {"role": "assistant", "content": "eski cevap " * 40}] * 6
                + [{"role": "user", "content": "GUNCEL SORU: dosyayi ac"}])
        out, info = _tok.optimize_messages(msgs, task_hint="dosya")
        assert isinstance(out, list) and out, out
        assert isinstance(info, dict), info
        # EN KRITIK DEGISMEZ: guncel kullanici turu asla dusurulmez/kirpilmaz.
        assert out[-1]["content"] == "GUNCEL SORU: dosyayi ac", out[-1]
        assert any(m.get("role") == "system" for m in out), \
            "sistem mesaji tamamen dusurulmus"
        return f"{len(msgs)} -> {len(out)} mesaj, bilgi: {sorted(info)[:4]}"

    def t_tok_compress():
        big = "satir icerigi\n" * 2000
        out = _tok.compress_tool_result(big, max_chars=1500)
        assert len(out) < len(big), "kisaltma hic yapilmadi"
        assert len(out) <= 1800, f"max_chars asildi: {len(out)}"
        return f"{len(big)} -> {len(out)} karakter"

    def t_tok_budget():
        c_easy = _tok.estimate_complexity("merhaba")
        c_hard = _tok.estimate_complexity(
            "tum dosyalari analiz et, hatalari bul, duzelt, testleri "
            "calistir ve rapor yaz " * 3)
        assert c_hard >= c_easy, (c_easy, c_hard)
        b = _tok.get_token_budget(c_hard)
        assert isinstance(b, int) and b > 0, b
        return f"karmasiklik {c_easy} -> {c_hard}, butce {b} token"

    for n, f in [("mesaj optimizasyonu", t_tok_messages),
                 ("arac cikti kisaltma", t_tok_compress),
                 ("token butcesi", t_tok_budget)]:
        check(n, f)

if "contextual_experience_replay" in ph:
    _cer = ph["contextual_experience_replay"]

    def t_cer_cycle():
        with _isolate(_cer, "_CER_FILE",
                      {"_experiences": [], "_loaded": True,
                       "_stats": {k: 0 for k in _cer._stats}}):
            _cer.record_experience("dosya acma gorevi",
                                   [{"tool": "open_file", "ok": True}], True,
                                   reflection="dogrudan arac cagrisi yeterli")
            _cer.record_experience("basarisiz deneme gorevi",
                                   [{"tool": "x", "ok": False}], False,
                                   reflection="yanlis arac secildi")
            s = _cer.stats()
            assert s["total_experiences"] == 2, s
            assert s["successes"] == 1 and s["reflections"] == 1, s
            rel = _cer.retrieve_relevant_experiences("dosya acma", k=2)
            assert rel, "kaydedilen deneyim geri getirilemedi"
            inj = _cer.format_cer_prompt_injection("dosya acma")
            assert isinstance(inj, str), type(inj)
        return "kayit -> istatistik -> geri getirme -> prompt enjeksiyonu"

    check("deneyim tekrari (CER)", t_cer_cycle)

if "adaptive_timeouts" in ph:
    _ato = ph["adaptive_timeouts"]

    def t_ato_dynamic():
        """Zaman asimi OLCUMDEN turetilmeli, sabit olmamali."""
        with _isolate(_ato, "_FILE", {"_data": {}, "_loaded": True}):
            for _ in range(6):
                _ato.record_latency("fast", 2.0, True)
            t_fast = _ato.get_timeout("fast")
            for _ in range(6):
                _ato.record_latency("heavy", 40.0, True)
            t_heavy = _ato.get_timeout("heavy")
            assert t_heavy > t_fast, (t_fast, t_heavy)
            b = _ato.BOUNDS["fast"]
            assert b["min"] <= t_fast <= b["max"], (t_fast, b)
            # Hic olcum yoksa cagiranin verdigi deger kullanilir, uydurulmaz.
            assert _ato.get_timeout("__olcum_yok__", fallback=7.5) == 7.5
            st = _ato.get_stats()
            assert "fast" in st and st["fast"]["samples"] == 6, st
            return f"fast={t_fast:.1f}s heavy={t_heavy:.1f}s (olcumden)"

    check("dinamik zaman asimi", t_ato_dynamic)

if "darwin_godel" in ph:
    _dgm = ph["darwin_godel"]

    def t_dgm_no_fabrication():
        """Hic denenmemis varyanta SAYI verilmemeli.

        Bu projede daha once rastgele fitness uretilmisti; regresyonu
        yakalamak icin test edilir.
        """
        v = _dgm._new_variant("__test_variant", "test", "test stratejisi")
        f = _dgm.compute_fitness(v)
        assert f is None, f"0 denemeli varyanta uyum skoru verildi: {f}"
        return "0 deneme -> fitness None ('bilinmiyor' != 'kotu')"

    def t_dgm_trial_shape():
        ts = _dgm.trial_status()
        assert "min_trials" in ts, ts
        for who in ("champion", "challenger"):
            v = ts.get(who)
            if not isinstance(v, dict):
                continue
            fit = v.get("fitness")
            assert fit is None or isinstance(fit, (int, float)), (who, fit)
            if fit is None:
                assert int(v.get("trials", 0) or 0) < ts["min_trials"], \
                    f"{who}: fitness None ama deneme sayisi yeterli"
        champ = (ts.get("champion") or {}).get("fitness")
        return (f"min_trials={ts['min_trials']} · sampiyon uyum={champ} "
                "(None = henuz olculmedi)")

    for n, f in [("uydurma uyum skoru yok", t_dgm_no_fabrication),
                 ("A/B deneme sekli", t_dgm_trial_shape)]:
        check(n, f)


# ══════════════════════════════════════════════════════════════════
# ISE YARAMAZ OTOMATIK YEDEGIN GERI ALINMASI
#
# NEDEN BU TEST VAR — olculmus bir ariza: 2026-09-05 tarihli
# backend-dist/ALES_log.txt dosyasinda sohbet TAMAMEN olu. Sebep bir model
# adi hatasi degil, ALES'in KENDI 2026-08-26'da yazdigi iki yedekti:
#   cerebras: llama-3.3-70b        -> gemma-4-31b  (her cagride 402)
#   groq:     llama-3.3-70b-versatile -> allam-2-7b (arac cagirmayi desteklemiyor)
# set_override bir kez yazildiktan sonra HICBIR kod yolunda gozden
# gecirilmiyordu; performance zinciri de yalnizca ["fast","fallback"]
# oldugu icin iki katmanin ikisi de olu yedege bagliydi. Yani sohbet
# KALICI olarak calismiyordu ve geri alacak mekanizma yoktu.
section("MODEL YEDEGI GERI ALMA (model_registry)")
try:
    import model_registry as _mreg
except Exception as e:
    bad("import model_registry", f"{type(e).__name__}: {e}")
    _mreg = None

if _mreg is not None:
    ok("import model_registry")

    def _fresh_registry():
        """GERCEK onbellege ASLA dokunmayan bos bir kayit defteri.

        %APPDATA%\\ALES\\model_cache.json canli kullanici verisidir; test
        onu ne okumali ne yazmali."""
        td = tempfile.mkdtemp(prefix="ales_mreg_")
        r = _mreg.ModelRegistry(cache_path=os.path.join(td, "c.json"))
        return r, td

    def t_unusable_classifier():
        """402 ve 'arac cagirmiyor' KALICI; kota/404 ise DEGIL."""
        u = _mreg.substitute_unusable
        assert u("Error code: 402 - {'message': 'Payment required to access "
                 "this resource.', 'code': 'payment_required'}"), "402 kacti"
        assert u("Error code: 400 - {'error': {'message': '`tool calling` is "
                 "not supported with this model'}}"), "arac cagirma kacti"
        assert u("No endpoints found that support tool use"), "openrouter kacti"
        # YANLIS POZITIF PAHALI: bunlar gecici, yedek geri ALINMAMALI.
        assert not u("Error code: 429 - rate limit exceeded"), "429 yanlis yakalandi"
        assert not u("Error code: 404 - Model does not exist"), "404 yanlis yakalandi"
        assert not u("insufficient_quota"), "kota yanlis yakalandi"
        return "402 + arac-cagirmiyor kalici · 429/404/kota gecici sayildi"

    def t_retire_removes_and_blacklists():
        """Geri alma: degisimi SIL ve ise yaramaz yedegi kara listeye at."""
        r, td = _fresh_registry()
        try:
            r.set_override("cerebras", "llama-3.3-70b", "gemma-4-31b", "test")
            assert r.effective_model("cerebras", "llama-3.3-70b") == "gemma-4-31b"
            out = r.retire_override("cerebras", "llama-3.3-70b",
                                    "402 payment_required")
            assert out == "gemma-4-31b", f"geri alinan ad yanlis: {out}"
            # Degisim gitti -> kullanicinin YAZDIGI ad geri geldi.
            assert r.effective_model("cerebras", "llama-3.3-70b") == \
                "llama-3.3-70b", r.overrides
            # Ise yaramaz yedek kara listede -> suggest onu bir daha SECEMEZ.
            assert r.is_blacklisted("cerebras", "gemma-4-31b"), r.blacklist
            # Ikinci cagri sessizce "" donmeli, patlamamali.
            assert r.retire_override("cerebras", "llama-3.3-70b", "x") == ""
            return "degisim silindi · yedek kara listede · tekrar cagri guvenli"
        finally:
            shutil.rmtree(td, ignore_errors=True)

    def t_retire_never_touches_user_model():
        """Kullanicinin KENDI modeli kara listeye ALINMAMALI.

        Geri alma yalnizca ALES'in koydugu yedegi hedefler. Kullanicinin
        yazdigi adi da kara listeye atsaydik, 402 alan bir hesapta modeli
        kalici olarak kaybettirirdik — oysa 402 bir faturalandirma
        tercihi olabilir."""
        r, td = _fresh_registry()
        try:
            r.set_override("groq", "llama-3.3-70b-versatile", "allam-2-7b", "t")
            r.retire_override("groq", "llama-3.3-70b-versatile", "no tools")
            assert not r.is_blacklisted("groq", "llama-3.3-70b-versatile"), \
                "kullanicinin modeli kara listeye alindi — olmamali"
            assert r.is_blacklisted("groq", "allam-2-7b"), r.blacklist
            return "yalnizca yedek kara listede · kullanici modeli korundu"
        finally:
            shutil.rmtree(td, ignore_errors=True)

    def t_suggest_wont_repick_retired():
        """Geri alinan yedek bir daha SECILMEMELI (sonsuz dongu korumasi)."""
        r, td = _fresh_registry()
        try:
            r.providers["cerebras"] = {"ids": ["gemma-4-31b", "llama-4-17b"],
                                       "meta": {}, "status": "ok"}
            r.set_override("cerebras", "llama-3.3-70b", "gemma-4-31b", "t")
            r.retire_override("cerebras", "llama-3.3-70b", "402")
            again = r.suggest("cerebras", "llama-3.3-70b")
            assert "gemma-4-31b" not in again, \
                f"geri alinan yedek tekrar onerildi: {again}"
            return f"tekrar onerilmedi · kalan adaylar: {again or 'yok'}"
        finally:
            shutil.rmtree(td, ignore_errors=True)

    def t_router_hook_exists():
        """Router GERCEKTEN bu yolu cagiriyor mu?

        Mekanizmanin var olmasi yetmez — akis ACILISINDA cagrilmasi gerekir,
        cunku 402 tam orada dusuyor. 'Kodu yazdim' ile 'kod calisiyor'
        arasindaki farki bu test tutuyor."""
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "model_router.py"), encoding="utf-8").read()
        assert "substitute_unusable" in src, \
            "model_router ise yaramaz yedek kontrolunu HIC yapmiyor"
        assert src.count("_retire_substitute(") >= 3, \
            ("geri alma tek yerde: hem _call_layer hem stream_chat "
             "cagirmali (sohbet AKIS yolunu kullaniyor)")
        return "kontrol hem _call_layer hem stream_chat acilisinda"

    for n, f in [("kalici/gecici hata ayrimi", t_unusable_classifier),
                 ("geri al + kara listeye at", t_retire_removes_and_blacklists),
                 ("kullanici modeline dokunulmaz", t_retire_never_touches_user_model),
                 ("geri alinan tekrar secilmez", t_suggest_wont_repick_retired),
                 ("router bu yolu cagiriyor", t_router_hook_exists)]:
        check(n, f)


# ══════════════════════════════════════════════════════════════════
section("BIG ALES / PUTER (mod + kopru + fail-open)")
# NEDEN BU BOLUM: Big ALES'in her parcasi ayri dosyada — mod tanimi
# config_manager'da, orkestrator model_router'da, kopru main.py'de,
# cagri arayuzde. Bu dagilim tam olarak "mekanizma var ama kimse
# cagirmiyor" arizasina davetiye. Onu YAZARAK degil, TEST EDEREK
# kapatiyoruz (ayni sinif daha once speculative_cache'te ve JIT
# cizgesinde yasandi).
# ══════════════════════════════════════════════════════════════════
def _src(fname):
    return open(os.path.join(os.path.dirname(os.path.abspath(__file__)), fname),
                encoding="utf-8").read()


def t_big_ales_mode_defined():
    """Mod tanimli, cozumlenebilir ve zinciri BOS DEGIL."""
    import config_manager as cm
    assert "big_ales" in cm.DEFAULT_MODES, "mod DEFAULT_MODES'ta yok"
    mc = cm.get_mode_config("big_ales")
    assert mc["mode"] == "big_ales", mc["mode"]
    assert mc["big_ales"] is True, "mod big_ales bayragini tasimiyor"
    assert mc["chain"], "zincir bos -> mod hic calismaz"
    assert mc["big_ales_model"] in cm.BIG_ALES_MODELS, mc["big_ales_model"]
    # Fast Path kapali olmali: acik olsa basit istekler orkestratoru
    # ATLAR, yani mod adini tasidigi isi yapmaz.
    assert mc["fast_path"] is False, "fast_path acik: orkestrator atlanir"
    ids = [m["id"] for m in cm.list_modes()]
    assert "big_ales" in ids, "UI mod listesinde gorunmuyor"
    return "mod cozumleniyor · %d katman · %s" % (len(mc["chain"]),
                                                 mc["big_ales_model"])


def t_big_ales_router_calls_it():
    """Orkestrator ANA SOHBET YOLUNDAN cagriliyor mu?

    stream_chat main.py'nin kullandigi yol; sadece route_chat'e baglamak
    modu sohbette OLU birakirdi."""
    src = _src("model_router.py")
    assert "puter_connector" in src, "router Puter'i hic tanimiyor"
    assert src.count("big_ales_orchestrate(") >= 3, \
        ("tanim + stream_chat + route_chat = en az 3 gecis bekleniyor; "
         "eksikse mod bazi yollarda calismaz")
    i_def = src.index("async def big_ales_orchestrate")
    i_stream = src.index("async def stream_chat")
    assert src.index("big_ales_orchestrate(", i_stream) > i_stream, \
        "stream_chat orkestratoru cagirmiyor"
    assert i_def < i_stream, "tanim stream_chat'ten SONRA (NameError riski)"
    return "stream_chat + route_chat cagiriyor"


def t_big_ales_fail_open():
    """Puter patlarsa istek OLDUGU GIBI zincire gitmeli (sohbet olmez)."""
    import asyncio as _a
    import model_router as mr
    import puter_connector as pc

    msgs = [{"role": "system", "content": "S"},
            {"role": "user", "content": "orijinal istek"}]
    mc = {"big_ales": True, "big_ales_model": pc.DEFAULT_MODEL,
          "big_ales_timeout_s": 5.0}

    async def _boom(*a, **k):
        raise RuntimeError("arayuz bagli degil")

    orig = pc.rewrite_request
    pc.rewrite_request = _boom
    try:
        out = _a.run(mr.big_ales_orchestrate(msgs, mc))
    finally:
        pc.rewrite_request = orig
    assert out[-1]["content"] == "orijinal istek", \
        "hata sonrasi mesaj bozuldu: %r" % (out[-1],)

    # Mod kapaliyken hic dokunmamali (mutlu yolda sifir maliyet).
    same = _a.run(mr.big_ales_orchestrate(msgs, {"big_ales": False}))
    assert same is msgs, "mod kapali ama liste yine kopyalandi"
    return "hata -> istek korunuyor · mod kapali -> liste hic dokunulmuyor"


def t_big_ales_rewrite_replaces_last_user():
    """Basarili gecis SON kullanici mesajini degistirir, digerlerini DEGIL,
    ve cagiranin listesini YERINDE bozmaz."""
    import asyncio as _a
    import model_router as mr
    import puter_connector as pc

    msgs = [{"role": "user", "content": "eski soru"},
            {"role": "assistant", "content": "cevap"},
            {"role": "user", "content": "asil istek"}]
    snapshot = [dict(m) for m in msgs]

    async def _rw(text, model_id=None, timeout=None):
        return "YENIDEN YAZILMIS: " + text

    orig = pc.rewrite_request
    pc.rewrite_request = _rw
    try:
        out = _a.run(mr.big_ales_orchestrate(
            msgs, {"big_ales": True, "big_ales_model": pc.DEFAULT_MODEL}))
    finally:
        pc.rewrite_request = orig
    assert out[2]["content"] == "YENIDEN YAZILMIS: asil istek", out[2]
    assert out[0]["content"] == "eski soru", "onceki kullanici mesaji bozuldu"
    assert out[1]["content"] == "cevap", "asistan mesaji bozuldu"
    assert msgs == snapshot, "CAGIRANIN listesi yerinde degistirildi"
    return "yalnizca son kullanici mesaji · cagiranin listesi korunuyor"


def t_big_ales_multimodal_untouched():
    """Icerik liste ise (gorsel + metin) yeniden yazma YAPILMAZ."""
    import asyncio as _a
    import model_router as mr
    import puter_connector as pc

    msgs = [{"role": "user", "content": [{"type": "text", "text": "bak"},
                                         {"type": "image_url", "image_url": {}}]}]

    async def _rw(*a, **k):
        raise AssertionError("cok kipli icerik yeniden yazilmaya kalkildi")

    orig = pc.rewrite_request
    pc.rewrite_request = _rw
    try:
        out = _a.run(mr.big_ales_orchestrate(
            msgs, {"big_ales": True, "big_ales_model": pc.DEFAULT_MODEL}))
    finally:
        pc.rewrite_request = orig
    assert out is msgs, "gorsel iceren mesaj degistirildi -> gorsel kaybolur"
    return "gorsel iceren istek dokunulmadan geciyor"


def t_big_ales_model_whitelist():
    """Beyaz liste disi model REDDEDILIR (Puter hesabinda ucret dogurur)."""
    import asyncio as _a
    import puter_connector as pc
    # Devre kesici acikken cagri hemen doner ve BASKA bir hata mesaji
    # verir; bu test onu degil beyaz listeyi olcuyor, o yuzden sifirla.
    pc.reset_breaker()
    try:
        _a.run(pc.call_puter_model("selam", model_id="gpt-4o"))
    except pc.PuterError as e:
        assert "izin verilmeyen model" in str(e), str(e)
        # Cagiran hatasi devreyi ETKILEMEMELI.
        assert pc.breaker_state()["fail_streak"] == 0, \
            "beyaz liste hatasi devre kesiciyi tetikledi"
        return "beyaz liste disi model engellendi: %d izinli model" % len(
            pc.ALLOWED_MODELS)
    raise AssertionError("beyaz liste disi model kabul edildi")


def t_big_ales_breaker():
    """Devre kesici: giris yoksa her mesaj zaman asimi BEKLEMEMELI.

    Somut ariza: Big ALES acik ama kullanici Puter'a hic giris yapmadi.
    Kesici olmasa her istek 60s bekleyip fail-open ile devam eder — sohbet
    olmez ama kullanilamaz hale gelir. Ust uste iki hatadan sonra yol
    aninda hata dondurmeli.
    """
    import asyncio as _a
    import puter_connector as pc

    real_load = pc.load_session
    pc.reset_breaker()
    pc.load_session = lambda: {}          # "giris yapilmamis" durumu
    try:
        # Arayuz bagli degil -> her cagri PuterError (SAYILAN tur).
        for _ in range(pc._FAIL_LIMIT):
            try:
                _a.run(pc.call_puter_model("selam"))
            except pc.PuterError:
                pass
        st = pc.breaker_state()
        assert st["fail_streak"] >= pc._FAIL_LIMIT, st
        assert st["open"] is True, "kesici acilmadi -> her mesaj beklemeye devam"
        t0 = time.time()
        try:
            _a.run(pc.call_puter_model("selam"))
            raise AssertionError("kesici acikken cagri hata vermedi")
        except pc.PuterError as e:
            assert "devre disi" in str(e), str(e)
        dt = time.time() - t0
        assert dt < 1.0, "kesici acikken cagri %.1fs surdu (beklemeden " \
                         "donmeliydi)" % dt
        # Basarili bir cagri ya da giris kesiciyi kapatir.
        pc.reset_breaker()
        assert pc.breaker_state()["open"] is False
        return "%d hatadan sonra aninda doner (%.0fms) · sifirlanabiliyor" % (
            pc._FAIL_LIMIT, dt * 1000)
    finally:
        pc.load_session = real_load
        pc.reset_breaker()


def t_big_ales_http_origin():
    """Paketlenmis arayuz GERCEK bir http kaynagindan mi yukleniyor?

    Ali'nin bildirdigi ariza: paketlenmis ALES.exe acilir acilmaz
    puter.js "Unsupported Protocol - file://" veriyordu. Sebep
    electron-main.js'in loadFile() kullanmasiydi; file:// bir opaque
    origin oldugu icin puter.js orada CALISAMAZ (ayar sorunu degil,
    protokol sorunu).

    Duzeltme iki parcali ve IKISI DE gerekli:
      1. electron-main.js -> loadURL('http://localhost:8000')
      2. package.json -> dist/ extraResources ile exe'nin yanina kopyalanir,
         yoksa backend arayuzu bulamaz (main.py _find_webui_dir) ve pencere
         arayuz yerine 503 JSON gosterir.
    Bir parca geri alinirsa ariza AYNEN geri gelir, o yuzden ikisi de
    burada olculuyor.
    """
    import json as _j
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    em = open(os.path.join(root, "electron-main.js"), encoding="utf-8").read()
    pkg = _j.loads(open(os.path.join(root, "package.json"),
                        encoding="utf-8").read())

    # 1) http kaynagi kullaniliyor, file:// yolu TAMAMEN kalkti.
    assert "http://localhost:8000" in em, \
        "electron-main.js arayuzu backend kaynagindan yuklemiyor"
    assert "loadURL(targetURL)" in em, "loadURL cagrisi yok"
    # "mainWindow.loadFile(" arariyoruz, ciplak "loadFile(" degil: dosyada
    # arizayi ACIKLAYAN yorumlar da bu kelimeyi geciyor ve onlari silmek
    # bir daha ayni hataya dusmemek icin en degerli parca.
    assert "mainWindow.loadFile(" not in em, \
        "loadFile hala cagriliyor -> file:// kaynagi geri gelmis, " \
        "puter.js patlar"

    # 2) Backend'in servis edecegi kopya paketleniyor.
    extras = pkg.get("build", {}).get("extraResources") or []
    froms = {(e.get("from"), e.get("to")) for e in extras
             if isinstance(e, dict)}
    assert ("dist", "dist") in froms, \
        "package.json extraResources icinde dist->dist yok -> backend " \
        "arayuzu bulamaz, pencerede 503 JSON gorunur"
    assert ("backend-dist/ales-backend.exe", "ales-backend.exe") in froms, \
        "backend exe artik paketlenmiyor"

    # 3) Backend tarayici ACMAMALI: main.py varsayilan olarak
    #    _open_browser_when_ready() ile sistem tarayicisini aciyor; Electron
    #    bayragi vermezse cift tiklamada pencerenin YANINDA bir tarayici
    #    sekmesi de acilir ("tarayici YOK" sartinin ihlali).
    assert "ALES_NO_BROWSER" in em, \
        "Electron backend'i tarayici bayragi olmadan baslatiyor -> " \
        "cift tiklamada tarayici acilir"
    assert "env: backendEnv" in em, "env spawn'a gecirilmiyor"

    # 4) Service worker: file://'da HIC kaydolmuyordu, http'de KAYDOLUYOR.
    #    Yani onbellek mantigi artik masaustunde de devrede. API yanitlari
    #    onbelleklenirse Ayarlar paneli donmus Puter oturumu/devre kesici
    #    durumu gosterir ve kullanici bunu anlayamaz.
    sw = open(os.path.join(root, "frontend", "public", "sw.js"),
              encoding="utf-8").read()
    assert "isStatic" in sw, \
        "sw.js hala kara listeye dayaniyor -> API GET'leri onbelleklenir"
    assert "if (!isStatic) return" in sw, "API/dinamik yollar aga gitmiyor"

    # 5) Yedek yol (file:// ile acilirsa kopru) hala duruyor.
    app = open(os.path.join(root, "frontend", "src", "App.jsx"),
               encoding="utf-8").read()
    assert "location.protocol === 'file:'" in app, \
        "file:// yedek yolu silinmis"
    return "loadURL(http://localhost:8000) · dist paketleniyor · " \
           "tarayici kapali · sw API onbelleklemiyor · kopru yedegi duruyor"


def t_big_ales_popup_hardened():
    """Puter giris penceresi ALES'in IC koprusunu goremiyor.

    Ali'nin sarti: "All Puter session handling must be secure." Buradaki
    tehdit somut ve http'ye gecisle YENI AKTIF OLDU:

    Electron'da window.open ile acilan cocuk pencere ust pencerenin
    webPreferences'ini -- PRELOAD DAHIL -- devralir. Big ALES girisi tam
    olarak boyle bir pencere acip icinde puter.com yukluyor. Kapi olmazsa
    o UZAK sayfada window.ales tanimli olur; loadConfig() config.json'daki
    CANLI API anahtarlarini dondurur, saveConfig() uzerine yazar, quit()
    uygulamayi kapatir.

    Acik ONCE de vardi ama ULASILAMAZDI: arayuz file:// kaynagindaydi,
    puter.js orada kimlik dogrulamayi hic baslatmiyordu, yani pencere hic
    acilmiyordu. loadURL('http://localhost:8000') ile pencere GERCEKTEN
    aciliyor -- bu yuzden iki katman birlikte olculuyor.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pre = open(os.path.join(root, "preload.js"), encoding="utf-8").read()
    em = open(os.path.join(root, "electron-main.js"), encoding="utf-8").read()

    # 1) ASIL KORUMA: koprü yalnizca guvenilen kaynakta kuruluyor.
    #    Sadece "kapi tanimli mi" degil, exposeInMainWorld'un kapinin
    #    ICINDE oldugunu da dogruluyoruz -- kapiyi yazip disinda cagirmak
    #    en olasi geri gitme sekli ve hicbir hata vermez.
    assert "TRUSTED_ORIGIN" in pre, \
        "preload.js kaynak kapisi yok -> window.ales puter.com'da tanimli olur"
    i_gate = pre.find("if (TRUSTED_ORIGIN)")
    i_expose = pre.find("exposeInMainWorld")
    assert i_gate != -1, "if (TRUSTED_ORIGIN) blogu yok"
    assert i_expose > i_gate, \
        "exposeInMainWorld kapinin DISINDA cagriliyor -> kapi hicbir sey " \
        "korumuyor"
    assert "127.0.0.1" in pre and "localhost" in pre, \
        "kapi yerel kaynaklari tanimiyor -> arayuzun kendi dugmeleri olur"

    # 2) IKINCI KATMAN: cocuk pencere sikilastiriliyor. Ana pencerede
    #    webSecurity KAPALI (Puter API'sine CORS olmadan ulasmak icin);
    #    uzak bir sayfada kapali kalmasinin hicbir gerekcesi yok.
    assert "setWindowOpenHandler" in em, \
        "cocuk pencereler sikilastirilmiyor -> ust pencerenin gevsek " \
        "ayarlari puter.com'a aynen geciyor"
    h = em[em.find("setWindowOpenHandler"):]
    h = h[:6000]
    assert "webSecurity: true" in h, \
        "cocuk pencerede webSecurity geri acilmiyor"
    assert "devTools: false" in h, "uzak sayfada devTools kapatilmiyor"
    assert "action: 'deny'" in h, \
        "izin verilmeyen semalar reddedilmiyor -> sayfa harici program " \
        "tetikleyebilir"
    # Pencere ENGELLENMEMELI: Puter jetonu opener'a postMessage ile donuyor,
    # 'deny' ile giris hicbir zaman tamamlanmaz.
    assert "action: 'allow'" in h, \
        "pencere tamamen engellenmis -> Puter girisi asla tamamlanamaz"
    return "window.ales yalnizca yerel kaynakta · cocuk pencerede " \
           "webSecurity acik, devTools kapali · yalnizca https + yerel http"



def t_big_ales_bridge_wired():
    """Kopru main.py'de GERCEKTEN bagli mi (iki yon birlikte)?"""
    src = _src("main.py")
    assert "import puter_connector" in src, "main.py modulu hic yuklemiyor"
    assert "register_ws_source" in src, \
        "WebSocket kaynagi kaydedilmiyor -> connector istemciyi hic bulamaz"
    assert 'puter_result' in src, "arayuzden gelen sonuc hic islenmiyor"
    assert "puter_connector.resolve(" in src, "bekleyen cagri hic cozulmuyor"
    assert '"/big-ales"' in src, "Ayarlar paneli icin uc yok"
    # Arayuz tarafi: cagriyi gercekten yapan yer.
    app = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "frontend", "src", "App.jsx"),
        encoding="utf-8").read()
    assert "puter_call" in app, "arayuz istegi dinlemiyor"
    assert "puter.ai.chat" in app, "arayuz Puter'i hic cagirmiyor"
    assert "puter_result" in app, "arayuz sonucu geri gondermiyor"
    idx = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "frontend", "index.html"),
        encoding="utf-8").read()
    assert "js.puter.com" in idx, "puter.js sayfaya hic yuklenmiyor"
    return "backend kopru + arayuz cagrisi + SDK etiketi: hepsi bagli"


def t_big_ales_http_bridge():
    """file:// kapisi: kopru sayfasi UCTAN UCA bagli mi?

    Bu testin sebebi somut: paketlenmis Electron arayuzu file:// ile
    aciyor ve orada puter.js girisi calismaz (opaque origin). Kopru
    sayfasi tam bu yuzden var; parcalarindan biri kopsa Big ALES
    PAKETLENMIS uygulamada sessizce olur ama gelistirmede (http)
    calismaya devam eder -- yani en zor yakalanan ariza sinifi.
    """
    import puter_connector as pc
    src = _src("main.py")
    app = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "frontend", "src", "App.jsx"),
        encoding="utf-8").read()

    # 1) Sayfa gercekten uretiliyor ve puter.js'i yukluyor.
    assert isinstance(pc.BRIDGE_HTML, str) and len(pc.BRIDGE_HTML) > 400
    assert "js.puter.com" in pc.BRIDGE_HTML, "kopru sayfasi SDK'yi yuklemiyor"
    assert "/puter-bridge/result" in pc.BRIDGE_HTML, "sayfa sonucu gondermiyor"
    assert "/puter-bridge/job/" in pc.BRIDGE_HTML, "sayfa isi cekmiyor"
    # 2) Uc uclar main.py'de kayitli.
    for uc in ('"/puter-bridge"', '"/puter-bridge/job/{rid}"',
               '"/puter-bridge/result"'):
        assert uc in src, "uc yok: %s" % uc
    assert "pc.BRIDGE_HTML" in src or "puter_connector.BRIDGE_HTML" in src, \
        "sayfa hicbir uctan servis edilmiyor"
    # 3) Arayuz file:// durumunda kopruyu ACIYOR ve reply ETMIYOR.
    assert "location.protocol === 'file:'" in app, \
        "arayuzde file:// kapisi yok -> paketlenmis uygulamada calismaz"
    assert "d.bridge" in app, "arayuz kopru adresini kullanmiyor"
    # 4) Is kaydi gercekten dolduruluyor ve get_job ile okunabiliyor.
    pc._jobs["TEST-RID"] = {"model": pc.DEFAULT_MODEL, "prompt": "x",
                            "system": pc.ORCHESTRATOR_SYSTEM}
    try:
        j = pc.get_job("TEST-RID")
        assert j.get("prompt") == "x", j
        assert pc.get_job("YOK-BOYLE-BIR-ID") == {}, "bilinmeyen id sizdiriyor"
        # resolve() isi de TEMIZLEMELI, yoksa istemler bellekte birikir.
        pc.resolve("TEST-RID", {"ok": True, "text": "y"})
        assert pc.get_job("TEST-RID") == {}, "resolve isi temizlemiyor"
    finally:
        pc._jobs.pop("TEST-RID", None)
    # 5) call_puter_model istegi kopru adresiyle gonderiyor mu?
    csrc = _src("puter_connector.py")
    assert '"bridge"' in csrc, "puter_call mesajinda kopru adresi yok"
    return "kopru sayfasi + 3 uc + file:// kapisi + is kaydi: bagli"


def t_big_ales_session_encrypted():
    """Jeton saklama: sifreleme ve izin daraltma GERCEKTEN calisiyor mu?"""
    import json as _json
    import tempfile
    import puter_connector as pc

    real = pc.SESSION_FILE
    tmp = Path(tempfile.mkdtemp(prefix="ales_puter_")) / "puter_session.enc"
    pc.SESSION_FILE = tmp
    try:
        assert pc.save_session({"signed_in": True, "username": "ali",
                                "token": "GIZLI-JETON-123"}), "yazilamadi"
        wrap = _json.loads(tmp.read_text(encoding="utf-8"))
        # DIKKAT: burada ham dosyada duz metin aramak YETMEZ — icerik zaten
        # base64'lu, yani sifreleme HIC olmasa da jeton dosyada goze
        # carpmaz. Gercek iddia: base64 COZULDUKTEN SONRA da jeton
        # gorunmuyor. Zayif surumu (sadece ham dosyaya bakan) bilerek
        # birakmadim; sifrelemeyi kapatsan bile gecerdi.
        import base64 as _b64
        payload = _b64.b64decode(wrap["data"])
        if pc._IS_WINDOWS:
            assert wrap["enc"] == "dpapi", \
                "Windows'ta DPAPI beklenir, bulunan: %s" % wrap["enc"]
            assert b"GIZLI-JETON-123" not in payload, \
                "jeton base64 altinda DUZ METIN duruyor -> sifreleme yok"
            assert b"signed_in" not in payload, "govde sifrelenmemis"
        back = pc.load_session()
        assert back.get("token") == "GIZLI-JETON-123", back
        assert pc.has_session() is True
        info = pc.session_info()
        assert "GIZLI-JETON-123" not in _json.dumps(info), \
            "session_info jetonu sizdiriyor"
        assert info["encryption"] in ("dpapi", "none"), info["encryption"]
        assert pc.clear_session() and not tmp.exists()
        assert pc.load_session() == {}, "silinen oturum yine okunuyor"
        return "gidis-donus OK · %s · cozulmus govdede jeton YOK" % wrap["enc"]
    finally:
        pc.SESSION_FILE = real
        try:
            shutil.rmtree(tmp.parent, ignore_errors=True)
        except Exception:
            pass


for _n, _f in [("big_ales modu tanimli", t_big_ales_mode_defined),
               ("router orkestratoru cagiriyor", t_big_ales_router_calls_it),
               ("Puter patlarsa sohbet olmez", t_big_ales_fail_open),
               ("yalnizca son istek yeniden yazilir",
                t_big_ales_rewrite_replaces_last_user),
               ("gorsel iceren istek korunur", t_big_ales_multimodal_untouched),
               ("model beyaz listesi", t_big_ales_model_whitelist),
               ("devre kesici beklemeden doner", t_big_ales_breaker),
               ("kopru iki yonde bagli", t_big_ales_bridge_wired),
               ("http kopru sayfasi bagli", t_big_ales_http_bridge),
               ("arayuz http kaynagindan yukleniyor", t_big_ales_http_origin),
               ("giris penceresi sikilastirildi", t_big_ales_popup_hardened),
               ("jeton sifreli saklaniyor", t_big_ales_session_encrypted)]:
    check(_n, _f)


# ══════════════════════════════════════════════════════════════════
section("OZET")
print(f"  GECTI : {len(PASS)}")
print(f"  KALDI : {len(FAIL)}")
if FAIL:
    print("\n  Basarisiz olanlar:")
    for name, err in FAIL:
        print(f"    - {name}: {err}")
    print("\n  Bu ciktinin tamamini bana yapistirin, duzeltirim.")
else:
    print("\n  Her sey gecti. Moduller main.py'ye baglanmaya hazir.")
sys.exit(len(FAIL))
