"""
plugin_loader.py — Hafif, surec-ici eklenti yukleyici (OpenFlux ikamesi).

Ali'nin onayladigi ikame: "OpenFlux -> JSON tabanli hafif plugin loader".
OpenFlux ayri bir servis/kuyruk ister; ALES tek surecte calisir. Bu modul
ayni yetenegi (yeniden BASLATMADAN eklenti ekle/cikar) sifir zorunlu
bagimlilikla saglar.

BIR EKLENTI NEDIR:
  backend/plugins/<ad>.py  ->  icinde register() fonksiyonu olan bir dosya.

    PLUGIN_API = 1                       # opsiyonel ama onerilir

    def register():
        return {
            "id": "hesap_makinesi",
            "name": "Hesap Makinesi",
            "description": "Dort islem yapar",
            "version": "1.0.0",
            "tools": [ { ...main.py TOOLS ile AYNI OpenAI tool semasi... } ],
            "handlers": {"plugin_hesapla": lambda args, progress_cb=None: "42"},
            "on_load":   lambda: None,   # opsiyonel
            "on_unload": lambda: None,   # opsiyonel
        }

DURUM DOSYASI: AppData/plugins.json -> {"enabled": {"<id>": true/false}}
Kullanici bir eklentiyi UI'dan kapatirsa dosyaya yazilir; ALES yeniden
baslatildiginda kapali kalir.

skills_engine.py'den FARKI (ikisi de var, ikisi de gerekli):
  skills_engine  = klasor + SKILL.md + frontmatter; dokumantasyon tasir,
                   LLM'e "bu isi nasil yaparsin" anlatir, referans skill
                   olabilir.
  plugin_loader  = TEK dosya + register(); sadece kod/arac ekler, dokuman
                   tasimaz, calisirken tak-cikar edilir.
Ikisinin araclari main.py get_all_tools() icinde birlesir.

GUVENLIK — ISIM GASPI (name squatting):
Bir eklenti "delete_path", "write_file" veya "run_python_code" adinda arac
tanimlayabilse, ALES'in cekirdek araclarini SESSIZCE ele gecirirdi: model
"dosyayi sil" der, cagri eklentiye gider. Bu yuzden cekirdek arac adlari
REZERVEDIR ve cakisan arac YUKLENMEZ (eklentinin geri kalani yuklenir,
cakisan arac atlanir ve load_error'a yazilir). main.py baslangicta
set_reserved_names() ile gercek listeyi bildirir; bildirmezse asagidaki
_HARD_RESERVED yine de yikici araclari korur (fail-safe varsayilan).

Ayrica: eklenti kodu ALES surecinde, TAM yetkiyle calisir. Bu bir kum
havuzu DEGILDIR ve oyle sunulmuyor — plugins/ klasorune dosya koymak
"ALES'e kod eklemek"tir. Guvenilmeyen kod icin code_act_executor'un ayri
process + statik kapi yolu kullanilmali.
"""
import importlib.util
import json
import os
import sys
import threading
import time
from pathlib import Path

PLUGIN_API_VERSION = 1

try:
    from config_manager import APPDATA
    STATE_FILE = APPDATA / "plugins.json"
except Exception:
    STATE_FILE = Path("plugins.json")


def _plugins_dir() -> Path:
    """skills_engine._skills_dir() ile AYNI mantik: PyInstaller ile paketlenmis
    exe icinde de dogru klasoru bulur (build exe'nin yanina kopyalar)."""
    here = Path(__file__).resolve().parent
    candidates = [here / "plugins", Path(os.getcwd()) / "plugins"]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "plugins")
    try:
        candidates.append(Path(sys.executable).resolve().parent / "plugins")
    except Exception:
        pass
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


PLUGINS_DIR = _plugins_dir()

