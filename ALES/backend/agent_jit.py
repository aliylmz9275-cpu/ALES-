"""
agent_jit.py — Agent JIT: gorev tanimini calistirilabilir koda "derle" ve SAKLA.

NEDEN: CodeAct bir gorevi tek kod blogu haline getirir ama her seferinde
modele sorar. Ayni gorev ikinci kez geldiginde LLM'e hic gitmemek gerekir.
Bu modulun asil kazanci ONBELLEK: derlenmis blok normalize edilmis gorev
metnine gore saklanir; tekrar isteginde blok dogrudan calisir, LLM cagrisi
yapilmaz. stats()["llm_calls_saved"] tam olarak bunu sayar.

Rakam iddiasi yok: hiz kazanci bu tree'de olculmedi, mekanizma
"tekrar eden gorevde LLM turunu tamamen atlamak".

KATMAN SIRASI (main.py run_agent icinde):
  fast_path (deterministik, 0 LLM)  ->  agent_jit (derlenmis blok, 0 LLM)
  ->  semantic_cache (benzer soru)  ->  router zinciri (LLM)
JIT, fast_path'in "yazilmis kural" gerektirdigi yerde devreye girer:
kural yoktur ama bu gorev daha once cozulmustur.

GUVENLIK: Calistirma HER ZAMAN code_act_executor.run_sandboxed uzerinden
olur — ayri process, timeout, statik kapi. Bu modulde exec()/eval() YOK.
code_act_executor yuklenemezse jit_run calismayi REDDEDER; asla kendi
basina kod calistirmaya kalkmaz.

BAYAT KOD TEHLIKESI: Onbellekteki blok, dunya degistikten sonra da mutlu
mesut calismaya devam eder. Bu yuzden uc kapi var:
  1. JIT_VERSION — semantik degisirse eski girdiler gecersiz sayilir.
  2. FAIL_LIMIT — ust uste basarisiz olan girdi KARANTINAYA alinir.
  3. invalidate()/clear() — kullanici elle temizleyebilir.
"""
import asyncio
import hashlib
import json
import math
import os
import re
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Optional

try:
    import code_act_executor
except Exception as _e:                                  # noqa: F841
    code_act_executor = None

try:
    from config_manager import get_appdata_dir
    _JIT_FILE = get_appdata_dir() / "agent_jit.json"
except Exception:
    _JIT_FILE = Path("agent_jit.json")

# ─── AYARLAR ───────────────────────────────────────────────────────────
JIT_VERSION = 1          # semantik degisirse artir -> eski girdiler duser
MAX_ENTRIES = 200        # LRU tahliye siniri
FAIL_LIMIT = 2           # ust uste bu kadar hata -> karantina
MIN_TASK_CHARS = 8       # bundan kisa gorev metni anlamli anahtar uretmez
SIM_THRESHOLD = 0.92     # yakin-eslesme esigi (tam eslesme yoksa)

# semantic_cache.py ile AYNI normalizasyon: ALES'te tek idiom olsun.
_TR = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "İ": "i", "ö": "o",
                     "ş": "s", "ü": "u", "Ç": "c", "Ğ": "g", "Ö": "o",
                     "Ş": "s", "Ü": "u", "I": "i"})
_PUNCT_RE = re.compile(r"[^\w\s]", re.U)
_WS_RE = re.compile(r"\s+")
# Sayilar/tarihler gorevin KIMLIGI degil PARAMETRESIDIR: "12 sayisinin
# karekoku" ile "27 sayisinin karekoku" ayni derlenmis plan olmali diye
# rakamlari maskeleriz.
_NUM_RE = re.compile(r"\b\d+([.,]\d+)?\b")

_lock = threading.RLock()
_entries = None          # {key: entry} — tembel yuklenir
_stats = {"hits": 0, "misses": 0, "compiles": 0, "runs": 0, "failures": 0,
          "quarantined": 0, "llm_calls_saved": 0, "stale_version": 0,
          # Cizge sayaclari BASLANGICTA da burada dursun: aksi halde hic
          # cizge kurulmadan once /jit/graphs bu anahtarlari HIC gormez ve
          # panel "0" ile "olculmedi" arasindaki farki soyleyemez.
          "graphs_compiled": 0, "graphs_executed": 0,
          "graph_nodes_run": 0, "graph_layers": 0}


