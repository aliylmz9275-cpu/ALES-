"""
long_term_memory.py — ALES kalici uzun-sureli hafiza (MemoryOS yerine, ayni
fikrin ALES yiginina uyan gercek karsiligi).

Ali'nin onayladigi ikame: "MemoryOS -> sqlite-vec". MemoryOS'un kendisi 3
commit'lik, Postgres+Redis+Docker+Python 3.12 isteyen olgunlasmamis bir depo;
ALES ise Python 3.10 ve Docker'siz calisir. Bu modul ayni yetenegi
(zaman-farkindali + vektor tabanli + Ebbinghaus unutma egrili uzun sureli
hafiza) SIFIR ZORUNLU BAGIMLILIK ile, tek bir SQLite dosyasinda saglar.

Tasarim ilkeleri:
  * ASLA cokmez: sqlite-vec eklentisi de, Gemini embedding'i de OPSIYONEL.
    Ikisi de yoksa yerel (bagimliliksiz) hashing-embedding + Python kosinus
    siralamasina duser. Hicbir sey kurulu olmasa bile import + calisma tamam.
  * Ebbinghaus: her kaydin bir "guc"u vardir; zaman gectikce zayiflar, her
    hatirlanista guclenir (reinforcement). Recall skoru = benzerlik * tazelik.
  * memory.py'yi DEGISTIRMEZ, tamamlar: ayni Gemini embedding kaynagini
    (text-embedding-004) kullanir, yoksa kendi yereline duser.

Kayit semasi (SQLite `memories` tablosu):
  id, text, kind, source, importance, created_at, last_access, access_count,
  dim, embedding(JSON)
"""

import json
import math
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

# ─── DB yolu (ALES AppData ile ayni yer) ────────────────────────────
try:
    from config_manager import APPDATA
    DB_PATH = APPDATA / "ltm.db"
except Exception:
    DB_PATH = Path("ltm.db")

# retry_util SAVUNMACI import edilir: yoksa embedding tek denemede yapilir,
# modul yine calisir.
try:
    import retry_util
except Exception:
    retry_util = None

_LOCAL_DIM = 256          # yerel hashing-embedding boyutu
_TAU_DAYS = 30.0          # Ebbinghaus zaman sabiti (gun) — buyukse yavas unutur
_conn = None
_vec_ok = False           # sqlite-vec eklentisi yuklendi mi?
_gemini_dim = None        # Gemini embedding boyutu (ilk kullanimda ogrenilir)
_gemini_down = False      # Gemini bir kez dustuyse bu surecte TEKRAR DENENMEZ

# ─── sqlite-vec KNN durumu ──────────────────────────────────────────
# ESKIDEN: _connect() sqlite_vec.load() cagirip _vec_ok = True yapiyordu ama
# TEK BIR vec0 tablosu olusturmuyor, TEK BIR KNN sorgusu atmiyordu. Yani
# eklenti yukleniyor sonra tamamen goz ardi ediliyordu; her recall() TUM
# tabloyu Python'da tariyordu (O(n) kosinus). Asagidaki mekanizma eklentiyi
# gercekten kullanir.
#
# NEDEN BOYUT BASINA AYRI TABLO: vec0 sanal tablosunda vektor boyutu
# OLUSTURMA aninda sabitlenir (float[768] gibi) ve sonradan degistirilemez.
# ALES iki uzay kullanabiliyor (Gemini 768 / yerel 256), bu yuzden
# mem_vec_768 ve mem_vec_256 ayri tablolardir. Boyut karisik DB'lerde bu
# kendiliginden dogru davranir.
_vec_tables = {}          # dim -> {"table": ad, "metric": "cosine"|"l2"}
_vec_serialize = None     # sqlite_vec.serialize_float32 (varsa)
VEC_OVERFETCH = 6         # KNN'den k*6 aday cek, sonra Python'da yeniden sirala
VEC_MIN_FETCH = 30