# Bu adlar HER ZAMAN korunur; main.py listeyi bildirmese bile.
_HARD_RESERVED = {
    "run_python_code", "delete_path", "write_file", "edit_file",
    "create_directory", "move_path", "copy_path", "read_file",
    "click_at", "type_text", "press_key", "open_app", "close_app",
    "take_screenshot", "analyze_screen", "find_on_screen",
    "add_pending_approval", "send_notification", "call_connector",
    "set_mode", "save_fact", "run_shell", "run_command",
}

_lock = threading.RLock()
_plugins = {}            # pid -> kayit
_reserved = set()        # main.py'nin bildirdigi cekirdek arac adlari
_stats = {"loaded": 0, "failed": 0, "calls": 0, "call_errors": 0,
          "reloads": 0, "rejected_tools": 0, "last_error": None}
_events = []             # son olaylar (UI/WS icin)
MAX_EVENTS = 50


# ─── DURUM ─────────────────────────────────────────────────────────────
def _load_state() -> dict:
    try:
        if STATE_FILE.exists():
            d = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return d
    except Exception:
        pass
    return {"enabled": {}}


def _save_state(state: dict):
    """Atomik yazim (.tmp -> os.replace): yazim ortasinda cokme, her acilista
    sifirlanan bir durum dosyasi biraksin istemiyoruz."""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(str(tmp), str(STATE_FILE))
    except Exception:
        pass


def _event(kind: str, pid: str, detail: str = ""):
    with _lock:
        _events.append({"event": kind, "plugin": pid, "detail": detail[:300],
                        "ts": time.time()})
        if len(_events) > MAX_EVENTS:
            del _events[:len(_events) - MAX_EVENTS]


def events(limit: int = 20) -> list:
    with _lock:
        return list(_events[-max(1, int(limit)):])


def set_reserved_names(names) -> int:
    """main.py baslangicta cekirdek arac adlarini bildirir. Bundan sonra
    yuklenecek eklentiler bu adlari kullanamaz."""
    global _reserved
    with _lock:
        _reserved = {str(n) for n in (names or []) if n}
    return len(_reserved)


def reserved_names() -> set:
    with _lock:
        return set(_reserved) | _HARD_RESERVED


# ─── DOGRULAMA ─────────────────────────────────────────────────────────
def _tool_name(t) -> str:
    try:
        return t["function"]["name"]
    except Exception:
        return ""


def _validate_spec(spec: dict, fname: str) -> dict:
    """register() ciktisini dogrula ve TEMIZLE. Sonuc: {"ok","spec","errors"}.

    Kotu semali TEK bir arac butun eklentiyi dusurmez; o arac atilir ve
    hata listeye yazilir. Sebep: bir eklentide 5 arac varsa 4'unu
    kaybetmenin anlami yok.
    """
    errors = []
    if not isinstance(spec, dict):
        return {"ok": False, "spec": None,
                "errors": ["register() bir dict dondurmedi"]}

    pid = str(spec.get("id") or Path(fname).stem).strip()
    if not pid:
        return {"ok": False, "spec": None, "errors": ["id bos"]}

    api = spec.get("api") or spec.get("PLUGIN_API") or PLUGIN_API_VERSION
    try:
        api = int(api)
    except Exception:
        api = PLUGIN_API_VERSION
    if api > PLUGIN_API_VERSION:
        errors.append(f"eklenti API v{api} istiyor, ALES v{PLUGIN_API_VERSION} "
                      "sunuyor — yine de yuklendi, uyumsuzluk olabilir")

    handlers = spec.get("handlers") or {}
    if not isinstance(handlers, dict):
        handlers = {}
        errors.append("handlers bir dict degil, yok sayildi")

    reserved = reserved_names()
    clean_tools, clean_handlers = [], {}
    for t in (spec.get("tools") or []):
        name = _tool_name(t)
        if not name:
            errors.append("adi olmayan arac semasi atlandi")
            continue
        if name in reserved:
            # ISIM GASPI KAPISI (bkz. modul basligi).
            errors.append(f"'{name}' cekirdek arac adi — REDDEDILDI")
            with _lock:
                _stats["rejected_tools"] += 1
            continue
        owner = _owner_of_tool(name, skip_pid=pid)
        if owner:
            errors.append(f"'{name}' zaten '{owner}' eklentisinde var — atlandi")
            continue
        h = handlers.get(name)
        if not callable(h):
            errors.append(f"'{name}' icin handler yok/cagirilabilir degil — atlandi")
            continue
        clean_tools.append(t)
        clean_handlers[name] = h

    return {"ok": True, "errors": errors, "spec": {
        "id": pid,
        "name": str(spec.get("name") or pid),
        "description": str(spec.get("description") or ""),
        "version": str(spec.get("version") or "0.0.0"),
        "api": api,
        "tools": clean_tools,
        "handlers": clean_handlers,
        "on_load": spec.get("on_load"),
        "on_unload": spec.get("on_unload"),
        "keywords": list(spec.get("keywords") or []),
    }}