# ─── NORMALIZASYON / ANAHTAR ───────────────────────────────────────────
def normalize(task: str) -> str:
    """Gorev metnini eslesme icin sadelestir (goruntulenen metin degismez)."""
    if not task:
        return ""
    t = task.translate(_TR).casefold()
    t = _PUNCT_RE.sub(" ", t)
    t = _NUM_RE.sub(" <n> ", t)
    return _WS_RE.sub(" ", t).strip()


def cache_key(task: str) -> str:
    """Normalize edilmis gorevin kisa, kararli hash'i."""
    return hashlib.sha1(normalize(task).encode("utf-8")).hexdigest()[:16]


def _vec(norm: str) -> Counter:
    return Counter(norm.split())


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[t] * b[t] for t in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


# ─── KALICILIK ─────────────────────────────────────────────────────────
def _load() -> dict:
    """Tembel yukleme. Bozuk dosya sessizce bos onbellege duser — JIT
    onbellegi kaybetmek kotu degil, uygulamayi acmamak kotu."""
    global _entries
    if _entries is not None:
        return _entries
    data = {}
    try:
        if _JIT_FILE.exists():
            raw = json.loads(_JIT_FILE.read_text(encoding="utf-8"))
            for k, e in (raw.get("entries") or {}).items():
                if isinstance(e, dict) and e.get("code"):
                    data[k] = e
    except Exception:
        data = {}
    _entries = data
    return _entries


