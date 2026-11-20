"""
CodeAct — model plani TEK kod blogu olarak yazar, biz onu izole calistiririz.

NEDEN: Klasik arac dongusunde her adim ayri bir LLM gidis-donusudur
(dusun -> arac cagir -> sonucu oku -> tekrar dusun). 6 adimlik bir plan
6 tur eder. CodeAct'ta model plani tek Python blogu olarak yazar, blok
bir kez calisir, tek sonuc doner. Tur sayisi duser, gecikme de duser.

NOT: Kazanci yuzde olarak YAZMIYORUZ. Bu tree'de hicbir sey olculmedi;
mekanizma "tur sayisini azaltmak", rakam iddiasi degil. Gercek sayilar
stats() icinde, calistikca birikir.

GUVENLIK — projenin kendi kurali (config_manager.py:122):
  "CodeAct onay kapisi ve timeout'lar AYNEN korunur — AI kodu otomatik
   calistirilmaz, kapilar kaldirilmaz."
Bu modul o kurala uyar:
  1. Kod ONCE statik taranir (ast). Allowlist disi import veya tehlikeli
     cagri varsa HIC process baslatilmaz.
  2. needs_approval() supheye dusen her durumda True doner (fail-closed).
  3. plan_and_run() approve_cb almadan onay gerektiren kodu CALISTIRMAZ;
     kodu ve statik raporu dondurup karari cagirana birakir.
  4. Calistirma daima ayri process + timeout + kirpilmis cikti + temiz
     calisma dizini + gizli-anahtarlardan arindirilmis ortam.
exec() / eval() bu modulde HIC kullanilmaz.

code_runner.py (18 satirlik naif kosucu) DURUYOR — main.py'deki
run_python_code araci hala onu kullanir. Bu modul onun yerine gecmez,
uzerine gelir.
"""
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

# ─── AYARLAR ───────────────────────────────────────────────────────────
SANDBOX_TIMEOUT_S = 30.0      # varsayilan; cagiran override edebilir
MAX_OUTPUT_CHARS = 20_000     # stdout/stderr basina kirpma siniri
MAX_CODE_CHARS = 60_000       # bundan uzun kod zaten plan degil, kaza
TRIVIAL_MAX_LINES = 40        # needs_approval icin "kucuk" esigi

# Sadece bunlar import edilebilir. Neden allowlist: blocklist, birileri
# yeni bir tehlikeli modul ekledigi anda SESSIZCE acik kalir. Allowlist
# ise bilinmeyen her seye kapali dogar.
ALLOWED_IMPORTS = frozenset({
    "math", "json", "re", "datetime", "time", "random", "itertools",
    "functools", "collections", "statistics", "string", "textwrap",
    "decimal", "fractions", "hashlib", "base64", "uuid", "pathlib",
    "csv", "io", "typing", "dataclasses", "enum", "unicodedata",
    "operator", "bisect", "heapq", "copy", "difflib", "calendar",
    "zoneinfo", "abc", "numbers", "types", "reprlib", "pprint",
})

# allow_net=True verilmedikce yasak olan ag modulleri.
NET_IMPORTS = frozenset({
    "socket", "http", "urllib", "requests", "httpx", "ftplib", "smtplib",
    "telnetlib", "asyncio", "ssl", "xmlrpc", "webbrowser", "aiohttp",
    "websockets", "poplib", "imaplib", "urllib3",
})

# Import edilmesi hicbir kosulda kabul edilmeyen moduller. Bunlar
# allowlist'te olmadigi icin zaten yakalanir; burada AYRICA listeleniyor
# ki hata mesaji "bilinmeyen modul" degil "yasakli modul" desin.
HARD_DENY_IMPORTS = frozenset({
    "os", "sys", "subprocess", "shutil", "ctypes", "multiprocessing",
    "threading", "importlib", "builtins", "__builtin__", "pickle",
    "marshal", "shelve", "dbm", "sqlite3", "code", "codeop", "pty",
    "signal", "resource", "pwd", "grp", "winreg", "msvcrt", "gc",
    "inspect", "traceback", "atexit", "site", "sysconfig", "venv",
    "distutils", "setuptools", "pip", "ensurepip", "runpy", "tempfile",
    "glob", "fileinput", "zipfile", "tarfile", "gzip", "bz2", "lzma",
})