def _owner_of_tool(name: str, skip_pid: str = "") -> str:
    with _lock:
        for pid, p in _plugins.items():
            if pid == skip_pid:
                continue
            if name in (p.get("handlers") or {}):
                return pid
    return ""


# ─── YUKLEME ───────────────────────────────────────────────────────────
def _load_file(path: Path, enabled_map: dict) -> dict:
    """Tek bir .py dosyasini yukle. ASLA raise etmez; hata kayda gecer."""
    pid_guess = path.stem
    rec = {"id": pid_guess, "name": pid_guess, "description": "",
           "version": "0.0.0", "api": PLUGIN_API_VERSION, "tools": [],
           "handlers": {}, "enabled": bool(enabled_map.get(pid_guess, True)),
           "path": str(path), "load_error": None, "warnings": [],
           "mtime": 0.0, "loaded_at": time.time(), "on_unload": None}
    try:
        rec["mtime"] = path.stat().st_mtime
    except Exception:
        pass

    try:
        mod_name = f"ales_plugin_{pid_guess}"
        spec_o = importlib.util.spec_from_file_location(mod_name, path)
        module = importlib.util.module_from_spec(spec_o)
        sys.modules[mod_name] = module
        spec_o.loader.exec_module(module)
    except Exception as e:
        rec["load_error"] = f"import hatasi: {type(e).__name__}: {e}"
        with _lock:
            _stats["failed"] += 1
            _stats["last_error"] = rec["load_error"]
        _event("error", pid_guess, rec["load_error"])
        return rec

    reg = getattr(module, "register", None)
    if not callable(reg):
        rec["load_error"] = "register() fonksiyonu yok"
        with _lock:
            _stats["failed"] += 1
        _event("error", pid_guess, rec["load_error"])
        return rec

    try:
        raw = reg()
    except Exception as e:
        rec["load_error"] = f"register() hatasi: {type(e).__name__}: {e}"
        with _lock:
            _stats["failed"] += 1
            _stats["last_error"] = rec["load_error"]
        _event("error", pid_guess, rec["load_error"])
        return rec

    v = _validate_spec(raw, path.name)
    if not v["ok"]:
        rec["load_error"] = "; ".join(v["errors"])
        with _lock:
            _stats["failed"] += 1
        _event("error", pid_guess, rec["load_error"])
        return rec

    s = v["spec"]
    rec.update({"id": s["id"], "name": s["name"],
                "description": s["description"], "version": s["version"],
                "api": s["api"], "tools": s["tools"],
                "handlers": s["handlers"], "keywords": s["keywords"],
                "on_unload": s["on_unload"], "warnings": v["errors"]})
    rec["enabled"] = bool(enabled_map.get(s["id"], True))

    if callable(s.get("on_load")):
        try:
            s["on_load"]()
        except Exception as e:
            rec["warnings"].append(f"on_load hatasi: {type(e).__name__}: {e}")

    with _lock:
        _stats["loaded"] += 1
    _event("loaded", rec["id"],
           f"{len(rec['tools'])} arac" + (f", {len(rec['warnings'])} uyari"
                                          if rec["warnings"] else ""))
    return rec