def _save():
    """Atomik yazim: .tmp'ye yaz, sonra os.replace. Yazim ortasinda cokme
    onbellegi bozmasin (yarim JSON = her acilista sifirlanan onbellek)."""
    try:
        d = _load()
        payload = {"version": JIT_VERSION, "saved_at": time.time(), "entries": d}
        tmp = _JIT_FILE.with_suffix(".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(str(tmp), str(_JIT_FILE))
    except Exception:
        pass


def _evict():
    """MAX_ENTRIES asilirsa en az kullanilan + en eski gider (LRU)."""
    d = _load()
    if len(d) <= MAX_ENTRIES:
        return
    items = sorted(d.items(),
                   key=lambda kv: (kv[1].get("uses", 0),
                                   kv[1].get("last_used", 0)))
    for k, _ in items[:len(d) - MAX_ENTRIES]:
        d.pop(k, None)


# ─── ARAMA / SAKLAMA ───────────────────────────────────────────────────
def _find(task: str):
    """Eslesen girdiyi bul. SAYAC TUTMAZ, girdiyi DEGISTIRMEZ.

    Doner: (girdi_referansi | None, benzerlik, sebep). Cagiran _lock'u
    tutmali. lookup() ve peek() ayni karari vermek zorunda oldugu icin
    karar mantigi TEK yerde duruyor — ikisi sadece yan etkide farkli.
    """
    if not task or len(task.strip()) < MIN_TASK_CHARS:
        return None, 0.0, "kisa"
    d = _load()
    e = d.get(cache_key(task))
    if e is not None:
        if e.get("jit_version") != JIT_VERSION:
            return None, 0.0, "stale"
        if e.get("quarantined"):
            return None, 0.0, "karantina"
        return e, 1.0, "tam"
    # Tam eslesme yok: yakin bir gorev var mi?
    qv = _vec(normalize(task))
    best, best_sim = None, 0.0
    for cand in d.values():
        if cand.get("quarantined") or cand.get("jit_version") != JIT_VERSION:
            continue
        sim = _cosine(qv, _vec(cand.get("norm", "")))
        if sim > best_sim:
            best, best_sim = cand, sim
    if best and best_sim >= SIM_THRESHOLD:
        return best, round(best_sim, 4), "yakin"
    return None, round(best_sim, 4), "yok"


def lookup(task: str) -> dict:
    """Kullanilabilir derlenmis girdi varsa dondur, yoksa None.

    None doner: yok / karantinada / JIT_VERSION eski. Bu uc durum
    ayri ayri stats()'a yazilir ki kullanici neden HIT almadigini gorebilsin.
    """
    with _lock:
        e, sim, reason = _find(task)
        if e is None:
            if reason == "stale":
                _stats["stale_version"] += 1
            if reason != "kisa":
                _stats["misses"] += 1
            return None
        _stats["hits"] += 1
        e["last_used"] = time.time()
        e["uses"] = e.get("uses", 0) + 1
        out = dict(e)
        out["similarity"] = sim
        return out


def peek(task: str) -> dict:
    """lookup() ile AYNI karari verir, ama sayaclara ve girdiye DOKUNMAZ.

    NEDEN VAR: cagiran taraf (main.py'deki JIT hizli yolu) once "bu kod
    onay gerektiriyor mu" diye bakmak, sonra jit_run() ile calistirmak
    istiyor. Bunu lookup() ile yapmak ayni isabeti IKI kez sayardi —
    hit sayaci ve 'uses' degeri sisip, panelde gercekte olandan daha
    fazla JIT kullanimi gorunurdu.
    """
    with _lock:
        e, sim, _ = _find(task)
        if e is None:
            return None
        out = dict(e)
        out["similarity"] = sim
        return out


def store(task: str, code: str, lang: str = "python", static: dict = None,
          source_model: str = "") -> dict:
    """Derlenmis blogu sakla (veya var olani guncelle)."""
    with _lock:
        d = _load()
        k = cache_key(task)
        now = time.time()
        prev = d.get(k) or {}
        e = {
            "key": k,
            "task": (task or "")[:600],
            "norm": normalize(task),
            "code": code or "",
            "lang": lang or "python",
            "jit_version": JIT_VERSION,
            "created": prev.get("created", now),
            "last_used": now,
            "uses": prev.get("uses", 0),
            "ok_count": prev.get("ok_count", 0),
            "fail_count": 0,                    # yeni kod -> hata sayaci sifir
            "consecutive_fails": 0,
            "elapsed_avg": prev.get("elapsed_avg", 0.0),
            "source_model": source_model or prev.get("source_model", ""),
            "static": static or {},
            "quarantined": False,
            "quarantine_reason": "",
        }
        d[k] = e
        _stats["compiles"] += 1
        _evict()
        _save()
        return dict(e)


def record_result(key: str, ok: bool, elapsed: float = 0.0) -> dict:
    """Calisma sonucunu isle. FAIL_LIMIT ust uste hata -> karantina."""
    with _lock:
        d = _load()
        e = d.get(key)
        if not e:
            return {"ok": False, "error": "girdi yok"}
        _stats["runs"] += 1
        if ok:
            e["ok_count"] = e.get("ok_count", 0) + 1
            e["consecutive_fails"] = 0
            n = e["ok_count"]
            prev = e.get("elapsed_avg", 0.0)
            e["elapsed_avg"] = round((prev * (n - 1) + float(elapsed or 0)) / n, 3)
        else:
            _stats["failures"] += 1
            e["fail_count"] = e.get("fail_count", 0) + 1
            e["consecutive_fails"] = e.get("consecutive_fails", 0) + 1
            if e["consecutive_fails"] >= FAIL_LIMIT and not e.get("quarantined"):
                e["quarantined"] = True
                e["quarantine_reason"] = f"{e['consecutive_fails']} ust uste hata"
                _stats["quarantined"] += 1
        _save()
        return {"ok": True, "entry": dict(e)}


def invalidate(key: str) -> bool:
    with _lock:
        d = _load()
        gone = d.pop(key, None) is not None
        if gone:
            _save()
        return gone


def quarantine(key: str, reason: str = "") -> bool:
    """Girdiyi devre disi birak ama SILME.

    Neden silmiyoruz: bozuk bir derlenmis blok, hangi gorevin nasil yanlis
    cozuldugunu gosteren tek kanittir. Silinirse kullanici ayni gorevde
    tekrar tekrar ayni hataya duser ve nedenini goremez.
    """
    with _lock:
        d = _load()
        e = d.get(key)
        if not e:
            return False
        if not e.get("quarantined"):
            _stats["quarantined"] += 1
        e["quarantined"] = True
        e["quarantine_reason"] = reason or "elle karantina"
        _save()
        return True


def unquarantine(key: str) -> bool:
    with _lock:
        d = _load()
        e = d.get(key)
        if not e:
            return False
        e["quarantined"] = False
        e["quarantine_reason"] = ""
        e["consecutive_fails"] = 0
        _save()
        return True


def clear() -> dict:
    with _lock:
        d = _load()
        n = len(d)
        d.clear()
        _save()
        return {"ok": True, "cleared": n}


def list_entries(limit: int = 50) -> list:
    """UI listesi. Kod GOVDESI YOK (code_chars var) — 200 girdinin tam kodu
    bir listeleme yanitini gereksiz sisirir."""
    with _lock:
        d = _load()
        items = sorted(d.values(), key=lambda e: e.get("last_used", 0),
                       reverse=True)[:max(1, int(limit))]
        out = []
        for e in items:
            out.append({
                "key": e.get("key"), "task": e.get("task", "")[:180],
                "lang": e.get("lang"), "code_chars": len(e.get("code") or ""),
                "uses": e.get("uses", 0), "ok_count": e.get("ok_count", 0),
                "fail_count": e.get("fail_count", 0),
                "consecutive_fails": e.get("consecutive_fails", 0),
                "elapsed_avg": e.get("elapsed_avg", 0.0),
                "quarantined": bool(e.get("quarantined")),
                "quarantine_reason": e.get("quarantine_reason", ""),
                "jit_version": e.get("jit_version"),
                "stale": e.get("jit_version") != JIT_VERSION,
                "source_model": e.get("source_model", ""),
                "created": e.get("created"), "last_used": e.get("last_used"),
            })
        return out


def get_entry(key: str) -> dict:
    with _lock:
        e = _load().get(key)
        return dict(e) if e else None


# ─── DERLEME / CALISTIRMA ──────────────────────────────────────────────
async def compile_task(task: str, ask_llm, tools_doc: str = "") -> dict:
    """Gorevi koda cevir ve sakla. Calistirmaz.

    Doner: {"ok","code","lang","static","key","error"}
    """
    out = {"ok": False, "code": "", "lang": "python", "static": None,
           "key": "", "error": None}
    if code_act_executor is None:
        out["error"] = "code_act_executor yuklenemedi"
        return out
    if not callable(ask_llm):
        out["error"] = "ask_llm verilmedi"
        return out
    if not task or len(task.strip()) < MIN_TASK_CHARS:
        out["error"] = "gorev metni cok kisa"
        return out
    try:
        reply = await ask_llm(code_act_executor.build_messages(task, tools_doc))
    except Exception as e:
        out["error"] = f"LLM hatasi: {type(e).__name__}: {e}"
        return out

    ex = code_act_executor.extract_code(
        reply if isinstance(reply, str) else str(reply or ""))
    if not ex.get("found"):
        out["error"] = "modelin yanitinda kod blogu yok"
        return out
    out["code"], out["lang"] = ex["code"], ex["lang"]

    st = code_act_executor.static_check(out["code"], out["lang"])
    out["static"] = st
    if not st.get("ok"):
        # Reddedilen kodu ONBELLEGE ALMIYORUZ: bir daha calistirilamayacak
        # bir blogu saklamak, sonraki denemeyi de bosa cikarir.
        out["error"] = "statik kapi reddetti: " + "; ".join(st.get("blocked", []))
        return out

    e = store(task, out["code"], out["lang"], static=st, source_model="router")
    out["key"] = e["key"]
    out["ok"] = True
    return out


async def jit_run(task: str, ask_llm=None, approve_cb=None,
                  force_recompile: bool = False, timeout_s: float = None,
                  tools_doc: str = "") -> dict:
    """Derlenmis blok varsa onu calistir, yoksa derleyip calistir.

    Doner: {"ok","cached","key","code","lang","result","elapsed","error",
            "needs_approval"}

    cached=True yolunda ask_llm HIC cagrilmaz — modulun butun amaci bu.
    """
    t0 = time.time()
    out = {"ok": False, "cached": False, "key": "", "code": "",
           "lang": "python", "result": None, "elapsed": 0.0, "error": None,
           "needs_approval": False}

    if code_act_executor is None:
        # Kendi basina kod calistirmaya ASLA kalkismiyoruz.
        out["error"] = "code_act_executor yuklenemedi — JIT calistirma kapali"
        out["elapsed"] = round(time.time() - t0, 3)
        return out

    e = None if force_recompile else lookup(task)
    if e:
        out["cached"] = True
        out["key"] = e.get("key", "")
        out["code"], out["lang"] = e.get("code", ""), e.get("lang", "python")
        with _lock:
            _stats["llm_calls_saved"] += 1
    else:
        c = await compile_task(task, ask_llm, tools_doc=tools_doc)
        if not c["ok"]:
            out["error"] = c["error"]
            out["elapsed"] = round(time.time() - t0, 3)
            return out
        out["key"], out["code"], out["lang"] = c["key"], c["code"], c["lang"]

    # ONAY KAPISI: onbellekten gelse bile AI kodudur. Kapiyi atlamiyoruz.
    if code_act_executor.needs_approval(out["code"], out["lang"]):
        out["needs_approval"] = True
        if approve_cb is None:
            out["error"] = "onay gerekiyor (approve_cb verilmedi)"
            out["elapsed"] = round(time.time() - t0, 3)
            return out
        try:
            if not await approve_cb(out["code"], {"jit": True, "key": out["key"]}):
                out["error"] = "kullanici onaylamadi"
                out["elapsed"] = round(time.time() - t0, 3)
                return out
        except Exception as ex2:
            out["error"] = f"onay geri cagrisi hatasi: {type(ex2).__name__}"
            out["elapsed"] = round(time.time() - t0, 3)
            return out

    res = code_act_executor.run_sandboxed(out["code"], out["lang"],
                                          timeout_s=timeout_s)
    out["result"] = res
    out["ok"] = bool(res.get("ok"))
    out["elapsed"] = round(time.time() - t0, 3)
    if not out["ok"]:
        out["error"] = (res.get("stderr") or "")[:500] or "calisma basarisiz"
    if out["key"]:
        record_result(out["key"], out["ok"], out["elapsed"])
    return out


# ─── PARALEL ARAC CALISTIRMA ───────────────────────────────────────────
async def run_parallel(calls: list, execute_async, limit: int = 4,
                       safe_names: set = None) -> list:
    """(tool, args) listesini paralel calistir.

    KAPI: safe_names verilmediyse SIRALI calisir. Sebep: main.py zaten
    salt-okunur araclari (PARALLEL_SAFE_TOOLS) yan etkili olanlardan ayirmis
    durumda. Buradan her seyi paralel calistirmak o ayrimi sessizce iptal
    ederdi — mesela iki tiklama ayni anda gidebilirdi. Bu yuzden kapi
    "kapaliya duser" (fail-closed): izin listesi yoksa paralellik yok.
    """
    if not calls:
        return []
    # asyncio ARTIK MODUL BASINDA import ediliyor. Buradaki yerel import
    # gerekli goruntusu veriyordu ama tam tersi bir tuzakti: yalnizca BU
    # fonksiyonun cercevesine bir ad bagliyordu, modul genelinde HICBIR SEY
    # baglamiyordu. execute_graph da asyncio.gather cagiriyor ve orada yerel
    # import olmadigi icin NameError aliyordu — yani cizge katmani hic
    # calismadi. Kaldirildi ki bir daha "burada var, orada yok" olmasin.

    if not safe_names:
        out = []
        for name, args in calls:
            try:
                out.append(await execute_async(name, args or {}))
            except Exception as e:
                out.append(f"HATA ({name}): {type(e).__name__}: {e}")
        return out

    sem = asyncio.Semaphore(max(1, int(limit)))
    safe = set(safe_names)

    async def _one(name, args):
        if name not in safe:
            # Guvenli listede degil -> paralel calistirmiyoruz.
            return f"HATA ({name}): paralel-guvenli listede degil"
        async with sem:
            try:
                return await execute_async(name, args or {})
            except Exception as e:
                return f"HATA ({name}): {type(e).__name__}: {e}"

    return await asyncio.gather(*[_one(n, a) for n, a in calls])


# ═══════════════════════════════════════════════════════════════════════
# AGINT-TARZI ÇİZGE DERLEMESİ (Agentic Execution Graphs - NeurIPS 2025)
# ═══════════════════════════════════════════════════════════════════════
class ExecutionNode:
    """Çizgedeki tek bir işlem düğümü (subtask/tool)."""
    def __init__(self, node_id: str, tool: str, args: dict = None,
                 depends_on: list = None, is_speculative: bool = False,
                 desc: str = ""):
        self.node_id = node_id
        self.tool = tool
        self.args = args or {}
        self.depends_on = list(depends_on or [])
        self.is_speculative = bool(is_speculative)
        self.desc = desc or f"{tool}(...)"
        self.status = "pending"   # pending | running | done | failed | skipped
        self.output = None
        self.error = None
        self.elapsed = 0.0

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id, "tool": self.tool, "args": self.args,
            "depends_on": self.depends_on, "is_speculative": self.is_speculative,
            "desc": self.desc, "status": self.status, "output": str(self.output)[:200] if self.output else None,
            "error": self.error, "elapsed": round(self.elapsed, 3)
        }