# Cagrilmasi yasak isimler (dogrudan Name olarak).
DENIED_NAMES = frozenset({
    "eval", "exec", "compile", "__import__", "globals", "locals",
    "vars", "memoryview", "breakpoint", "input",
})

# Yasak nokta-yolu onekleri: "os.system", "shutil.rmtree" gibi.
DENIED_PATH_PREFIXES = (
    "os.", "sys.", "subprocess.", "shutil.", "ctypes.", "socket.",
    "importlib.", "pickle.", "marshal.", "multiprocessing.", "threading.",
    "signal.", "winreg.", "builtins.", "inspect.",
)

# Nesne uzerinden cagrilinca yikici olan metod isimleri. pathlib.Path
# allowlist'te oldugu icin Path("x").unlink() teorik olarak mumkun —
# bu liste onu keser.
DENIED_ATTR_LEAVES = frozenset({
    "system", "popen", "spawn", "spawnl", "spawnv", "spawnve",
    "unlink", "rmdir", "rmtree", "chmod", "chown", "remove", "removedirs",
    "kill", "terminate", "killpg", "fork", "forkpty", "execv", "execve",
    "execl", "setuid", "setgid", "putenv", "unsetenv", "startfile",
    "check_output", "check_call", "call", "run_shell", "dup2",
})

# JS icin AST yok — regex ile tarariz. Bu Python kapisindan ZAYIF bir
# kapi; asagida ayrica belirtiliyor ve cagirana da bildiriliyor.
JS_DENY_PATTERNS = (
    (r"require\s*\(\s*['\"](child_process|fs|net|http|https|dgram|cluster|vm|worker_threads|os|dns|tls|repl)['\"]", "yasakli require"),
    (r"\bprocess\s*\.\s*env\b", "process.env erisimi"),
    (r"\bprocess\s*\.\s*(exit|kill|binding|dlopen)\b", "process kontrolu"),
    (r"\beval\s*\(", "eval"),
    (r"new\s+Function\s*\(", "new Function"),
    (r"\bimport\s*\(", "dinamik import"),
    (r"\bglobalThis\b", "globalThis"),
    (r"\b__proto__\b", "__proto__"),
)

# Ortama gecmesine izin verilen degisken adlari. Geri kalan HER SEY
# dusurulur — ozellikle API anahtarlari. Uretilen bir betik
# os.environ'a bakamaz (os import'u yasak) ama savunma katmanli olsun:
# process'e hic verilmezse sizdirilamaz.
ENV_ALLOW = (
    "SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP",
    "OS", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
    "PROCESSOR_IDENTIFIER", "SYSTEMDRIVE", "LANG", "LC_ALL", "TZ",
)
# Adinda bunlardan biri gecen degisken, allowlist'te olsa bile atilir.
ENV_SECRET_RE = re.compile(
    r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD|API|CREDENTIAL|AUTH|COOKIE|SESSION",
    re.I,
)

_lock = threading.RLock()
_stats = {
    "planned": 0, "ran": 0, "blocked": 0, "timed_out": 0, "failed": 0,
    "approval_required": 0, "skip_static_used": 0, "total_s": 0.0,
    "last": None,
}

# Python bayraklari bir kez proplanir (asagiya bak).
_py_flags_cache = None


# ─── STATIK KAPI ───────────────────────────────────────────────────────
def _dotted(node) -> str:
    """Attribute zincirini "a.b.c" olarak geri kur. Cozulemezse "" doner."""
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    else:
        return ""
    return ".".join(reversed(parts))


