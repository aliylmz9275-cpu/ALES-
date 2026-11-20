"""
ALES Skills Engine
===================
Claude'a skill yukleme mantiginin ALES'e tasinmis hali.

backend/skills/ altindaki HER ALT KLASOR bir "skill"dir. Bir skill klasorunde:
  - SKILL.md   (zorunlu)  : YAML frontmatter + aciklama.
        ---
        id: youtube_oynatici
        name: YouTube Oynatici
        description: Video arar ve oynatir
        keywords: [youtube, video, izlet, oynat]
        enabled: true
        ---
        (buraya serbest metin - skill'in nasil kullanilacagina dair notlar)
  - skill.py   (opsiyonel) : gercek yetenegi kodlar.
        SKILL_TOOLS = [ {tool semasi}, ... ]   # main.py'deki TOOLS ile ayni format
        def run(tool_name, args, progress_cb=None): ...  # cagriyi yurut, string don

Yeni bir skill eklemek = yeni bir klasor + bu iki dosya. ALES onu otomatik
kesfeder (uygulama yeniden baslatildiginda ya da reload_skills() cagrisiyla,
orn. /skills/reload endpoint'i uzerinden - restart gerekmez).

SKILL.md'si olup skill.py'si olmayan klasorler de gecerlidir: bunlar "referans"
skill'dir (calistirilamaz ama read_skill_doc ile LLM'e okunabilir - orn. bir
siparis rehberi, bir stil kilavuzu).
"""
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

from config_manager import APPDATA


def _skills_dir() -> Path:
    """PyInstaller ile paketlenmis exe icinde de dogru skills/ klasorunu
    bulur - filesystem.py'deki _skills_dir() ile ayni mantik (build.bat
    skills/ klasorunu exe'nin yanina kopyalar, _MEIPASS'e degil)."""
    here = Path(__file__).resolve().parent
    candidates = [here / "skills", Path(os.getcwd()) / "skills"]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "skills")
    try:
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "skills")
    except Exception:
        pass
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


SKILLS_DIR = _skills_dir()
SKILLS_STATE_FILE = APPDATA / "skills_state.json"

_cache = {}  # skill_id -> dict


def _writable_skills_dir() -> Path:
    """Yeni skill yazarken (install_skill) _MEIPASS gibi gecici/read-only
    bir klasore degil, exe'nin yaninda kalici bir klasore yazmak icin."""
    if getattr(sys, "_MEIPASS", None):
        try:
            d = Path(sys.executable).resolve().parent / "skills"
            d.mkdir(parents=True, exist_ok=True)
            return d
        except Exception:
            pass
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    return SKILLS_DIR


def _parse_frontmatter(text: str):
    """Basit YAML-benzeri frontmatter parse (disaridan kutuphane gerektirmesin diye)."""
    m = re.match(r'^\s*---\s*\n(.*?)\n---\s*\n?(.*)$', text, re.DOTALL)
    if not m:
        return {}, text
    fm_text, body = m.group(1), m.group(2)
    meta = {}
    for line in fm_text.splitlines():
        if ":" not in line or line.strip().startswith("#"):
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if v.startswith("[") and v.endswith("]"):
            v = [x.strip().strip('"\'') for x in v[1:-1].split(",") if x.strip()]
        elif v.lower() in ("true", "false"):
            v = v.lower() == "true"
        meta[k] = v
    return meta, body