def _graph_id(task: str) -> str:
    """Cizge kimligini uretir — store ve lookup AYNI yerden okumak zorunda.

    Eskiden __init__ `task.encode()`, lookup_graph ise `task.strip().encode()`
    kullaniyordu: basinda/sonunda bosluk olan her gorev bir kimlikle
    saklanip baska bir kimlikle aranacakti, yani onbellek HIC tutmayacakti
    ve bu hicbir hata uretmeyecekti. Tek kaynak birakildi.
    """
    return hashlib.sha256(task.strip().encode("utf-8")).hexdigest()[:16]


class ExecutionGraph:
    """Yönlü döngüsüz yürütme çizgesi (DAG). Bağımsız adımları paralel çalıştırır."""
    def __init__(self, task: str = "", graph_id: str = ""):
        self.graph_id = graph_id or _graph_id(task)
        self.task = task
        self.nodes: dict = {}      # node_id -> ExecutionNode
        self.created = time.time()

    def add_node(self, node: ExecutionNode):
        self.nodes[node.node_id] = node

    def get_ready_nodes(self) -> list:
        """Bagimliliklari ARTIK BEKLENMEYEN ve henuz calismamis dugumler.

        "SONUCLANMIS" = done | failed | skipped, sadece done DEGIL. Bu bilincli
        bir karar ve dogrudan main.py'nin sozlesmesinden geliyor:

        Buradaki kenarlar VERI bagimliligi degil, SIRA bariyeridir. Her
        dugumun arglari modelden hazir gelir; n3 n2'nin CIKTISINI kullanmaz,
        yalnizca n2'den SONRA calismasi gerekir (ornegin n2 ekrani okur,
        n3 tiklar). Bu yuzden n2'nin basarisiz olmasi n3'u gecersiz kilmaz.

        Eskiden yalnizca "done" kabul ediliyordu ve su SESSIZ ariza cikiyordu:
        bir salt-okunur cagri (saglayici hatasi, zaman asimi) basarisiz
        oldugunda ondan sonraki TUM dugumler asla hazir olmuyor, dongu
        "Bagimlilik cozulemedi (kilitlenme)" yoluna dusuyor ve o dugumlerin
        output'u None kaliyordu. main.py None goren yerde butun turu bastan,
        SIRAYLA calistiriyor -- yani basarili cagrilar IKINCI KEZ yurutulmus
        oluyordu. Tek bir hava durumu hatasi, butun turu iki kez calistiran
        bir yola donusuyordu.

        Simdi her dugum tam olarak BIR kez calisir; basarisiz olan da
        "❌ ..." metniyle modele ulasir ve model turu kendisi toparlar.
        """
        SETTLED = ("done", "failed", "skipped")
        ready = []
        for n in self.nodes.values():
            if n.status != "pending":
                continue
            deps_ok = True
            for d_id in n.depends_on:
                dep_node = self.nodes.get(d_id)
                if not dep_node or dep_node.status not in SETTLED:
                    deps_ok = False
                    break
            if deps_ok:
                ready.append(n)
        return ready

    def is_finished(self) -> bool:
        return all(n.status in ("done", "failed", "skipped") for n in self.nodes.values())

    def to_dict(self) -> dict:
        return {
            "graph_id": self.graph_id,
            "task": self.task,
            "node_count": len(self.nodes),
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "finished": self.is_finished(),
        }