# ─── Embedding ───────────────────────────────────────────────────────
def _local_embed(text: str) -> list:
    """Bagimliliksiz, deterministik hashing bag-of-words embedding. Gemini
    yoksa devreye girer. semantic_cache'teki mantikla ayni ruh: kelime ->
    sabit boyutlu vektor; L2 normalize. Turkce icin kucuk harf guvenli."""
    vec = [0.0] * _LOCAL_DIM
    if not text:
        return vec
    for raw in text.lower().split():
        w = "".join(ch for ch in raw if ch.isalnum())
        if not w:
            continue
        h = 0
        for ch in w:
            h = (h * 31 + ord(ch)) & 0xFFFFFFFF
        vec[h % _LOCAL_DIM] += 1.0
    n = math.sqrt(sum(x * x for x in vec))
    return [x / n for x in vec] if n else vec


def _gemini_embed(text: str):
    """Gemini text-embedding-004 ile embedding; key yoksa/hata olursa None.

    GECICI hatalar (429/503/ag kopmasi) icin retry_util ile KISA bir yeniden
    deneme yapilir. Sebep: _embed ilk basarisizlikta yerel embedder'a
    KILITLENIR; tek bir anlik blip yuzunden butun oturumun anlamsal kalitesini
    dusurmek istemeyiz. Gecikme bilincli kucuk tutulur (bu cagri istek
    yolundadir): 2 deneme, ~0.3s geri-alim, en fazla 1s."""
    try:
        from config_manager import load_config
        key = ((load_config() or {}).get("gemini_key") or "").strip()
        if not key:
            return None
        from google import genai
        client = genai.Client(api_key=key)

        def _once():
            res = client.models.embed_content(
                model="gemini-embedding-2",
                contents=text[:2000],
            )
            return res.embeddings[0].values

        emb = (retry_util.retry(_once, attempts=2, base_s=0.3, max_s=1.0,
                                label="ltm.embed")
               if retry_util else _once())
        global _gemini_dim
        _gemini_dim = len(emb)
        return list(emb)
    except Exception:
        return None


def _embed(text: str) -> list:
    """Once Gemini (anlamsal, esanlamli-farkindali), yoksa yerel.

    ONEMLI — EMBEDDING UZAYI SUREC BOYUNCA SABITTIR. Eski hali her cagride
    Gemini'yi yeniden deniyordu; Gemini calisirken tek bir cagri (kota, ag
    hatasi, 429) patlarsa AYNI veritabanina 768 boyutlu ve 256 boyutlu
    vektorler yaziliyordu. recall() farkli boyuttaki kayitlari atlar (dogru
    davranis — kosinus ancak ayni uzayda anlamlidir), dolayisiyla o kayitlar
    SESSIZCE hatirlanamaz hale geliyordu: hata yok, log yok, sadece bos
    sonuc. Artik ilk basarisizlikta yerel embedder'a KILITLENIR; boylece bir
    oturumda uretilen tum vektorler ayni uzayda olur."""
    global _gemini_down
    if not _gemini_down:
        g = _gemini_embed(text)
        if g is not None:
            return g
        _gemini_down = True
        print("[LTM] Gemini embedding kullanilamadi -> bu oturum boyunca "
              f"yerel {_LOCAL_DIM}-boyutlu embedder kullanilacak.")
    return _local_embed(text)


