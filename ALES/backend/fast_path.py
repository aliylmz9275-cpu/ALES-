"""
fast_path.py — ALES Zero-LLM hizli yol (Faz 1, Task #4).

Rutin, tek-anlamli komutlari AI'ya HIC ugramadan dogrudan mevcut araclarla
calistirir (<50ms hedef). Eslesme YOKSA None doner -> istek normal AI
agent dongusune gider.

skills.json formati (backend/skills.json, liste):
  {
    "name": "screenshot",
    "platform": "windows",
    "enabled": true,
    "match": { "keywords": [["ekran","goruntu"], ["ekran","yakala"]],
               "regex": "^ekran(i)? (goruntusu|yakala).*$",
               "max_words": 6 },
    "steps": [ { "tool": "take_screenshot", "args": {"region": "auto"} } ],
    "capture": { "1": {"into_step": 0, "arg": "app_name"} },   # regex grubu -> arg
    "error_handling": "route_to_ai"   # hata olursa AI'ya duş (varsayilan)
  }

GUVENLIK: Fast Path yalnizca skills.json'da TANIMLI adimlari calistirir ve
her adimi mevcut execute_tool uzerinden gecirir - yani yikici araclar (dosya
sil vb.) icin var olan onay kapisi/guvenlik AYNEN gecerlidir. Tohum ornekler
salt-okunur/guvenli araclardir. Eslesme MUHAFAZAKARdir: kisa, emir-kipi
mesajlar; supheliyse None (AI'ya birak).
"""
import json
import re
from pathlib import Path

# "Bu bir soru/kod istegi" sinyalleri — bunlar varsa Fast Path DEVREYE GIRMEZ
# (orn. "hava durumu API'si nasil yazilir" -> get_weather'i tetiklememeli).
_META_WORDS = {
    "nasil", "nasıl", "neden", "niye", "how", "why", "what", "nedir",
    "yaz", "kod", "code", "ornek", "örnek", "aciklai", "acikla", "açıkla",
    "explain", "write", "script", "fonksiyon", "function", "api", "hakkinda",
    "hakkında", "farki", "farkı", "karsilastir", "karşılaştır",
}
_TR = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "İ": "i", "ö": "o",
                     "ş": "s", "ü": "u", "Ç": "c", "Ğ": "g", "Ö": "o",
                     "Ş": "s", "Ü": "u", "I": "i"})

try:
    from config_manager import get_appdata_dir
    _APPDATA_SKILLS = get_appdata_dir() / "skills.json"
except Exception:
    _APPDATA_SKILLS = Path("skills.json")
_LOCAL_SKILLS = Path(__file__).parent / "skills.json"

_cache = None


def _norm(text: str) -> str:
    t = (text or "").translate(_TR).casefold().strip()
    return re.sub(r"\s+", " ", t)


def load_skills(force: bool = False) -> list:
    """skills.json yukle: once AppData (kullanici duzenlemesi), sonra backend/."""
    global _cache
    if _cache is not None and not force:
        return _cache
    for f in [_APPDATA_SKILLS, _LOCAL_SKILLS]:
        if f.exists():
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                _cache = data if isinstance(data, list) else data.get("skills", [])
                return _cache
            except Exception:
                continue
    _cache = []
    return _cache


def reload_skills() -> list:
    return load_skills(force=True)


# ─── ESLESME (muhafazakar) ───────────────────────────────────────
def _matches(skill: dict, msg_norm: str, msg_raw: str) -> re.Match:
    """Bir skill bu mesaja uyuyor mu? Uyuyorsa regex match objesi (grup
    yakalamak icin) ya da True doner; uymuyorsa None."""
    if not skill.get("enabled", True):
        return None
    match = skill.get("match", {})
    words = msg_norm.split()
    max_words = int(match.get("max_words", 8))
    if len(words) > max_words:
        return None  # uzun mesaj = muhtemelen sohbet/soru, AI'ya birak

    # regex onceligi (grup yakalayabilir -> arg'a enjekte)
    rx = match.get("regex")
    if rx:
        m = re.match(rx, msg_norm)
        if m:
            return m
        return None

    # anahtar kelime kumeleri: herhangi bir kume TAMAMEN eslesirse yeter
    #   keywords: [["ekran","goruntu"], ["screenshot"]]  (VE-icinde / VEYA-arasi)
    groups = match.get("keywords", [])
    tokset = set(words)
    for grp in groups:
        if isinstance(grp, str):
            grp = [grp]
        if all(_norm(k) in tokset for k in grp):
            return re.match(r"(?s).*", msg_norm)  # eslesme var, grup yok
    return None


def find_match(user_message: str) -> dict:
    """Mesaja uyan ilk skill'i dondur (calistirilabilir plan halinde) ya da
    None. Meta-soru sinyali varsa (nasil/neden/kod/... ) her zaman None."""
    msg_norm = _norm(user_message)
    if not msg_norm:
        return None
    if set(msg_norm.split()) & _META_WORDS:
        return None  # "... nasil yazilir" gibi -> AI'ya birak
    for skill in load_skills():
        m = _matches(skill, msg_norm, user_message)
        if not m:
            continue
        steps = [dict(s) for s in skill.get("steps", [])]
        # regex gruplarini adimlara enjekte et (capture haritasi)
        cap = skill.get("capture", {})
        if cap and m and m.groups():
            for grp_key, spec in cap.items():
                try:
                    val = m.group(int(grp_key))
                except Exception:
                    val = None
                if val is None:
                    continue
                si = int(spec.get("into_step", 0))
                if 0 <= si < len(steps):
                    steps[si].setdefault("args", {})[spec["arg"]] = val.strip()
        return {"name": skill.get("name", "fast"), "steps": steps,
                "error_handling": skill.get("error_handling", "route_to_ai"),
                "platform": skill.get("platform", "any")}
    return None


# ─── CALISTIRMA (mevcut execute_tool uzerinden) ──────────────────
async def run_fast_path(user_message: str, execute_async, progress_cb=None) -> dict:
    """Eslesme varsa adimlari mevcut arac yolundan calistirir.
    execute_async: async (tool_name, args) -> str  (main.execute_tool_async).
    Doner: {"handled":True,"name":..,"outputs":[...]} veya {"handled":False}.
    Hata + error_handling=route_to_ai -> {"handled":False,"error":..} (AI'ya duş).

    NOT: yikici araclar icin bile mevcut execute_tool guvenlik/onay kapisi
    devrede kalir; Fast Path o kapiyi ATLAMAZ, sadece arac cagrisini kurar."""
    plan = find_match(user_message)
    if not plan:
        return {"handled": False}
    outputs = []
    for step in plan["steps"]:
        tool = step.get("tool")
        args = step.get("args", {}) or {}
        if not tool:
            continue
        try:
            res = await execute_async(tool, args)
        except Exception as e:
            res = f"[FASTPATH-HATA] {tool}: {e}"
        outputs.append({"tool": tool, "result": res})
        if isinstance(res, str) and res.startswith(("Hata:", "[HATA]", "[FASTPATH-HATA]")):
            if plan.get("error_handling", "route_to_ai") == "route_to_ai":
                return {"handled": False, "error": res, "name": plan["name"]}
    return {"handled": True, "name": plan["name"], "outputs": outputs}