_compiled_graphs: dict = {}  # graph_id -> ExecutionGraph

def store_graph(graph: ExecutionGraph):
    with _lock:
        _compiled_graphs[graph.graph_id] = graph
        if len(_compiled_graphs) > 100:
            oldest = min(_compiled_graphs.keys(), key=lambda k: _compiled_graphs[k].created)
            _compiled_graphs.pop(oldest, None)

def lookup_graph(task: str) -> Optional[ExecutionGraph]:
    with _lock:
        return _compiled_graphs.get(_graph_id(task))

def compile_calls_to_graph(task: str, calls: list, parallel_safe: set) -> ExecutionGraph:
    """Modelin BU turda istedigi arac cagrilarini bir DAG'a derler.

    `calls`: [(ad, arglar), ...] — modelin gercekten istedigi cagrilar.
    `parallel_safe`: main.py'nin PARALLEL_SAFE_TOOLS kumesi.

    NEDEN BOYLE, "gorev metninden tahmin" DEGIL:
    eski compile_task_to_graph gorev METNINDEN dugum uyduruyordu ve
    urettigi "execute_task" adli arac main.py'nin arac tablosunda HIC
    YOK; "find_on_screen"a da `query` argumani veriyordu, oysa gercek
    imza `element` bekliyor (main.py:1079). Yani derlenen cizge
    calistirilsa her dugum hata verirdi. Bu yuzden cizge artik
    UYDURULMUYOR: modelin zaten istedigi, adi ve argumanlari DOGRU olan
    cagrilardan kuruluyor.

    BAGIMLILIK KURALI (tek kural, bilerek basit):
      - salt-okunur (parallel_safe) cagrilar birbirine BAGLI DEGIL
        -> ayni katmanda, paralel calisirlar.
      - yan etkili bir cagri, kendisinden ONCEKI TUM dugumlere baglidir
        ve kendisinden sonrakiler de ona baglidir -> bir bariyer olur.
        Boylece "ekran goruntusu al, sonra tikla" sirasi ASLA bozulmaz.
    Bu, modelin verdigi sirayi korurken yalnizca guvenli olani paralel
    yapar; hiz kazanci sadece gercekten bagimsiz isler icin alinir.
    """
    g = ExecutionGraph(task=task)
    prev_barrier: list = []      # son yan etkili dugum (bariyer)
    since_barrier: list = []     # bariyerden sonra eklenen bagimsizlar

    for i, (name, args) in enumerate(calls):
        nid = f"n{i + 1}"
        safe = name in parallel_safe
        if safe:
            # Salt-okunur: yalnizca son bariyere bagli, kardesleriyle paralel.
            node = ExecutionNode(nid, name, args or {},
                                 depends_on=list(prev_barrier),
                                 desc=f"{name} (paralel)")
            since_barrier.append(nid)
        else:
            # Yan etkili: bariyer. Kendisinden onceki HER SEYE bagli.
            deps = list(prev_barrier) + list(since_barrier)
            node = ExecutionNode(nid, name, args or {}, depends_on=deps,
                                 desc=f"{name} (sirali)")
            prev_barrier = [nid]
            since_barrier = []
        g.add_node(node)

    _stats["graphs_compiled"] = _stats.get("graphs_compiled", 0) + 1
    store_graph(g)
    return g


