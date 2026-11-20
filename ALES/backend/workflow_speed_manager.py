"""
workflow_speed_manager.py — ALES mobil gorev pipeline orkestratoru.

Ultra-hizli, non-blocking asenkron akis. Bir "feed" (gorev listesi) alir,
her gorevi siniflandirir, ogrenir (ilk kez) veya cache'ten hizli calistirir
(sonraki kez), Twitter ban korumasini uygular, hata olursa self-healing
danismanla kendini onarir.

Akis:
  feed -> classify -> [twitter gate] -> template var mi?
      var  -> FAST-RUN  (metin okumadan, cached oranlarla, sub-1sn)
      yok  -> FIRST-RUN (talimati analiz et, URL cek, UI zonlarini bul,
                         X%/Y% oranlarini templates.json'a yaz)
  basarisiz -> 2 retry -> ask_advisor_ai (override/skip)

Global durum (Twitter):
  twitter_follow_count = 0
  twitter_cooldown_until = None
  10 follow -> 300s cooldown. Cooldown'da SADECE twitter_follow atlanir;
  twitter_like ve tum instagram gorevleri tam hizda devam eder.
"""
import asyncio
import json
import re
import time
import traceback
from pathlib import Path

import adb_engine as adb
from advisor import ask_advisor_ai, vision_locate
from phone_speed_control import load_settings, get_active_profile

try:
    from config_manager import get_appdata_dir
    TEMPLATES_FILE = get_appdata_dir() / "templates.json"
except Exception:
    TEMPLATES_FILE = Path("templates.json")

# ─── KATEGORILER ─────────────────────────────────────────────────
CATEGORIES = [
    "instagram_follow", "instagram_story_like", "instagram_comment",
    "instagram_repost", "twitter_like", "twitter_follow",
]

# Kategori -> (uygulama paketi, deep-link ureticisi, aranan buton metinleri)
CATEGORY_SPEC = {
    "instagram_follow": {
        "package": "com.instagram.android",
        "link": adb.instagram_profile_link,
        "targets": ["Takip Et", "Follow", "Takip et"],
        "action_label": "Takip Et / Follow butonu",
    },
    "instagram_story_like": {
        "package": "com.instagram.android",
        "link": adb.instagram_profile_link,
        "targets": ["Beğen", "Like", "Story", "Hikaye"],
        "action_label": "hikayeyi begenme (kalp) alani",
    },
    "instagram_comment": {
        "package": "com.instagram.android",
        "link": adb.instagram_profile_link,
        "targets": ["Yorum", "Comment", "Add a comment", "Yorum ekle"],
        "action_label": "yorum yazma alani",
    },
    "instagram_repost": {
        "package": "com.instagram.android",
        "link": adb.instagram_profile_link,
        "targets": ["Paylaş", "Repost", "Share", "Gönder"],
        "action_label": "paylas/repost butonu",
    },
    "twitter_like": {
        "package": "com.twitter.android",
        "link": adb.twitter_profile_link,
        "targets": ["Beğen", "Like", "Beğeniler"],
        "action_label": "tweet begenme (kalp) butonu",
    },
    "twitter_follow": {
        "package": "com.twitter.android",
        "link": adb.twitter_profile_link,
        "targets": ["Takip Et", "Follow", "Takip et"],
        "action_label": "Takip Et / Follow butonu",
    },
}

# Siniflandirma icin anahtar kelime imzalari (talimat metninden)
_CLASSIFY_RULES = [
    ("instagram_repost", ["repost", "yeniden paylaş", "reels paylaş", "instagram paylaş"]),
    ("instagram_comment", ["yorum", "comment", "yorum yap"]),
    ("instagram_story_like", ["hikaye", "story", "storyi beğen", "story like", "hikayeyi beğen"]),
    ("instagram_follow", ["instagram takip", "insta takip", "ig takip", "instagram follow", "instagramda takip"]),
    ("twitter_follow", ["twitter takip", "x takip", "twitter follow", "x follow", "twitterda takip", "takip et twitter"]),
    ("twitter_like", ["twitter beğen", "tweet beğen", "twitter like", "x beğen", "tweet like"]),
    # daha genel duşuşler (yukaridakiler eslesmezse)
    ("instagram_follow", ["instagram", "insta", " ig "]),
    ("twitter_follow", ["twitter", " x "]),
]


def classify_task(instruction: str) -> str:
    """Talimat metnini 6 kategoriden birine sokar. Bulamazsa None."""
    if not instruction:
        return None
    t = f" {instruction.lower()} "
    for cat, kws in _CLASSIFY_RULES:
        if any(kw in t for kw in kws):
            return cat
    return None


# ─── HEDEF (URL / KULLANICI) CIKARIMI ────────────────────────────
_URL_RE = re.compile(r"https?://[^\s]+")
_USER_RE = re.compile(r"@([A-Za-z0-9._]{2,})")