def static_check(code: str, lang: str = "python", allow_net: bool = False,
                 extra_allow: list = None) -> dict:
    """Kodu CALISTIRMADAN tara.

    Doner: {"ok", "blocked":[str], "warnings":[str], "imports":[str],
            "syntax_error":str|None, "lang", "weak_gate":bool}
    ok=False ise run_sandboxed hic process baslatmaz.
    """
    out = {"ok": False, "blocked": [], "warnings": [], "imports": [],
           "syntax_error": None, "lang": lang, "weak_gate": False}
    code = code or ""
    if not code.strip():
        out["blocked"].append("kod bos")
        return out
    if len(code) > MAX_CODE_CHARS:
        out["blocked"].append(f"kod cok uzun ({len(code)} > {MAX_CODE_CHARS})")
        return out

    if lang in ("js", "javascript", "node"):
        # AST yok: bu kapi Python kapisindan zayif. Cagirana bildiriyoruz
        # ki "tarandi" yanilgisina dusmesin.
        out["weak_gate"] = True
        out["warnings"].append(
            "JS icin AST yok; tarama regex tabanli ve Python'dan zayif")
        for pat, why in JS_DENY_PATTERNS:
            if re.search(pat, code):
                out["blocked"].append(f"JS: {why}")
        if not shutil.which("node"):
            out["blocked"].append("node bulunamadi (JS calistirilamaz)")
        out["ok"] = not out["blocked"]
        return out

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        out["syntax_error"] = f"satir {e.lineno}: {e.msg}"
        out["blocked"].append(f"sozdizimi hatasi: {out['syntax_error']}")
        return out
    except Exception as e:                      # ast cok derin nesting'de patlar
        out["blocked"].append(f"ayristirilamadi: {type(e).__name__}")
        return out

    allowed = set(ALLOWED_IMPORTS)
    if extra_allow:
        allowed |= {str(x).split(".")[0] for x in extra_allow}

    seen_imports = set()
    for node in ast.walk(tree):
        # ── import'lar ──
        if isinstance(node, ast.Import):
            for a in node.names:
                seen_imports.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:                      # "from . import x" — paket yok
                out["blocked"].append("goreli import (paket baglami yok)")
            if node.module:
                seen_imports.add(node.module.split(".")[0])

        # ── cagrilar ──
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id in DENIED_NAMES:
                out["blocked"].append(f"yasakli cagri: {f.id}()")
            elif isinstance(f, ast.Attribute):
                dp = _dotted(f)
                if dp:
                    for pref in DENIED_PATH_PREFIXES:
                        if dp.startswith(pref):
                            out["blocked"].append(f"yasakli cagri: {dp}()")
                            break
                if f.attr in DENIED_ATTR_LEAVES:
                    out["blocked"].append(f"yasakli metod: .{f.attr}()")
                # open() disinda dosya yazan bir sey kalmasin diye:
            if isinstance(f, ast.Name) and f.id == "open":
                # open YASAK DEGIL — CSV okumak mesru bir CodeAct isi.
                # Ama dosya I/O varsa needs_approval() daima True olur.
                out["warnings"].append("dosya I/O (open) — onay gerekir")

        # ── dunder kacamaklari ──
        elif isinstance(node, ast.Attribute):
            if node.attr in ("__globals__", "__builtins__", "__subclasses__",
                             "__bases__", "__mro__", "__class__",
                             "__code__", "__dict__", "__loader__",
                             "__getattribute__", "__reduce__"):
                out["blocked"].append(f"dunder erisimi: .{node.attr}")
        elif isinstance(node, ast.Name):
            if node.id in ("__builtins__", "__import__", "__loader__"):
                out["blocked"].append(f"dunder erisimi: {node.id}")

    out["imports"] = sorted(seen_imports)
    for mod in sorted(seen_imports):
        if mod in HARD_DENY_IMPORTS:
            out["blocked"].append(f"yasakli modul: {mod}")
        elif mod in NET_IMPORTS and not allow_net:
            out["blocked"].append(f"ag modulu (allow_net=False): {mod}")
        elif mod not in allowed and mod not in NET_IMPORTS:
            out["blocked"].append(f"allowlist disi modul: {mod}")

    # Tekrarlari at, sirayi koru
    out["blocked"] = list(dict.fromkeys(out["blocked"]))
    out["warnings"] = list(dict.fromkeys(out["warnings"]))
    out["ok"] = not out["blocked"]
    return out


def needs_approval(code: str, lang: str = "python") -> bool:
    """Onay gerekiyor mu? SUPHEDE DAIMA True (fail-closed).

    False donmesi icin kodun hepsi dogru olmali: statik kapi temiz, dosya
    I/O yok, kisa, ve sadece saf-hesap modulleri kullaniyor. Bunlarin biri
    bile saglanmazsa insan onayi ister.
    """
    if lang not in ("python", "py"):
        return True                              # JS kapisi zayif -> hep onay
    st = static_check(code, lang)
    if not st["ok"] or st["warnings"]:
        return True
    if len((code or "").splitlines()) > TRIVIAL_MAX_LINES:
        return True
    pure = {"math", "json", "re", "datetime", "random", "itertools",
            "functools", "collections", "statistics", "string", "decimal",
            "fractions", "textwrap", "operator", "bisect", "heapq",
            "unicodedata", "calendar", "difflib", "pprint", "copy"}
    return not set(st["imports"]).issubset(pure)