def graph_would_help(calls: list, parallel_safe: set) -> bool:
    """Cizge kurmanin ISE YARAYIP yaramayacagini soyler.

    Cizge kurmak bedava degil (nesne uretimi + asyncio.gather sarmalama).
    En az IKI salt-okunur cagri ayni katmanda olmadikca hicbir sey
    kazanilmaz; o durumda cagiran taraf duz siralı yolu kullanmali.
    """
    if len(calls) < 2:
        return False
    layer = 0
    best = 0
    for name, _ in calls:
        if name in parallel_safe:
            layer += 1
            best = max(best, layer)
        else:
            layer = 0
    return best >= 2

async def execute_graph(graph: ExecutionGraph, tool_executor_async) -> dict:
    """
    Çizgeyi dinamik olarak yürütür: Hazır düğümleri tespit edip eşzamanlı (paralel) çalıştırır.
    """
    t0 = time.time()
    steps_run = 0
    layers = 0
    while not graph.is_finished():
        ready = graph.get_ready_nodes()
        if not ready:
            # Bağımlılık döngüsü veya tıkanma
            for n in graph.nodes.values():
                if n.status == "pending":
                    n.status = "failed"
                    n.error = "Bağımlılık çözülemedi (kilitlenme)"
            break

        # Bağımsız adımları paralel çalıştır
        async def _run_one(node: ExecutionNode):
            node.status = "running"
            t_node = time.time()
            try:
                node.output = await tool_executor_async(node.tool, node.args)
                node.status = "done"
            except Exception as e:
                node.status = "failed"
                node.error = str(e)
                # CAGIRAN TARAF ICIN: main.py arac sonuclarini METIN olarak
                # gecmise yaziyor ve hatalari "❌" ile ayirt ediyor. Burada
                # output'u None birakmak, hatayi modelden SAKLAMAK olurdu:
                # model aracin cagrildigini sanip bos sonucla devam ederdi.
                node.output = f"❌ {node.tool}: {e}"
            node.elapsed = time.time() - t_node

        await asyncio.gather(*[_run_one(n) for n in ready])
        steps_run += len(ready)
        layers += 1

    elapsed_tot = time.time() - t0
    # SAYAC: kac dugum ayni katmanda paralel gitti. "steps_run" dugum
    # sayisidir, katman sayisi degil; ikisinin farki asil kazanctir
    # (5 dugum / 2 katman = 3 dugum paralel gitti).
    _stats["graphs_executed"] = _stats.get("graphs_executed", 0) + 1
    _stats["graph_nodes_run"] = _stats.get("graph_nodes_run", 0) + steps_run
    _stats["graph_layers"] = _stats.get("graph_layers", 0) + layers
    return {
        "ok": all(n.status == "done" for n in graph.nodes.values() if not n.is_speculative),
        "graph_id": graph.graph_id,
        "elapsed": round(elapsed_tot, 3),
        "steps_run": steps_run,
        "layers": layers,
        "outputs": {nid: n.output for nid, n in graph.nodes.items()},
        "graph": graph.to_dict()
    }