def _load_state() -> dict:
    if SKILLS_STATE_FILE.exists():
        try:
            return json.loads(SKILLS_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_state(state: dict):
    try:
        SKILLS_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def discover_skills(force: bool = False) -> dict:
    """skills/ klasorunu tarar, her skili yukler. force=True -> cache'i atla."""
    global _cache
    if _cache and not force:
        return _cache

    _cache = {}
    if not SKILLS_DIR.exists():
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        return _cache

    state = _load_state()
    for d in sorted(SKILLS_DIR.iterdir()):
        if not d.is_dir():
            continue
        md_path = d / "SKILL.md"
        if not md_path.exists():
            continue
        try:
            raw = md_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            continue
        meta, body = _parse_frontmatter(raw)
        skill_id = meta.get("id", d.name)
        enabled = state.get(skill_id, meta.get("enabled", True))

        module = None
        tools = []
        load_error = None
        py_path = d / "skill.py"
        if py_path.exists():
            try:
                mod_name = f"ales_skill_{skill_id}"
                spec = importlib.util.spec_from_file_location(mod_name, py_path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = module
                spec.loader.exec_module(module)
                tools = getattr(module, "SKILL_TOOLS", []) or []
            except Exception as e:
                load_error = str(e)

        _cache[skill_id] = {
            "id": skill_id,
            "name": meta.get("name", skill_id),
            "description": meta.get("description", ""),
            "keywords": meta.get("keywords", []) if isinstance(meta.get("keywords", []), list) else [],
            "enabled": bool(enabled),
            "executable": module is not None,
            "tools": tools,
            "module": module,
            "path": str(d),
            "doc": body.strip(),
            "load_error": load_error,
        }
    return _cache


def reload_skills() -> dict:
    return discover_skills(force=True)


def get_enabled_tools() -> list:
    """LLM'e gonderilecek tum aktif skill araclarinin tool-semasi listesi."""
    out = []
    for s in discover_skills().values():
        if s["enabled"]:
            out.extend(s["tools"])
    return out


def get_tool_categories() -> dict:
    """tool_router.py'nin TOOL_CATEGORIES formatinda, her skill kendi kategorisi olur.
    Boylece kullanicinin mesaji skill'in keywords'lerinden birine denk gelirse
    o skill'in araclari da modele sunulur (49 arac + N skill arasindan filtreleme)."""
    cats = {}
    for s in discover_skills().values():
        if s["enabled"] and s["tools"]:
            cats[f"skill:{s['id']}"] = {
                "keywords": s["keywords"],
                "tools": [t["function"]["name"] for t in s["tools"]],
            }
    return cats


def find_tool_owner(tool_name: str):
    for s in discover_skills().values():
        for t in s["tools"]:
            if t["function"]["name"] == tool_name:
                return s
    return None


def is_skill_tool(tool_name: str) -> bool:
    return find_tool_owner(tool_name) is not None


def execute_skill_tool(tool_name: str, args: dict, progress_cb=None):
    """tool_name bir skill aracina aitse calistirir ve sonucu (str) doner.
    Ait degilse None doner (cagiran yer baska bir yerde arasin diye)."""
    skill = find_tool_owner(tool_name)
    if not skill:
        return None
    if not skill["enabled"]:
        return f"[HATA] '{skill['id']}' skill'i su an pasif. Once aktif et."
    if not skill["module"]:
        return f"[HATA] '{skill['id']}' calistirilabilir degil (skill.py yok)."
    run_fn = getattr(skill["module"], "run", None)
    if not run_fn:
        return f"[HATA] Skill '{skill['id']}' bir run() fonksiyonu tanimlamiyor."
    try:
        try:
            return run_fn(tool_name, args, progress_cb)
        except TypeError:
            return run_fn(tool_name, args)
    except Exception as e:
        return f"[HATA] Skill '{skill['id']}' calisirken hata: {e}"


def list_skills_text() -> str:
    skills = discover_skills()
    if not skills:
        return "[BILGI] Yuklu skill yok. Skills panelinden yeni bir skill ekleyebilirsin."
    lines = ["[SKILLS]"]
    for s in skills.values():
        state = "aktif" if s["enabled"] else "pasif"
        kind = "calistirilabilir" if s["executable"] else "referans"
        err = f" ⚠️ yuklenemedi: {s['load_error']}" if s["load_error"] else ""
        lines.append(f"  * {s['id']} [{state}/{kind}] — {s['description']}{err}")
    return "\n".join(lines)


def get_skills_summary() -> list:
    """API/UI icin JSON-dostu liste (module hafizada tutulan Python objesi oldugu icin cikartilir)."""
    out = []
    for s in discover_skills().values():
        out.append({k: v for k, v in s.items() if k not in ("module", "tools")} | {
            "tool_names": [t["function"]["name"] for t in s["tools"]]
        })
    return out


def set_skill_enabled(skill_id: str, enabled: bool) -> str:
    skills = discover_skills()
    if skill_id not in skills:
        return f"[HATA] Skill bulunamadi: {skill_id}"
    state = _load_state()
    state[skill_id] = enabled
    _save_state(state)
    reload_skills()
    return f"[OK] '{skill_id}' skill'i {'aktif' if enabled else 'pasif'} edildi."


def install_skill(skill_id: str, skill_md: str, skill_py: str = "") -> str:
    """Yeni bir skill yukler - Claude'a bir skill klasoru yukleme mantiginin ayni.
    skill_id klasor adi olur; SKILL.md ve varsa skill.py diske yazilir."""
    safe_id = re.sub(r'[^a-zA-Z0-9_\-]', '_', (skill_id or "").strip())
    if not safe_id:
        return "[HATA] Gecersiz skill id."
    if not skill_md or not skill_md.strip():
        return "[HATA] SKILL.md icerigi bos olamaz."
    d = _writable_skills_dir() / safe_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(skill_md, encoding="utf-8")
    if skill_py and skill_py.strip():
        (d / "skill.py").write_text(skill_py, encoding="utf-8")
    reload_skills()
    err = discover_skills().get(safe_id, {}).get("load_error")
    if err:
        return f"[UYARI] Skill kaydedildi ama yuklenirken hata var: {err}"
    return f"[OK] Skill yuklendi: {safe_id}"


def delete_skill(skill_id: str) -> str:
    safe_id = re.sub(r'[^a-zA-Z0-9_\-]', '_', (skill_id or "").strip())
    d = SKILLS_DIR / safe_id
    if not d.exists() or not d.is_dir():
        return f"[HATA] Skill bulunamadi: {skill_id}"
    import shutil
    shutil.rmtree(d)
    reload_skills()
    return f"[OK] Skill silindi: {skill_id}"