# ─── KOD CIKARMA / PROMPT ──────────────────────────────────────────────
_FENCE_RE = re.compile(
    r"```[ \t]*(python|py|javascript|js|node)?[ \t]*\r?\n(.*?)```",
    re.S | re.I,
)
_LANG_MAP = {"py": "python", "python": "python",
             "js": "js", "javascript": "js", "node": "js"}


def extract_code(text: str) -> dict:
    """LLM yanitindan tek kod blogunu cek.

    Doner: {"lang", "code", "found":bool, "blocks":int}
    Birden fazla blok varsa EN UZUNU alinir — modeller aciklama icin
    kucuk ornek bloklar da yazar, plan genelde en uzun olandir.
    """
    text = text or ""
    matches = _FENCE_RE.findall(text)
    if matches:
        best_lang, best_code = "", ""
        for lang, body in matches:
            if len(body) > len(best_code):
                best_lang, best_code = (lang or "").lower(), body
        code = best_code.strip("\n")
        lang = _LANG_MAP.get(best_lang, "python")
        return {"lang": lang, "code": code, "found": bool(code.strip()),
                "blocks": len(matches)}

    # Fence yoksa: bariz Python gorunuyorsa duz metni kabul et.
    stripped = text.strip()
    looks_py = bool(re.search(
        r"^\s*(import |from |def |class |print\(|for |while |if |with )",
        stripped, re.M))
    if looks_py:
        return {"lang": "python", "code": stripped, "found": True, "blocks": 0}
    return {"lang": "python", "code": "", "found": False, "blocks": 0}


def build_messages(task: str, tools_doc: str = "") -> list:
    """CodeAct icin OpenAI mesaj listesi.

    Modelden TEK fenced blok istenir; kutuphane kisiti ve print zorunlulugu
    acikca soylenir. Kisiti prompt'ta soylemek statik kapinin bosa
    calismasini azaltir (blok reddedilirse tur kazanci kaybolur).
    """
    allowed = ", ".join(sorted(ALLOWED_IMPORTS))
    system = (
        "Sen ALES'in CodeAct planlayicisisin. Kullanicinin gorevini TEK bir "
        "Python kod blogu olarak coz.\n\n"
        "KURALLAR:\n"
        f"1. SADECE bu standart kutuphaneleri kullanabilirsin: {allowed}\n"
        "2. os, sys, subprocess, shutil, socket, requests, ctypes, "
        "threading, pickle KULLANMA — blok reddedilir.\n"
        "3. Ag erisimi YOK. Internetten veri cekmeye calisma.\n"
        "4. Sonucu mutlaka print() ile yaz. Hicbir sey yazdirmayan kod "
        "basarisiz sayilir.\n"
        "5. Yanitin TEK bir ```python fenced blogu olsun. Blok disinda "
        "en fazla 2 cumle aciklama yaz.\n"
        "6. Kodun kendi kendine yeterli olsun: girdi bekleme, input() "
        "cagirma, sonsuz dongu kurma.\n"
        f"7. Kod {TRIVIAL_MAX_LINES * 3} satiri gecmesin.\n"
    )
    if tools_doc:
        system += ("\nKULLANILABILIR VERI/ARAC NOTLARI:\n" + tools_doc.strip() + "\n")
    return [{"role": "system", "content": system},
            {"role": "user", "content": (task or "").strip()}]


# ─── SANDBOX ───────────────────────────────────────────────────────────
_py_exe_cache = None


def _python_exe() -> str:
    """CodeAct'in plan dosyasini calistiracagi GERCEK CPython'u bul.

    KRITIK (PyInstaller ile paketleme): Donmus (.exe) derlemede
    sys.executable ALES.exe'dir, python.exe DEGIL. Eskiden argv'ye dogrudan
    sys.executable veriliyordu; .exe icinde bu, plan.py'yi calistirmak
    yerine ALES'in IKINCI bir kopyasini baslatirdi -- port 8000 cakisir,
    yeni bir tarayici sekmesi acilir ve kullanici bunu "CodeAct bozuk"
    olarak degil "ALES kendini cogaltiyor" olarak gorurdu.

    Bu yuzden donmus modda sistemde kurulu bir python.exe ariyoruz.
    Bulunamazsa BOS string doner ve run_sandboxed Python planini
    calistirmayi REDDEDER: yanlis process baslatmaktansa nedenini soyleyip
    durmak dogrudur. JS yolu (node) bundan etkilenmez.
    """
    global _py_exe_cache
    if _py_exe_cache is not None:
        return _py_exe_cache
    if not getattr(sys, "frozen", False):
        _py_exe_cache = sys.executable or ""
        return _py_exe_cache
    me = os.path.basename(sys.executable or "").lower()
    found = ""
    for name in ("python", "python3", "py"):
        p = shutil.which(name)
        if not p or os.path.basename(p).lower() == me:
            continue          # kendimizi bulduysak atla (sonsuz dongu olur)
        try:
            r = subprocess.run([p, "-c", "print(1)"], capture_output=True,
                               text=True, timeout=10)
            if r.returncode == 0 and "1" in (r.stdout or ""):
                found = p
                break
        except Exception:
            continue
    _py_exe_cache = found
    return found