# ─── ISTATISTIK ────────────────────────────────────────────────────────
def stats() -> dict:
    with _lock:
        d = _load()
        s = dict(_stats)
        total = s["hits"] + s["misses"]
        s["entries"] = len(d)
        s["quarantined_now"] = sum(1 for e in d.values() if e.get("quarantined"))
        s["stale_now"] = sum(1 for e in d.values()
                             if e.get("jit_version") != JIT_VERSION)
        s["hit_rate"] = round(s["hits"] / total, 4) if total else 0.0
        s["jit_version"] = JIT_VERSION
        s["max_entries"] = MAX_ENTRIES
        s["fail_limit"] = FAIL_LIMIT
        s["executor"] = "code_act_executor" if code_act_executor else None
        s["file"] = str(_JIT_FILE)
        s["compiled_graphs"] = len(_compiled_graphs)
        return s


def reset_stats() -> dict:
    """SAYAC SIFIRLA dugmesi buraya baglidir (POST /jit/stats/reset).

    Cizge sayaclari da SIFIRLANIR. Unutulursa /jit/graphs "12 cizge calisti"
    demeye devam eder, kullanici sifirladigini sanir ve panelde eski sayilari
    gorur — olcmedigimiz seyi soylememe kuralinin tersi kadar kotu: OLCTUGUMUZ
    seyi yanlis donemden soylemek.
    """
    with _lock:
        _stats.update({"hits": 0, "misses": 0, "compiles": 0, "runs": 0,
                       "failures": 0, "quarantined": 0, "llm_calls_saved": 0,
                       "stale_version": 0, "graphs_compiled": 0,
                       "graphs_executed": 0, "graph_nodes_run": 0,
                       "graph_layers": 0})
    return stats()


def info() -> dict:
    """runtime_state / UI icin kisa durum. `available` = calistirma yolu
    GERCEKTEN acik mi: code_act_executor yoksa derleme yapilabilir ama
    hicbir sey calistirilamaz, yani modul ise yaramaz durumdadir."""
    ok = code_act_executor is not None
    return {
        "available": ok,
        "note": ("Derlenen blok onay kapisindan gecerek calisir. Agint çizge derleyicisi aktif."
                 if ok else
                 "code_act_executor yuklenemedi -> JIT calistirma kapali."),
        "jit_version": JIT_VERSION,
        "max_entries": MAX_ENTRIES,
        "fail_limit": FAIL_LIMIT,
        "sim_threshold": SIM_THRESHOLD,
        "file": str(_JIT_FILE),
        "agint_graph_support": True,
    }

