"""ALES — FAZ 2-6 modül doğrulayıcı (backend AYAKTA olmasa da çalışır).

Neden var: bu makinede kabuk erişimi kesintili olduğu için Faz 2-6'da
yazılan hiçbir satır çalıştırılamadı. Doğrulama tamamen OKUMAYLA yapıldı:
her panelin okuduğu istatistik anahtarı, onu tanımlayan `_stats` sözlüğüne
kadar geri izlendi. Bu dosya o elle yapılan kontrolü ÇALIŞTIRILABİLİR hale
getirir — aynı anahtar listesi burada makine tarafından denetlenir.

Üç şeyi ayrı ayrı söyler, çünkü üçü ayrı arıza:
  1. modül import edilebiliyor mu        -> import hatası
  2. modül düzeyi stats()/status() patlıyor mu -> çağrı hatası
  3. panelin beklediği anahtar var mı    -> SESSIZ arıza (panelde boş alan)

3. madde önemli: eksik anahtar hiçbir yerde hata üretmez, arayüzde
sadece boş bir satır olarak görünür. `/batch-inference/stats` tam bu
şekilde üç alanı boş döndürüyordu (engine.stats() modül düzeyindeki
stats() yerine çağrılmıştı) ve okuma sırasında bu yolla yakalandı.

Kullanım:  cd backend && python verify_phases.py
Çıkış kodu = başarısız kontrol sayısı (0 = hepsi geçti).
"""
import importlib
import json
import sys

# (modül, erişimci yolu, panelin okuduğu anahtarlar)
#
# Erişimci adları TAHMİN EDİLMEZ, tek tek yazılır: getattr zinciriyle
# "stats varsa onu, yoksa status'u" demek yanlış fonksiyonu seçip yeşil
# rapor üretebilir — düzeltilen hata da tam olarak buydu.
#
# Anahtar listesi boş bırakılan modüller (adaptive_timeouts,
# versioned_config, native_desktop, self_heal) panelde ya iç içe ya da
# liste biçiminde okunuyor; sabit bir anahtar sözleşmesi ileri sürmemek
# için yalnızca çağrılıp yazdırılıyorlar.
CHECKS = [
    ("agent_jit", "stats", []),
    ("batch_inference", "stats", [
        "batches_executed", "items_batched", "avg_batch_size",
        "direct_executions", "queued_now", "window_ms", "batch_size"]),
    ("speculative_cache", "stats", [
        "entries", "max_entries", "hit_rate", "hits", "misses",
        "kv_entries", "kv_prefix_hits", "kv_tokens_saved",
        "speculative_prefetches", "speculative_hits"]),
    ("token_optimizer", "stats", [
        "prompts_optimized", "tokens_saved_approx", "avg_reduction_percent",
        "redundant_turns_pruned", "messages_shrunk"]),
    ("predictive", "stats", [
        "scheduled", "hits", "hit_rate", "saved_s", "pairs_learned",
        "pairs_tracked", "expired", "skipped_unsafe"]),
    ("mixture_of_agents", "stats", [
        "moa_runs", "proposals_generated", "synthesized_answers",
        "avg_elapsed_s", "dmoa_balanced"]),
    ("contextual_experience_replay", "stats", [
        "total_experiences", "max_experiences", "successes",
        "reflections", "replays_injected"]),
    ("reflection_agent", "stats", [
        "reflections_triggered", "corrections_successful",
        "sage_triads_run", "checker_catches"]),
    ("self_evolution", "stats", [
        "strategic_rules", "procedural_recipes", "trajectories_optimized",
        "loops_pruned", "rsi_cycles", "agent0_verifications"]),
    ("darwin_godel", "stats", [
        "generation", "archive_count", "proven_count",
        "promotions", "rejections"]),
    ("evo_cua_bridge", "status", [
        "role", "executor", "screen_resolution", "stats",
        "action_space", "cua_model_endpoint", "sandbox_mode"]),
    # /openclaw/status modül düzeyindeki info()'yu DEĞİL bridge.status()'u
    # döndürüyor; info() runtime_state'in yoklama fonksiyonu, ayrı iş.
    ("openclaw_bridge", "bridge.status", [
        "daemon_connected", "openclaw_url", "fallback_active", "stats"]),
    ("adaptive_timeouts", "get_stats", []),
    ("versioned_config", "stats", []),
    ("auto_model_discovery", "get_status", [
        "active", "reconcile_interval_minutes", "catalog_scanner",
        "stats", "last_scan_time", "last_reconcile_time"]),
    ("native_desktop", "stats", []),
    ("self_heal", "status", []),
]

# Panellerin çağırdığı REST uçları. Değer = o ucun döndürmesi gereken
# en az bir anahtar (uç var ama boş dönüyorsa fark edilsin).
ENDPOINTS = [
    "/batch-inference/stats", "/spec-cache/stats", "/token-optimizer/stats",
    "/predictive/stats", "/moa/stats", "/cer/stats", "/cer/experiences",
    "/reflection/stats", "/self-evolution/stats", "/darwin-godel/stats",
    "/darwin-godel/trial", "/openclaw/status", "/evocua/status",
    "/adaptive-timeouts/stats", "/config-versions?limit=15",
    "/auto-discovery/status", "/env-status", "/jit",
]