def python_available() -> bool:
    """Python plani calistirilabilir mi? (UI bunu gosterir.)"""
    return bool(_python_exe())


def _py_flags() -> list:
    """Python bayraklari: ["-I", "-S"] tercih edilir.

    -I  = izole mod (PYTHONPATH, kullanici site-packages, PYTHON* env yok)
    -S  = site.py hic yuklenmez -> site-packages sys.path'e GIRMEZ, yani
          statik kapi bir sey kacirsa bile "import requests" calismaz.
          Bu ikinci savunma katmani.
    Bazi bozuk kurulumlarda -S stdlib yolunu bozar; bunu bir kez, ucuz bir
    prob ile olcup sonucu onbellekleriz (kullanici anlamsiz hata gormesin).
    """
    global _py_flags_cache
    if _py_flags_cache is not None:
        return list(_py_flags_cache)
    flags = ["-I", "-S"]
    try:
        p = subprocess.run([_python_exe() or sys.executable, "-I", "-S", "-c",
                            "import json,math;print(1)"],
                           capture_output=True, text=True, timeout=10)
        if p.returncode != 0 or "1" not in (p.stdout or ""):
            flags = ["-I"]
    except Exception:
        flags = ["-I"]
    _py_flags_cache = list(flags)
    return list(flags)


def _clean_env() -> dict:
    """Gizli-anahtarlardan arindirilmis minimal ortam."""
    env = {}
    for k in ENV_ALLOW:
        v = os.environ.get(k)
        if v and not ENV_SECRET_RE.search(k):
            env[k] = v
    # Turkce cikti Windows'un cp1254/cp857 varsayilaninda bozulur.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _clip(s: str) -> tuple:
    s = s or ""
    if len(s) <= MAX_OUTPUT_CHARS:
        return s, False
    return s[:MAX_OUTPUT_CHARS] + "\n...(kirpildi)", True


def _kill_tree(proc):
    """Process'i (ve varsa cocuklarini) oldur. Windows'ta taskkill /T."""
    try:
        proc.kill()
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=5)
        except Exception:
            pass
    try:
        proc.wait(timeout=3)
    except Exception:
        pass