def _cosine(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


# ─── Baglanti / sema ─────────────────────────────────────────────────
def _connect():
    global _conn, _vec_ok, _vec_serialize
    if _conn is not None:
        return _conn
    _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            text         TEXT NOT NULL,
            kind         TEXT DEFAULT 'note',
            source       TEXT DEFAULT '',
            importance   REAL DEFAULT 1.0,
            created_at   REAL,
            last_access  REAL,
            access_count INTEGER DEFAULT 0,
            dim          INTEGER,
            embedding    TEXT
        )
    """)
    _conn.commit()
    # sqlite-vec OPSIYONEL — Windows stdlib sqlite3 cogu zaman eklenti
    # yuklemeyi desteklemez; desteklemezse sessizce Python kosinusa duseriz.
    try:
        import sqlite_vec  # type: ignore
        _conn.enable_load_extension(True)
        sqlite_vec.load(_conn)
        _conn.enable_load_extension(False)
        _vec_ok = True
        _vec_serialize = getattr(sqlite_vec, "serialize_float32", None)
    except Exception:
        _vec_ok = False
    if _vec_ok:
        # Var olan vec0 tablolarini kesfet (onceki oturumlardan kalanlar).
        try:
            for (nm,) in _conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name LIKE 'mem_vec_%'").fetchall():
                try:
                    d = int(str(nm).rsplit("_", 1)[-1])
                except Exception:
                    continue
                _vec_tables.setdefault(d, {"table": nm, "metric": _vec_metric_of(nm)})
        except Exception:
            pass
    return _conn


def _vec_metric_of(table: str) -> str:
    """Tablonun hangi mesafe metrigiyle olusturuldugunu SQL'inden oku.

    Metrigi bilmek sart: kosinus mesafesinde benzerlik = 1 - d, L2'de ise
    (normalize vektorler icin) 1 - d^2/2. Yanlis formul skorlari sessizce
    bozar ve min_score esigi anlamsizlasir.
    """
    try:
        row = _conn.execute("SELECT sql FROM sqlite_master WHERE name = ?",
                            (table,)).fetchone()
        sql = (row[0] or "") if row else ""
        return "cosine" if "cosine" in sql.lower() else "l2"
    except Exception:
        return "l2"


def _ensure_vec_table(dim: int):
    """dim boyutu icin vec0 tablosunu garanti et. sqlite-vec yoksa None.

    Kosinus metrigiyle denenir; eski bir sqlite-vec surumu distance_metric
    sozdizimini bilmiyorsa duz (L2) tabloya duseriz — ikisi de dogru sonuc
    verir, sadece donusum formulu farklidir.
    """
    if not _vec_ok or not dim:
        return None
    info = _vec_tables.get(dim)
    if info:
        return info
    conn = _conn
    name = f"mem_vec_{int(dim)}"
    for metric, ddl in (
        ("cosine", f"CREATE VIRTUAL TABLE IF NOT EXISTS {name} USING vec0("
                   f"embedding float[{int(dim)}] distance_metric=cosine)"),
        ("l2", f"CREATE VIRTUAL TABLE IF NOT EXISTS {name} USING vec0("
               f"embedding float[{int(dim)}])"),
    ):
        try:
            conn.execute(ddl)
            conn.commit()
            info = {"table": name, "metric": metric}
            _vec_tables[dim] = info
            return info
        except Exception:
            continue
    return None


def _vec_value(emb: list):
    """Vektoru vec0'un kabul ettigi bicime cevir. serialize_float32 varsa
    blob (daha kucuk/hizli), yoksa JSON metni — vec0 ikisini de kabul eder."""
    if callable(_vec_serialize):
        try:
            return _vec_serialize(emb)
        except Exception:
            pass
    return json.dumps(emb)


def _vec_put(mid: int, emb: list) -> bool:
    """Bir aniyi KNN indeksine yaz. Basarisizlik SESSIZ ve ZARARSIZ:
    indeks eksik kalirsa recall() Python kosinus yoluna duser."""
    info = _ensure_vec_table(len(emb))
    if not info:
        return False
    try:
        _conn.execute(f"INSERT OR REPLACE INTO {info['table']}(rowid, embedding) "
                      f"VALUES (?, ?)", (int(mid), _vec_value(emb)))
        _conn.commit()
        return True
    except Exception:
        return False


def _vec_delete(ids) -> int:
    """Silinen anilari indeksten de dusur.

    ONEMLI: bu yapilmazsa KNN olu rowid'ler dondurur; JOIN onlari eler ama
    k adet sonuc isterken bazilari bos cikar ve recall sessizce eksik
    sonuc verir. Yani bu temizlik dogruluk meselesi, kozmetik degil.
    """
    if not _vec_ok or not ids:
        return 0
    n = 0
    for info in list(_vec_tables.values()):
        try:
            _conn.executemany(f"DELETE FROM {info['table']} WHERE rowid = ?",
                              [(int(i),) for i in ids])
            n += 1
        except Exception:
            continue
    try:
        _conn.commit()
    except Exception:
        pass
    return n


def _now() -> float:
    return time.time()


# ─── Ebbinghaus tazelik ──────────────────────────────────────────────
def _freshness(last_access: float, access_count: int) -> float:
    """Unutma egrisi: son erisimden bu yana gecen sureyle ussel azalir, ama
    sik hatirlanan (access_count yuksek) kayitlar daha yavas unutulur —
    tekrar = pekistirme. 0..~1.3 araligi dondurur."""
    elapsed_days = max(0.0, (_now() - (last_access or _now())) / 86400.0)
    tau = _TAU_DAYS * (1.0 + math.log1p(max(0, access_count)))
    return math.exp(-elapsed_days / tau)


# ─── Genel API ───────────────────────────────────────────────────────
def _sync_to_memory_json(entry: dict):
    r"""Her uzun süreli anıyı %APPDATA%\ALES\memory.json dosyasına da kalıcı olarak yazar."""
    try:
        from config_manager import load_memory, save_memory
        mem = load_memory()
        mem.setdefault("long_term", [])
        existing = next((item for item in mem["long_term"] if item.get("text") == entry.get("text")), None)
        if existing:
            existing.update(entry)
        else:
            mem["long_term"].append(entry)
        if len(mem["long_term"]) > 500:
            mem["long_term"] = mem["long_term"][-500:]
        save_memory(mem)
    except Exception as e:
        try:
            from config_manager import APPDATA
            p = APPDATA / "memory.json"
            data = {}
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            data.setdefault("long_term", [])
            data["long_term"].append(entry)
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


def add(text: str, kind: str = "note", source: str = "", importance: float = 1.0) -> dict:
    """Yeni bir uzun-sureli ani kaydet. Ayni metin varsa tekrar yazmaz,
    onun yerine pekistirir (access_count++). Hem SQLite'a hem %APPDATA%\\ALES\\memory.json'a yazar."""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "bos metin"}
    conn = _connect()
    row = conn.execute("SELECT id, access_count FROM memories WHERE text = ?", (text,)).fetchone()
    if row:
        conn.execute(
            "UPDATE memories SET last_access = ?, access_count = access_count + 1, importance = MAX(importance, ?) WHERE id = ?",
            (_now(), float(importance), row[0]),
        )
        conn.commit()
        _sync_to_memory_json({
            "id": row[0], "text": text, "kind": kind, "source": source,
            "importance": float(importance), "updated_at": datetime.now(timezone.utc).isoformat(),
            "reinforced": True
        })
        return {"ok": True, "id": row[0], "reinforced": True}
    emb = _embed(text)
    cur = conn.execute(
        "INSERT INTO memories (text, kind, source, importance, created_at, last_access, access_count, dim, embedding) VALUES (?,?,?,?,?,?,?,?,?)",
        (text, kind, source, float(importance), _now(), _now(), 0, len(emb), json.dumps(emb)),
    )
    conn.commit()
    mid = cur.lastrowid
    # Vektor indeksine de yaz. embedding kolonu KALIYOR (indeks yoksa/
    # bozulursa Python kosinus yolu ondan calisir) — indeks bir hizlandirma,
    # tek gercek kaynak degil.
    indexed = _vec_put(mid, emb)
    _sync_to_memory_json({
        "id": mid, "text": text, "kind": kind, "source": source,
        "importance": float(importance), "created_at": datetime.now(timezone.utc).isoformat(),
        "reinforced": False
    })
    return {"ok": True, "id": mid, "reinforced": False, "indexed": indexed}


def _sim_from_distance(d: float, metric: str) -> float:
    """vec0 MESAFE dondurur, biz BENZERLIK istiyoruz.

    cosine: d = 1 - kosinus  ->  sim = 1 - d
    l2:     normalize vektorlerde |a-b|^2 = 2(1-cos) -> sim = 1 - d^2/2
    Metrigi karistirmak skorlari sessizce bozar; bu yuzden metrik tablo
    SQL'inden okunuyor (_vec_metric_of), varsayilmiyor.
    """
    try:
        d = float(d)
    except Exception:
        return 0.0
    if metric == "cosine":
        return 1.0 - d
    return 1.0 - (d * d) / 2.0


def _knn_candidates(q_emb: list, want: int) -> list:
    """sqlite-vec ile en yakin `want` adayi getir.

    Doner: [(sim, row...)] veya None -> arayan Python kosinus yoluna duser.
    Bu fonksiyon HICBIR ZAMAN raise etmez: vektor indeksi bir hizlandirma,
    hafizanin calismasinin ON KOSULU degil.
    """
    if not _vec_ok:
        return None
    info = _vec_tables.get(len(q_emb)) or _ensure_vec_table(len(q_emb))
    if not info:
        return None
    try:
        rows = _conn.execute(
            f"""SELECT m.id, m.text, m.kind, m.source, m.importance,
                       m.created_at, m.last_access, m.access_count, m.dim,
                       v.distance
                  FROM {info['table']} v
                  JOIN memories m ON m.id = v.rowid
                 WHERE v.embedding MATCH ? AND k = ?
                 ORDER BY v.distance""",
            (_vec_value(q_emb), int(want)),
        ).fetchall()
    except Exception:
        # Eski sqlite-vec surumlerinde "k = ?" yerine LIMIT kullanilir.
        try:
            rows = _conn.execute(
                f"""SELECT m.id, m.text, m.kind, m.source, m.importance,
                           m.created_at, m.last_access, m.access_count, m.dim,
                           v.distance
                      FROM {info['table']} v
                      JOIN memories m ON m.id = v.rowid
                     WHERE v.embedding MATCH ?
                     ORDER BY v.distance LIMIT ?""",
                (_vec_value(q_emb), int(want)),
            ).fetchall()
        except Exception:
            return None
    metric = info.get("metric", "l2")
    out = []
    for r in rows:
        if r[8] != len(q_emb):      # boyut uyusmazligi: farkli uzay, atla
            continue
        out.append((_sim_from_distance(r[9], metric),) + tuple(r[:9]))
    return out


def recall(query: str, k: int = 5, min_score: float = 0.15, reinforce: bool = True,
           within_days: float = None, kind: str = None) -> list:
    """Sorguya en yakin k aniyi getir. Skor = kosinus_benzerlik * tazelik *
    onem. Getirilen kayitlar pekistirilir (Ebbinghaus: hatirlamak guclendirir).
    Dondurur: [{id,text,kind,source,score,similarity,created_at,...}].

    within_days: verilirse sadece bu kadar gun icinde OLUSTURULMUS anilar
                 (zamansal geri cagirma — "gecen hafta ne konusmustuk").
    kind:        verilirse sadece bu turden anilar.

    HIZ: sqlite-vec varsa aday kumesi vec0 KNN ile secilir (tum tabloyu
    Python'da taramak yerine), sonra Ebbinghaus tazeligi + onem ile YENIDEN
    SIRALANIR. Yeniden siralama sart: KNN yalnizca vektor mesafesini bilir,
    ALES'in hafiza semantigi ise tazelik ve onemi de icerir. Bu yuzden
    k*VEC_OVERFETCH aday cekip nihai sirayi Python'da veriyoruz.
    """
    query = (query or "").strip()
    if not query:
        return []
    conn = _connect()
    q_emb = _embed(query)
    q_dim = len(q_emb)
    used_index = False
    rows = None

    # ── 1) Hizli yol: vec0 KNN ────────────────────────────────────
    want = max(VEC_MIN_FETCH, int(k) * VEC_OVERFETCH)
    cand = _knn_candidates(q_emb, want)
    if cand:
        used_index = True
        scored = []
        for (sim, mid, text, kd, source, importance, created_at,
             last_access, access_count, _dim) in cand:
            if sim <= 0:
                continue
            score = sim * _freshness(last_access, access_count) * max(0.1, float(importance or 1.0))
            scored.append((score, sim, mid, text, kd, source, created_at, access_count))
    else:
        # ── 2) Yedek yol: tum tabloyu Python'da tara ───────────────
        rows = conn.execute(
            "SELECT id, text, kind, source, importance, created_at, last_access, access_count, dim, embedding FROM memories"
        ).fetchall()

        # ESKI/KARISIK VERITABANI KURTARMASI: bu surecte Gemini calisiyor olabilir
        # ama DB'deki kayitlar onceki bir oturumda yerel uzayda yazilmis olabilir.
        # O durumda asagidaki dongu HER kaydi atlar ve fonksiyon sessizce bos
        # doner. Sorgu boyutunda TEK bir kayit bile yoksa sorguyu yerel uzayda
        # yeniden gomup oradaki kayitlarla karsilastiriyoruz — _local_embed
        # deterministik ve bagimliliksiz oldugundan bu her zaman calisir.
        if rows and not any(r[8] == q_dim for r in rows):
            if any(r[8] == _LOCAL_DIM for r in rows):
                q_emb = _local_embed(query)
                q_dim = _LOCAL_DIM

        scored = []
        for (mid, text, kd, source, importance, created_at, last_access, access_count, dim, emb_json) in rows:
            # Boyut uyusmazligi (Gemini<->yerel gecisi) olursa ayni uzayda
            # yeniden embed etmek yerine bu kaydi guvenle atla.
            if dim != q_dim:
                continue
            try:
                emb = json.loads(emb_json)
            except Exception:
                continue
            sim = _cosine(q_emb, emb)
            if sim <= 0:
                continue
            score = sim * _freshness(last_access, access_count) * max(0.1, float(importance or 1.0))
            scored.append((score, sim, mid, text, kd, source, created_at, access_count))

    # ── Zamansal / tur filtresi ───────────────────────────────────
    if within_days:
        try:
            cutoff = _now() - float(within_days) * 86400.0
            scored = [s for s in scored if (s[6] or 0) >= cutoff]
        except Exception:
            pass
    if kind:
        scored = [s for s in scored if s[4] == kind]

    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    hit_ids = []
    for (score, sim, mid, text, kd, source, created_at, access_count) in scored[:k]:
        if score < min_score:
            continue
        out.append({
            "id": mid, "text": text, "kind": kd, "source": source,
            "score": round(score, 4), "similarity": round(sim, 4),
            "created_at": datetime.fromtimestamp(created_at or 0).isoformat(),
            "access_count": access_count,
            "via": "vector_index" if used_index else "python_cosine",
        })
        hit_ids.append(mid)
    if reinforce and hit_ids:
        conn.executemany(
            "UPDATE memories SET last_access = ?, access_count = access_count + 1 WHERE id = ?",
            [(_now(), mid) for mid in hit_ids],
        )
        conn.commit()
    return out


def forget_stale(min_freshness: float = 0.02, keep_important: float = 3.0) -> int:
    """Ebbinghaus: cok zayiflamis (uzun suredir hatirlanmamis) ve onemsiz
    anilari temizle. importance >= keep_important olanlar korunur. Silinen
    kayit sayisini dondurur."""
    conn = _connect()
    rows = conn.execute(
        "SELECT id, last_access, access_count, importance FROM memories"
    ).fetchall()
    doomed = [
        mid for (mid, last_access, access_count, importance) in rows
        if float(importance or 1.0) < keep_important
        and _freshness(last_access, access_count) < min_freshness
    ]
    if doomed:
        conn.executemany("DELETE FROM memories WHERE id = ?", [(mid,) for mid in doomed])
        conn.commit()
        # Vektor indeksinden de dus — yoksa KNN olu rowid dondurur ve
        # recall() sessizce eksik sonuc verir (bkz. _vec_delete).
        _vec_delete(doomed)
    return len(doomed)


def recall_recent(k: int = 5, kind: str = None, within_days: float = 7.0) -> list:
    """Zamansal geri cagirma: son N gunun anilari, benzerlik sorgusu OLMADAN.

    "Bu hafta ne uzerinde calistik" gibi sorular icin; vektor benzerligi
    burada anlamsiz, sira TAZELIK * ONEM.
    """
    conn = _connect()
    cutoff = _now() - max(0.01, float(within_days or 7.0)) * 86400.0
    q = ("SELECT id, text, kind, source, importance, created_at, last_access, "
         "access_count FROM memories WHERE created_at >= ?")
    args = [cutoff]
    if kind:
        q += " AND kind = ?"
        args.append(kind)
    rows = conn.execute(q, tuple(args)).fetchall()
    scored = []
    for (mid, text, kd, source, importance, created_at, last_access, ac) in rows:
        score = _freshness(last_access, ac) * max(0.1, float(importance or 1.0))
        scored.append((score, mid, text, kd, source, created_at, ac))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"id": m, "text": t, "kind": kd, "source": s,
             "score": round(sc, 4),
             "created_at": datetime.fromtimestamp(c or 0).isoformat(),
             "access_count": ac, "via": "temporal"}
            for (sc, m, t, kd, s, c, ac) in scored[:max(1, int(k))]]


def rebuild_vector_index() -> dict:
    """Vektor indeksini `memories` tablosundan bastan kur.

    NEDEN GEREKLI: sqlite-vec sonradan kuruldugunda (veya bu surum
    yuklendiginde) mevcut anilarin HICBIRI indekste degildir; o zamana kadar
    yazilan her sey yalnizca `embedding` kolonunda durur. Bu fonksiyon
    kaldigi yerden degil, SIFIRDAN kurar — yarim indeks yanlis KNN demek.
    Indeks yoksa recall() zaten Python kosinusa duser, yani bu bir
    HIZLANDIRMA islemidir, veri tasima islemi degil.
    """
    conn = _connect()
    if not _vec_ok:
        return {"ok": False, "error": "sqlite-vec kurulu degil (pip install sqlite-vec)",
                "indexed": 0}
    # Once mevcut tablolari bosalt.
    for info in list(_vec_tables.values()):
        try:
            conn.execute(f"DELETE FROM {info['table']}")
        except Exception:
            pass
    conn.commit()
    ok = 0
    fail = 0
    for (mid, dim, emb_json) in conn.execute(
            "SELECT id, dim, embedding FROM memories").fetchall():
        try:
            emb = json.loads(emb_json)
        except Exception:
            fail += 1
            continue
        if not emb or len(emb) != (dim or len(emb)):
            fail += 1
            continue
        if _vec_put(mid, emb):
            ok += 1
        else:
            fail += 1
    return {"ok": True, "indexed": ok, "failed": fail,
            "tables": {str(d): v["table"] for d, v in _vec_tables.items()}}


def vector_info() -> dict:
    """Vektor indeksinin GERCEK durumu: kurulu mu, dolu mu, yeniden kurulmali mi."""
    conn = _connect()
    total = 0
    try:
        total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    except Exception:
        pass
    tables = []
    indexed_total = 0
    for d, info in _vec_tables.items():
        n = None
        try:
            n = conn.execute(f"SELECT COUNT(*) FROM {info['table']}").fetchone()[0]
            indexed_total += int(n or 0)
        except Exception:
            pass
        tables.append({"dim": d, "table": info["table"],
                       "metric": info.get("metric"), "rows": n})
    return {
        "extension_loaded": _vec_ok,
        "serializer": "blob" if callable(_vec_serialize) else "json",
        "tables": tables,
        "memories": total,
        "indexed": indexed_total,
        "needs_rebuild": bool(_vec_ok and total and indexed_total < total),
        "overfetch": VEC_OVERFETCH,
        "install_hint": "" if _vec_ok else "pip install sqlite-vec",
        "note": ("Indeks yoksa geri cagirma calismaya devam eder (Python "
                 "kosinus, tum tabloyu tarar) — sadece daha yavastir."),
    }


def stats() -> dict:
    conn = _connect()
    total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    by_kind = {}
    for kind, c in conn.execute("SELECT kind, COUNT(*) FROM memories GROUP BY kind").fetchall():
        by_kind[kind] = c
    # Kayitli vektor boyutlari: birden fazlaysa DB karisiktir (eski oturumlar
    # farkli uzayda yazmis). Artik sessiz kalmiyor, UI'da gorunuyor.
    dims = {}
    try:
        for d, c in conn.execute("SELECT dim, COUNT(*) FROM memories GROUP BY dim").fetchall():
            dims[str(d)] = c
    except Exception:
        pass
    if _gemini_down or not _gemini_dim:
        active = "local"
    else:
        active = "gemini"
    return {
        "total": total,
        "by_kind": by_kind,
        "vec_extension": _vec_ok,
        # "embedding" surecte SU AN kullanilan uzay. _gemini_dim dolu olsa bile
        # Gemini dustuyse (latch) dogru cevap "local"dir — eski hali burada
        # "gemini" diyip yaniltiyordu.
        "embedding": active,
        "gemini_down": _gemini_down,
        "dims": dims,
        "mixed_dims": len(dims) > 1,
        "db_path": str(DB_PATH),
        # Vektor indeksi ayri bir alt sozlukte: "vec_extension: true" tek
        # basina indeksin DOLU oldugunu gostermiyordu (eskiden uzanti
        # yukleniyor ama hicbir tablo kurulmuyordu).
        "vector": _safe_vector_info(),
    }


def _safe_vector_info() -> dict:
    try:
        return vector_info()
    except Exception as e:
        return {"extension_loaded": _vec_ok, "error": str(e)}