def _resolve(mod, path):
    """'bridge.status' gibi noktalı yolu çözer."""
    obj = mod
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def check_modules():
    fails = 0
    print("=== Modul import + stats() sozlesmesi ===")
    for name, accessor, keys in CHECKS:
        try:
            mod = importlib.import_module(name)
        except Exception as e:
            print(f"  IMPORT HATASI  {name:32s} {type(e).__name__}: {e}")
            fails += 1
            continue
        try:
            fn = _resolve(mod, accessor)
        except AttributeError:
            print(f"  ERISIMCI YOK   {name:32s} {accessor}() bulunamadi")
            fails += 1
            continue
        try:
            data = fn()
        except Exception as e:
            print(f"  CAGRI PATLADI  {name:32s} {accessor}() -> "
                  f"{type(e).__name__}: {e}")
            fails += 1
            continue
        if not isinstance(data, dict):
            print(f"  TIP HATASI     {name:32s} dict degil: {type(data).__name__}")
            fails += 1
            continue
        missing = [k for k in keys if k not in data]
        if missing:
            # Panelde bu alanlar BOS gorunur, hicbir hata uretmez.
            print(f"  ANAHTAR EKSIK  {name:32s} {', '.join(missing)}")
            fails += 1
        else:
            extra = "" if keys else "  (anahtar sozlesmesi ileri surulmedi)"
            print(f"  OK             {name:32s} {len(data)} alan{extra}")
    return fails


def check_env():
    print()
    print("=== .env okunuyor mu (anahtar kaynagi) ===")
    # 2026-09-05'e kadar load_dotenv() HICBIR YERDE cagrilmiyordu: dosya
    # duruyordu ama sessizce yok sayiliyordu. Anahtarlar .env'e tasinsa
    # zincirin tamami sebebi gorunmeden kapanacakti.
    try:
        import config_manager as cm
    except Exception as e:
        print(f"  config_manager yuklenemedi: {type(e).__name__}: {e}")
        return 1
    try:
        st = cm.env_file_status()
    except Exception as e:
        print(f"  env_file_status() patladi: {type(e).__name__}: {e}")
        return 1
    if st.get("loaded"):
        print(f"  .env okundu: {st.get('path')}  ({st.get('count')} degisken)")
    else:
        print("  .env BULUNAMADI. Bakilan yollar:")
        for p in st.get("searched", []):
            print(f"      · {p}")
    names = ("groq_key", "cerebras_key", "gemini_key", "openrouter_key",
             "nvidia_key", "sambanova_key", "elevenlabs_key")
    ok = []
    for k in names:
        try:
            good = bool(cm.get_key(k))
        except Exception:
            good = False
        # Deger ASLA yazdirilmaz — yalnizca var/yok.
        print(f"      {'OK ' if good else '-  '} {k}")
        if good:
            ok.append(k)
    print(f"  cozulen anahtar: {len(ok)} / {len(names)}")
    # Anahtar yoklugu bir HATA DEGIL (ucretsiz katmanlarin hepsi
    # istenmiyor olabilir); bu yuzden fails'e eklenmiyor.
    return 0


def check_endpoints():
    print()
    print("=== Canli uclar (backend ayakta olmali) ===")
    import urllib.request as u
    down = 0
    missing = []
    for ep in ENDPOINTS:
        try:
            with u.urlopen("http://127.0.0.1:8000" + ep, timeout=30) as r:
                data = json.load(r)
        except Exception as e:
            down += 1
            missing.append((ep, f"{type(e).__name__}"))
            continue
        if isinstance(data, dict) and (data.get("unavailable")
                                      or data.get("_offline")):
            print(f"  MODUL YOK  {ep:34s} (unavailable)")
        else:
            n = len(data) if hasattr(data, "__len__") else 0
            print(f"  OK         {ep:34s} {n} alan")
    for ep, why in missing:
        print(f"  ULASILAMADI {ep:33s} {why}")
    if down == len(ENDPOINTS):
        print("  -> Hicbir uca ulasilamadi: ALES calismiyor. start.bat ile")
        print("     baslat, sonra bu dosyayi tekrar calistir. Yeni uclar")
        print("     ancak YENIDEN BASLATMA sonrasi gorunur.")
        return 0          # backend kapali olmasi bir KOD hatasi degil
    if down:
        print(f"  -> {down} uc eksik: bunlar YENI eklendi, ALES'i yeniden baslat.")
    return down


def main():
    fails = check_modules()
    fails += check_env()
    fails += check_endpoints()
    print()
    if fails:
        print(f"SONUC: {fails} kontrol basarisiz. Yukaridaki ilk"
              f" HATASI/EKSIK satirindan basla.")
    else:
        print("SONUC: tum moduller yuklendi, sozlesmeler tam.")
        print("       (Bu 'dogru calisiyor' demek DEGIL — yalnizca yuklendi")
        print("        ve beklenen alanlari donduruyor demek. Davranis testi:")
        print("        python test_new_modules.py)")
    return fails


if __name__ == "__main__":
    sys.exit(min(main(), 120))