def run_sandboxed(code: str, lang: str = "python", timeout_s: float = None,
                  allow_net: bool = False, extra_allow: list = None,
                  skip_static: bool = False) -> dict:
    """Kodu izole process'te calistir.

    Doner: {"ok","stdout","stderr","exit_code","elapsed","timed_out",
            "blocked":[str],"lang","truncated":bool,"static":dict|None}

    skip_static SADECE kullanici acikca onayladigi parcalar icin vardir ve
    stats()'ta ayrica sayilir; hicbir yerde varsayilan degildir.
    """
    t0 = time.time()
    timeout_s = float(timeout_s or SANDBOX_TIMEOUT_S)
    lang = _LANG_MAP.get((lang or "python").lower(), "python")
    res = {"ok": False, "stdout": "", "stderr": "", "exit_code": None,
           "elapsed": 0.0, "timed_out": False, "blocked": [], "lang": lang,
           "truncated": False, "static": None}

    st = None
    if skip_static:
        with _lock:
            _stats["skip_static_used"] += 1
    else:
        st = static_check(code, lang, allow_net=allow_net,
                          extra_allow=extra_allow)
        res["static"] = st
        if not st["ok"]:
            res["blocked"] = st["blocked"]
            res["stderr"] = "Statik kapi reddetti:\n- " + "\n- ".join(st["blocked"])
            res["elapsed"] = round(time.time() - t0, 3)
            with _lock:
                _stats["blocked"] += 1
                _stats["last"] = {"lang": lang, "blocked": st["blocked"],
                                  "at": time.time()}
            return res

    workdir = None
    proc = None
    try:
        # Temiz calisma dizini: goreli bir dosya yazimi proje agacina
        # degil bu gecici klasore dusmeli.
        workdir = tempfile.mkdtemp(prefix="ales_codeact_")
        if lang == "js":
            node = shutil.which("node")
            if not node:
                res["blocked"] = ["node bulunamadi"]
                res["stderr"] = "node bulunamadi (JS calistirilamaz)"
                res["elapsed"] = round(time.time() - t0, 3)
                with _lock:
                    _stats["blocked"] += 1
                return res
            path = os.path.join(workdir, "plan.js")
            with open(path, "w", encoding="utf-8") as f:
                f.write(code)
            argv = [node, "--no-warnings", path]
        else:
            py = _python_exe()
            if not py:
                # Donmus .exe icinde sistem Python'u yok. sys.executable'i
                # kullanmak ALES'in kendisini yeniden baslatirdi (bkz.
                # _python_exe dokumantasyonu), o yuzden REDDEDIYORUZ.
                res["blocked"] = ["python bulunamadi"]
                res["stderr"] = (
                    "Python yorumlayicisi bulunamadi. Paketlenmis ALES.exe "
                    "icinde Python plani calistirmak icin sistemde kurulu bir "
                    "Python gerekir: python.org'dan kurun ve kurulumda "
                    "\"Add python.exe to PATH\" secenegini isaretleyin. "
                    "(JavaScript planlari node ile calismaya devam eder.)")
                res["elapsed"] = round(time.time() - t0, 3)
                with _lock:
                    _stats["blocked"] += 1
                return res
            path = os.path.join(workdir, "plan.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(code)
            argv = [py] + _py_flags() + [path]

        creation = 0
        if sys.platform == "win32":
            # Yeni process grubu: timeout'ta tum agaci oldurebilelim ve
            # Ctrl+C sinyali ALES'e sizmasin.
            creation = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            creation |= getattr(subprocess, "CREATE_NO_WINDOW", 0)

        proc = subprocess.Popen(
            argv, cwd=workdir, env=_clean_env(),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,          # input() beklerse aninda EOF
            text=True, encoding="utf-8", errors="replace",
            creationflags=creation,
        )
        try:
            out, err = proc.communicate(timeout=timeout_s)
            res["exit_code"] = proc.returncode
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            try:
                out, err = proc.communicate(timeout=3)
            except Exception:
                out, err = "", ""
            res["timed_out"] = True
            res["exit_code"] = -1
            err = (err or "") + f"\n[ALES] Zaman asimi ({timeout_s:.0f}s) — process oldruldu"
            with _lock:
                _stats["timed_out"] += 1

        res["stdout"], t1 = _clip(out)
        res["stderr"], t2 = _clip(err)
        res["truncated"] = bool(t1 or t2)
        res["ok"] = (not res["timed_out"]) and res["exit_code"] == 0
    except Exception as e:
        res["stderr"] = f"[ALES] Sandbox hatasi: {type(e).__name__}: {e}"
        res["ok"] = False
    finally:
        if proc is not None and proc.poll() is None:
            _kill_tree(proc)
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)

    res["elapsed"] = round(time.time() - t0, 3)
    with _lock:
        _stats["ran"] += 1
        _stats["total_s"] += res["elapsed"]
        if not res["ok"]:
            _stats["failed"] += 1
        _stats["last"] = {"lang": lang, "ok": res["ok"],
                          "exit_code": res["exit_code"],
                          "elapsed": res["elapsed"],
                          "timed_out": res["timed_out"], "at": time.time()}
    return res