def _call_unload(rec: dict):
    fn = rec.get("on_unload")
    if callable(fn):
        try:
            fn()
        except Exception:
            pass


def discover(force: bool = False) -> dict:
    """plugins/ klasorunu tara. force=False ve zaten yuklenmisse dokunmaz.

    YENIDEN BASLATMA GEREKTIRMEZ: dosya eklendiyse yuklenir, silindiyse
    kaldirilir (on_unload cagirilir), degistiyse (mtime) yeniden yuklenir.
    """
    global _plugins
    with _lock:
        already = bool(_plugins)
    if already and not force:
        with _lock:
            return dict(_plugins)

    if not PLUGINS_DIR.exists():
        try:
            PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    state = _load_state()
    enabled_map = state.get("enabled") or {}

    found = {}
    try:
        files = sorted(p for p in PLUGINS_DIR.glob("*.py")
                       if not p.name.startswith("_"))
    except Exception:
        files = []

    for path in files:
        with _lock:
            prev = next((p for p in _plugins.values()
                         if p.get("path") == str(path)), None)
        try:
            mt = path.stat().st_mtime
        except Exception:
            mt = 0.0
        if prev and not force and abs(prev.get("mtime", 0.0) - mt) < 1e-6:
            found[prev["id"]] = prev              # degismemis, aynen kullan
            continue
        if prev:
            # Degismis -> once bosalt. Eski kaydi _plugins'ten de DUSURUYORUZ:
            # aksi halde _validate_spec, ayni dosyanin eski surumunu "baska
            # eklenti bu araci zaten tanimlamis" sanip yeni araclari reddeder.
            _call_unload(prev)
            with _lock:
                _plugins.pop(prev["id"], None)
            sys.modules.pop(f"ales_plugin_{path.stem}", None)
        rec = _load_file(path, enabled_map)
        found[rec["id"]] = rec

    with _lock:
        # Diskten SILINEN eklentiler: on_unload cagir ve dus.
        for pid, p in list(_plugins.items()):
            if pid not in found:
                _call_unload(p)
                _event("unloaded", pid, "dosya bulunamadi")
        _plugins = found
        return dict(_plugins)


def reload_all() -> dict:
    with _lock:
        _stats["reloads"] += 1
    return discover(force=True)


def reload_plugin(pid: str) -> dict:
    """Tek eklentiyi yeniden yukle (digerlerine dokunmadan)."""
    with _lock:
        p = _plugins.get(pid)
    if not p:
        return {"ok": False, "error": f"eklenti yok: {pid}"}
    path = Path(p["path"])
    if not path.exists():
        with _lock:
            _call_unload(p)
            _plugins.pop(pid, None)
        _event("unloaded", pid, "dosya silinmis")
        return {"ok": True, "unloaded": True, "id": pid}
    _call_unload(p)
    # sys.modules'ten dusur ki dosya gercekten yeniden okunsun.
    sys.modules.pop(f"ales_plugin_{path.stem}", None)
    rec = _load_file(path, (_load_state().get("enabled") or {}))
    with _lock:
        _plugins.pop(pid, None)
        _plugins[rec["id"]] = rec
        _stats["reloads"] += 1
    return {"ok": rec["load_error"] is None, "id": rec["id"],
            "load_error": rec["load_error"], "warnings": rec["warnings"],
            "tools": [_tool_name(t) for t in rec["tools"]]}


def unload(pid: str) -> dict:
    """Eklentiyi bellekten cikar (dosyayi SILMEZ)."""
    with _lock:
        p = _plugins.pop(pid, None)
    if not p:
        return {"ok": False, "error": f"eklenti yok: {pid}"}
    _call_unload(p)
    sys.modules.pop(f"ales_plugin_{Path(p['path']).stem}", None)
    _event("unloaded", pid, "elle cikarildi")
    return {"ok": True, "id": pid}