def extract_target(instruction: str, category: str) -> dict:
    """Talimattan hedef URL ve/veya kullanici adini cikarir, deep-link uretir."""
    url_m = _URL_RE.search(instruction or "")
    username = None
    if url_m:
        raw = url_m.group(0).rstrip(".,)")
        # url icindeki kullanici adini cek
        um = re.search(r"(?:instagram\.com|twitter\.com|x\.com)/(?:_u/)?([A-Za-z0-9._]+)", raw)
        if um:
            username = um.group(1)
    if not username:
        at = _USER_RE.search(instruction or "")
        if at:
            username = at.group(1)

    spec = CATEGORY_SPEC.get(category, {})
    link = None
    if username and spec.get("link"):
        link = spec["link"](username)
    elif url_m:
        link = url_m.group(0).rstrip(".,)")
    return {"username": username, "deep_link": link, "package": spec.get("package")}


# ─── TEMPLATES.JSON (ogrenilen sablonlar) ────────────────────────
_templates_lock = asyncio.Lock()


def _load_templates() -> dict:
    if TEMPLATES_FILE.exists():
        try:
            return json.loads(TEMPLATES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_templates(data: dict):
    TEMPLATES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def _store_template(category: str, step: dict):
    """Ogrenilen adimi (X%/Y% orani + eslesme metinleri) kalici yaz."""
    async with _templates_lock:
        data = _load_templates()
        entry = data.get(category, {"category": category, "steps": [], "runs": 0})
        entry["package"] = CATEGORY_SPEC.get(category, {}).get("package")
        entry["steps"] = [step]  # tek adimli aksiyonlar (follow/like) icin yeterli
        entry.setdefault("runs", 0)
        data[category] = entry
        _save_templates(data)


async def _bump_template_runs(category: str):
    async with _templates_lock:
        data = _load_templates()
        if category in data:
            data[category]["runs"] = data[category].get("runs", 0) + 1
            _save_templates(data)


# ─── TWITTER BAN KORUMASI (global durum) ─────────────────────────
twitter_follow_count = 0
twitter_cooldown_until = None
_tw_lock = asyncio.Lock()


async def _twitter_gate(category: str) -> tuple:
    """
    Twitter follow icin ban korumasi kapisi. (allowed, reason) doner.
    Cooldown'da SADECE twitter_follow bloklanir - twitter_like ve tum
    instagram gorevleri serbest.
    """
    global twitter_follow_count, twitter_cooldown_until
    if category != "twitter_follow":
        return True, None
    async with _tw_lock:
        now = time.time()
        if twitter_cooldown_until and now < twitter_cooldown_until:
            remain = int(twitter_cooldown_until - now)
            return False, f"twitter follow cooldown ({remain}s kaldi)"
        if twitter_cooldown_until and now >= twitter_cooldown_until:
            # cooldown bitti -> sifirla
            twitter_cooldown_until = None
            twitter_follow_count = 0
        return True, None


async def _twitter_after_success():
    """Basarili bir twitter follow sonrasi sayaci artir; 10'a ulasinca
    300s cooldown baslat."""
    global twitter_follow_count, twitter_cooldown_until
    s = load_settings()
    limit = int(s.get("twitter_follow_limit", 10))
    cooldown = int(s.get("twitter_cooldown_s", 300))
    async with _tw_lock:
        twitter_follow_count += 1
        if twitter_follow_count >= limit:
            twitter_cooldown_until = time.time() + cooldown


def twitter_status() -> dict:
    remain = 0
    if twitter_cooldown_until:
        remain = max(0, int(twitter_cooldown_until - time.time()))
    return {"follow_count": twitter_follow_count, "cooldown_remaining_s": remain}


# ─── FAST-RUN (cache'ten, metin okumadan, sub-1sn) ───────────────
async def _fast_run(category: str, target: dict, template: dict, profile: dict) -> dict:
    """templates.json'daki oranlarla dogrudan calis - UI XML okumadan.
    Deep-link ac, kisa yerlesme bekle, cached orana dokun."""
    if target.get("deep_link"):
        await adb.open_deep_link(target["deep_link"], package=target.get("package"))
    steps = template.get("steps", [])
    if not steps:
        raise RuntimeError("template bos (adim yok)")
    # UI'nin acilmasi icin tek bir hafif senkron nokta (sabit sleep yerine)
    await adb.wait_ui_settle(profile)
    ok_any = False
    for step in steps:
        rx, ry = step.get("x_ratio"), step.get("y_ratio")
        if rx is None or ry is None:
            continue
        ok_any = await adb.tap_ratio(rx, ry, profile=profile) or ok_any
    if not ok_any:
        raise RuntimeError("fast-run: cached orana dokunulamadi")
    await _bump_template_runs(category)
    return {"mode": "fast", "tapped": True}


# ─── FIRST-RUN (ogrenme) ─────────────────────────────────────────
async def _first_run(category: str, target: dict, profile: dict) -> dict:
    """
    Ilk kez gorulen kategori: deep-link ac, UI polling ile aksiyon
    butonunu (Follow/Like/...) bul, dokun, merkez oranini templates.json'a
    OGREN. Bulamazsa gorsel fallback'e duser.
    """
    spec = CATEGORY_SPEC.get(category, {})
    if target.get("deep_link"):
        await adb.open_deep_link(target["deep_link"], package=target.get("package"))

    # 1) UI polling ile butonu ara
    node = await adb.poll_for_element(spec.get("targets", []), profile=profile)
    screen = await adb.get_screen_size()

    if node:
        ratio = adb.node_center_ratio(node, screen)
        await adb.tap_node(node, profile=profile)
        if ratio:
            await _store_template(category, {
                "action": "tap",
                "x_ratio": ratio[0], "y_ratio": ratio[1],
                "matched_via": "uiautomator",
                "targets": spec.get("targets", []),
            })
        return {"mode": "first_run", "learned": True, "via": "xml"}

    # 2) XML basarisiz -> gorsel fallback (screenshot -> compress -> vision)
    png = await adb.screenshot_png()
    vis = await vision_locate(png, spec.get("action_label", "aksiyon butonu"))
    if vis.get("found"):
        await adb.tap_ratio(vis["x"], vis["y"], profile=profile)
        await _store_template(category, {
            "action": "tap",
            "x_ratio": round(vis["x"], 4), "y_ratio": round(vis["y"], 4),
            "matched_via": "vision",
            "targets": spec.get("targets", []),
        })
        return {"mode": "first_run", "learned": True, "via": "vision"}

    raise RuntimeError("first-run: buton ne XML ne gorsel ile bulunamadi")


# ─── TEK GOREV (retry + self-healing) ────────────────────────────
async def process_task(task: dict) -> dict:
    """
    task = {"id":..,"instruction":"...", ...}
    Doner: {"id":.., "category":.., "status":"done|skipped|failed", "detail":..}
    """
    instruction = task.get("instruction") or task.get("text") or ""
    category = classify_task(instruction)
    tid = task.get("id")
    if not category:
        return {"id": tid, "category": None, "status": "skipped", "detail": "kategori bulunamadi"}

    # Twitter ban korumasi kapisi
    allowed, reason = await _twitter_gate(category)
    if not allowed:
        return {"id": tid, "category": category, "status": "skipped", "detail": reason}

    target = extract_target(instruction, category)
    if not target.get("deep_link"):
        return {"id": tid, "category": category, "status": "skipped",
                "detail": "hedef URL/kullanici cikarilamadi"}

    profile = get_active_profile()
    templates = _load_templates()
    max_retries = int(profile.get("max_retries", 2))

    last_err = ""
    last_xml = ""
    for attempt in range(1, max_retries + 1):
        try:
            if category in templates and templates[category].get("steps"):
                result = await _fast_run(category, target, templates[category], profile)
            else:
                result = await _first_run(category, target, profile)
            # basari
            if category == "twitter_follow":
                await _twitter_after_success()
            return {"id": tid, "category": category, "status": "done", "detail": result}
        except Exception as e:
            last_err = f"{e}\n{traceback.format_exc()}"
            try:
                last_xml = await adb._dump_ui_xml(profile)
            except Exception:
                last_xml = ""
            print(f"[WF] {category} deneme {attempt}/{max_retries} basarisiz: {e}")
            # her denemede fast-run bir kez sonra XML'e dus - takilan cache'i
            # tekrar ogrensin diye templates'i bosalt
            if category in templates:
                templates = {k: v for k, v in templates.items() if k != category}

    # 3) 2 deneme bitti -> SELF-HEALING danisman
    advice = await ask_advisor_ai(last_err, last_xml, task_desc=instruction[:200])
    action = advice.get("action")
    if action == "override" and isinstance(advice.get("x"), (int, float)):
        try:
            await adb.tap_ratio(float(advice["x"]), float(advice["y"]), profile=profile)
            await _store_template(category, {
                "action": "tap",
                "x_ratio": round(float(advice["x"]), 4),
                "y_ratio": round(float(advice["y"]), 4),
                "matched_via": "advisor",
                "targets": CATEGORY_SPEC.get(category, {}).get("targets", []),
            })
            if category == "twitter_follow":
                await _twitter_after_success()
            return {"id": tid, "category": category, "status": "done",
                    "detail": {"mode": "self_healed", "via": "advisor_override"}}
        except Exception as e:
            return {"id": tid, "category": category, "status": "failed",
                    "detail": f"advisor override basarisiz: {e}"}
    # skip / retry(exhausted) -> temiz atla
    return {"id": tid, "category": category, "status": "skipped",
            "detail": advice.get("reason", "self-healing atladi")}


# ─── FEED (tum akis) ─────────────────────────────────────────────
async def run_feed(tasks: list, progress_cb=None, concurrency: int = 1) -> list:
    """
    Bir gorev listesini bastan sona isler. Instagram gorevleri + twitter
    like'lar tam hizda akar; twitter follow'lar ban korumasi kapisina
    tabidir. concurrency=1 (tek cihaz - seri) varsayilan; ADB tek cihazda
    paralel dokunma cakisir, o yuzden varsayilan seri.
    """
    results = []
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one(t):
        async with sem:
            res = await process_task(t)
            if progress_cb:
                try:
                    progress_cb(res)
                except Exception:
                    pass
            return res

    if concurrency <= 1:
        for t in tasks:
            results.append(await _one(t))
    else:
        results = await asyncio.gather(*[_one(t) for t in tasks])
    return results