# ─── PLANLA + CALISTIR ─────────────────────────────────────────────────
async def plan_and_run(task: str, ask_llm, approve_cb=None, tools_doc: str = "",
                       timeout_s: float = None, allow_net: bool = False,
                       extra_allow: list = None) -> dict:
    """Gorevi tek kod blogu olarak plancak ve (onay varsa) calistir.

    ask_llm    : async (messages: list) -> str      (main.py router kapatmasi)
    approve_cb : async (code: str, static: dict) -> bool
                 None ise ve onay gerekiyorsa KOD CALISTIRILMAZ.

    Doner: {"ok","code","lang","static","ran","result","needs_approval",
            "error","elapsed"}
    """
    t0 = time.time()
    out = {"ok": False, "code": "", "lang": "python", "static": None,
           "ran": False, "result": None, "needs_approval": False,
           "error": None, "elapsed": 0.0}
    with _lock:
        _stats["planned"] += 1

    if not callable(ask_llm):
        out["error"] = "ask_llm verilmedi"
        out["elapsed"] = round(time.time() - t0, 3)
        return out

    try:
        reply = await ask_llm(build_messages(task, tools_doc))
    except Exception as e:
        out["error"] = f"LLM hatasi: {type(e).__name__}: {e}"
        out["elapsed"] = round(time.time() - t0, 3)
        return out

    ex = extract_code(reply if isinstance(reply, str) else str(reply or ""))
    if not ex["found"]:
        out["error"] = "modelin yanitinda kod blogu yok"
        out["elapsed"] = round(time.time() - t0, 3)
        return out
    out["code"], out["lang"] = ex["code"], ex["lang"]

    st = static_check(out["code"], out["lang"], allow_net=allow_net,
                      extra_allow=extra_allow)
    out["static"] = st
    if not st["ok"]:
        out["error"] = "statik kapi reddetti: " + "; ".join(st["blocked"])
        out["elapsed"] = round(time.time() - t0, 3)
        with _lock:
            _stats["blocked"] += 1
        return out

    out["needs_approval"] = needs_approval(out["code"], out["lang"])
    if out["needs_approval"]:
        with _lock:
            _stats["approval_required"] += 1
        if approve_cb is None:
            # KURAL: onay kapisi olmadan AI kodu calistirilmaz.
            out["error"] = "onay gerekiyor (approve_cb verilmedi)"
            out["elapsed"] = round(time.time() - t0, 3)
            return out
        try:
            ok = await approve_cb(out["code"], st)
        except Exception as e:
            out["error"] = f"onay geri cagrisi hatasi: {type(e).__name__}"
            out["elapsed"] = round(time.time() - t0, 3)
            return out
        if not ok:
            out["error"] = "kullanici onaylamadi"
            out["elapsed"] = round(time.time() - t0, 3)
            return out

    res = run_sandboxed(out["code"], out["lang"], timeout_s=timeout_s,
                        allow_net=allow_net, extra_allow=extra_allow)
    out["ran"] = True
    out["result"] = res
    out["ok"] = bool(res.get("ok"))
    if not out["ok"]:
        out["error"] = (res.get("stderr") or "")[:500] or "calisma basarisiz"
    out["elapsed"] = round(time.time() - t0, 3)
    return out


# ─── ISTATISTIK ────────────────────────────────────────────────────────
def stats() -> dict:
    with _lock:
        s = dict(_stats)
    s["avg_s"] = round(s["total_s"] / s["ran"], 3) if s["ran"] else 0.0
    s["total_s"] = round(s["total_s"], 3)
    s["timeout_s"] = SANDBOX_TIMEOUT_S
    s["max_output_chars"] = MAX_OUTPUT_CHARS
    s["allowed_imports"] = len(ALLOWED_IMPORTS)
    s["py_flags"] = _py_flags_cache or ["-I", "-S"]
    return s


def reset_stats() -> dict:
    with _lock:
        _stats.update({"planned": 0, "ran": 0, "blocked": 0, "timed_out": 0,
                       "failed": 0, "approval_required": 0,
                       "skip_static_used": 0, "total_s": 0.0, "last": None})
    return stats()


def info() -> dict:
    """UI icin: kapinin ne oldugunu kullaniciya gosterebilmek."""
    return {
        "allowed_imports": sorted(ALLOWED_IMPORTS),
        "net_imports_blocked": sorted(NET_IMPORTS),
        "hard_denied": sorted(HARD_DENY_IMPORTS),
        "timeout_s": SANDBOX_TIMEOUT_S,
        "max_output_chars": MAX_OUTPUT_CHARS,
        "node_available": bool(shutil.which("node")),
        # Donmus .exe'de sistem Python'u olmayabilir; UI bunu gostersin ki
        # "CodeAct calismiyor" sessiz bir bilmece olarak kalmasin.
        "python_available": python_available(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "approval_required_by_default": True,
        "note": ("AI kodu onay olmadan calistirilmaz; her calisma ayri "
                 "process + timeout + gizli anahtarlardan arindirilmis ortam."),
    }