def set_enabled(pid: str, enabled: bool) -> dict:
    with _lock:
        p = _plugins.get(pid)
    if not p:
        return {"ok": False, "error": f"eklenti yok: {pid}"}
    state = _load_state()
    state.setdefault("enabled", {})[pid] = bool(enabled)
    _save_state(state)
    with _lock:
        p["enabled"] = bool(enabled)
    _event("enabled" if enabled else "disabled", pid, "")
    return {"ok": True, "id": pid, "enabled": bool(enabled)}


# ─── ARAC ARAYUZU (main.py bunlari kullanir) ───────────────────────────
def get_enabled_tools() -> list:
    """Aktif eklentilerin tool semalari — get_all_tools() bunu ekler."""
    out = []
    for p in discover().values():
        if p.get("enabled") and not p.get("load_error"):
            out.extend(p.get("tools") or [])
    return out


def get_tool_categories() -> dict:
    """tool_router.py TOOL_CATEGORIES formati (skills_engine ile ayni sekil)."""
    cats = {}
    for p in discover().values():
        if p.get("enabled") and p.get("tools") and not p.get("load_error"):
            cats[f"plugin:{p['id']}"] = {
                "keywords": p.get("keywords") or [],
                "tools": [_tool_name(t) for t in p["tools"]],
            }
    return cats


def find_tool_owner(tool_name: str):
    for p in discover().values():
        if tool_name in (p.get("handlers") or {}):
            return p
    return None


def is_plugin_tool(tool_name: str) -> bool:
    return find_tool_owner(tool_name) is not None


def _takes_progress(fn) -> bool:
    """Handler IKINCI BIR KONUMSAL parametre (progress_cb) kabul ediyor mu?
    Imza okunamazsa GUVENLI tarafa duseriz: tek argumanla cagirilir.
    Sadece konumsal bakiyoruz cunku cagri fn(args, progress_cb) seklinde."""
    try:
        import inspect
        sig = inspect.signature(fn)
        pos = 0
        for p in sig.parameters.values():
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
                pos += 1
            elif p.kind == p.VAR_POSITIONAL:
                return True
        return pos >= 2
    except Exception:
        return False


def execute_plugin_tool(tool_name: str, args: dict, progress_cb=None):
    """Eklenti aracini calistir. Bu eklentiye ait DEGILSE None doner
    (cagiran yer baska yerde arasin) — skills_engine ile ayni sozlesme."""
    p = find_tool_owner(tool_name)
    if not p:
        return None
    if not p.get("enabled"):
        return f"[HATA] '{p['id']}' eklentisi su an pasif. Once aktif et."
    if p.get("load_error"):
        return f"[HATA] '{p['id']}' yuklenemedi: {p['load_error']}"
    fn = (p.get("handlers") or {}).get(tool_name)
    if not callable(fn):
        return f"[HATA] '{tool_name}' icin handler yok."
    with _lock:
        _stats["calls"] += 1
    try:
        # progress_cb'yi SADECE handler kabul ediyorsa geciriyoruz. skills_engine
        # bunu "once iki argumanla dene, TypeError alirsan tek argumanla dene"
        # seklinde yapiyor; burada yapmiyoruz cunku handler KENDI icinde
        # TypeError atarsa o desen onu IKINCI KEZ calistirir — yan etkili bir
        # arac icin bu iki kez silme/iki kez gonderme demektir.
        if _takes_progress(fn):
            res = fn(args or {}, progress_cb)
        else:
            res = fn(args or {})
        return res if isinstance(res, str) else json.dumps(
            res, ensure_ascii=False, default=str)
    except Exception as e:
        with _lock:
            _stats["call_errors"] += 1
            _stats["last_error"] = f"{tool_name}: {type(e).__name__}: {e}"
        return f"[HATA] Eklenti '{p['id']}' calisirken hata: {e}"


# ─── LISTELEME / ISTATISTIK ────────────────────────────────────────────
def list_plugins() -> list:
    """UI listesi. 'handlers'/'on_unload' JSON'a cevrilemeyecegi icin cikarilir."""
    out = []
    for p in discover().values():
        out.append({
            "id": p["id"], "name": p["name"],
            "description": p["description"], "version": p["version"],
            "api": p.get("api"), "enabled": bool(p.get("enabled")),
            "tool_names": [_tool_name(t) for t in (p.get("tools") or [])],
            "tool_count": len(p.get("tools") or []),
            "load_error": p.get("load_error"),
            "warnings": p.get("warnings") or [],
            "path": p.get("path"), "loaded_at": p.get("loaded_at"),
        })
    return sorted(out, key=lambda x: x["id"])


def list_plugins_text() -> str:
    ps = list_plugins()
    if not ps:
        return ("[BILGI] Yuklu eklenti yok. backend/plugins/ altina register() "
                "fonksiyonu olan bir .py dosyasi koy ve /plugins/reload cagir.")
    lines = ["[EKLENTILER]"]
    for p in ps:
        st = "aktif" if p["enabled"] else "pasif"
        err = f"  !! yuklenemedi: {p['load_error']}" if p["load_error"] else ""
        lines.append(f"  * {p['id']} v{p['version']} [{st}] "
                     f"{p['tool_count']} arac — {p['description']}{err}")
    return "\n".join(lines)


def stats() -> dict:
    ps = discover()
    with _lock:
        s = dict(_stats)
    s["plugins"] = len(ps)
    s["enabled_now"] = sum(1 for p in ps.values() if p.get("enabled"))
    s["failed_now"] = sum(1 for p in ps.values() if p.get("load_error"))
    s["tools"] = sum(len(p.get("tools") or []) for p in ps.values()
                     if p.get("enabled") and not p.get("load_error"))
    s["dir"] = str(PLUGINS_DIR)
    s["api_version"] = PLUGIN_API_VERSION
    s["reserved_count"] = len(reserved_names())
    return s


def reset_stats() -> dict:
    with _lock:
        _stats.update({"loaded": 0, "failed": 0, "calls": 0, "call_errors": 0,
                       "reloads": 0, "rejected_tools": 0, "last_error": None})
    return stats()


def info() -> dict:
    """runtime_state / UI icin kisa durum.

    `available` = yukleyici CALISIR durumda mi (klasor okunabiliyor mu),
    eklenti SAYISI degil. Sifir eklenti tamamen normaldir; yukleyicinin
    hazir olmasi eklenti bulunmasindan bagimsizdir — aksi halde bos
    plugins/ klasoru "modul bozuk" gibi gorunurdu.
    """
    try:
        ps = discover()
        ok = True
        err = ""
    except Exception as e:
        ps, ok, err = {}, False, str(e)
    enabled = sum(1 for p in ps.values() if p.get("enabled") and not p.get("load_error"))
    failed = sum(1 for p in ps.values() if p.get("load_error"))
    return {
        "available": ok,
        "note": (f"{len(ps)} eklenti bulundu, {enabled} aktif"
                 + (f", {failed} hatali" if failed else "")
                 + ". Yeniden baslatma gerekmez."
                 if ok else f"plugins/ okunamadi: {err}"),
        "dir": str(PLUGINS_DIR),
        "api_version": PLUGIN_API_VERSION,
        "plugins": len(ps),
        "enabled": enabled,
        "failed": failed,
        "tools": sum(len(p.get("tools") or []) for p in ps.values()
                     if p.get("enabled") and not p.get("load_error")),
        "sandboxed": False,
        "warning": ("Eklentiler ALES surecinde TAM yetkiyle calisir; "
                    "kaynagina guvenmedigin dosyayi plugins/ icine koyma."),
    }

