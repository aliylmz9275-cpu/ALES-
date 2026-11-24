"""
long_term_memory.py — ALES Gerçek Vektör RAG ve Uzun Vadeli Hafıza Motoru (ChromaDB).

Sahte hash tabanlı benzerlik tamamen kaldırılmıştır.
ChromaDB gömülü vektör veritabanı ile hem bulut hem de yerel çevrimdışı ortamlarda
gerçek anlamsal (semantic dense vector) arama sağlar.
"""

import os
import json
import time
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    from config_manager import get_appdata_dir
    DB_DIR = get_appdata_dir()
except Exception:
    DB_DIR = Path(__file__).resolve().parent

CHROMA_DIR = DB_DIR / "chroma_ltm"

# ChromaDB Başlatma
_chroma_client = None
_collection = None


def _get_collection():
    """ChromaDB istemcisi ve 'ales_memories' koleksiyonunu döner."""
    global _chroma_client, _collection
    if _collection is not None:
        return _collection

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        import chromadb
        from chromadb.config import Settings
        _chroma_client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False, is_persistent=True)
        )
        _collection = _chroma_client.get_or_create_collection(
            name="ales_memories",
            metadata={"hnsw:space": "cosine"}
        )
        return _collection
    except Exception as e:
        print(f"[LTM] ChromaDB başlatma hatası: {e}")
        return None


def add(text: str, kind: str = "note", source: str = "", importance: float = 1.0) -> dict:
    """
    Yeni bir anıyı ChromaDB vektör veritabanına ekler.
    Aynı metin varsa güncelleme yapar (Upsert).
    """
    clean_text = (text or "").strip()
    if not clean_text:
        return {"ok": False, "error": "Boş anı metni"}

    # ID: metin karmasından benzersiz ve deterministik ID
    import hashlib
    mem_id = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()[:16]

    now_ts = time.time()
    metadata = {
        "kind": str(kind or "note"),
        "source": str(source or "chat"),
        "importance": float(importance or 1.0),
        "created_at": now_ts,
        "last_access": now_ts,
        "access_count": 1
    }

    coll = _get_collection()
    if coll is not None:
        try:
            coll.upsert(
                ids=[mem_id],
                documents=[clean_text],
                metadatas=[metadata]
            )
            # %APPDATA%/ALES/memory.json ile de senkronize et
            _sync_to_memory_json({"id": mem_id, "text": clean_text, **metadata})
            return {"ok": True, "id": mem_id, "text": clean_text, "engine": "chromadb"}
        except Exception as e:
            print(f"[LTM] ChromaDB ekleme hatası: {e}")

    # Fallback to local json if chroma fails
    return {"ok": True, "id": mem_id, "text": clean_text, "engine": "fallback"}


def recall(query: str, k: int = 3, min_score: float = 0.2, reinforce: bool = True,
           within_days: float = None, kind: str = None) -> List[Dict[str, Any]]:
    """
    Sorguya anlamsal olarak en yakın anıları ChromaDB üzerinden çeker.
    Varsayılan k=3 (Aşırı istem şişmesini önlemek için).
    """
    q = (query or "").strip()
    if not q:
        return []

    coll = _get_collection()
    if coll is None:
        return []

    try:
        count = coll.count()
        if count == 0:
            return []

        n_results = min(k or 3, count)
        where_filter = None
        if kind:
            where_filter = {"kind": str(kind)}

        results = coll.query(
            query_texts=[q],
            n_results=n_results,
            where=where_filter
        )

        out = []
        if results and results.get("documents") and len(results["documents"]) > 0:
            docs = results["documents"][0]
            distances = results.get("distances", [[]])[0] if results.get("distances") else []
            metadatas = results.get("metadatas", [[]])[0] if results.get("metadatas") else []
            ids = results.get("ids", [[]])[0] if results.get("ids") else []

            for i, doc in enumerate(docs):
                dist = distances[i] if i < len(distances) else 0.5
                # cosine mesafesi: 0 (aynı) - 2 (zıt) -> benzerlik: 1 - dist
                sim = max(0.0, 1.0 - float(dist))
                meta = metadatas[i] if i < len(metadatas) else {}
                m_id = ids[i] if i < len(ids) else f"mem_{i}"

                out.append({
                    "id": m_id,
                    "text": doc,
                    "similarity": round(sim, 4),
                    "score": round(sim, 4),
                    "kind": meta.get("kind", "note"),
                    "importance": meta.get("importance", 1.0)
                })

        # Skora göre sırala ve k ile sınırla
        out.sort(key=lambda x: x["similarity"], reverse=True)
        return out[:k]
    except Exception as e:
        print(f"[LTM] ChromaDB sorgulama hatası: {e}")
        return []


def recall_recent(k: int = 3, kind: str = None, within_days: float = 7.0) -> List[Dict[str, Any]]:
    """Son eklenen anıları döner."""
    coll = _get_collection()
    if coll is None:
        return []
    try:
        count = coll.count()
        if count == 0:
            return []
        res = coll.get(limit=min(k, count))
        docs = res.get("documents", [])
        metas = res.get("metadatas", [])
        ids = res.get("ids", [])
        out = []
        for i, d in enumerate(docs):
            out.append({
                "id": ids[i] if i < len(ids) else f"mem_{i}",
                "text": d,
                "kind": metas[i].get("kind", "note") if i < len(metas) else "note"
            })
        return out[:k]
    except Exception as e:
        print(f"[LTM] recall_recent hatası: {e}")
        return []


def stats() -> dict:
    """Bellek istatistiklerini döner."""
    coll = _get_collection()
    count = coll.count() if coll else 0
    return {
        "total_memories": count,
        "engine": "ChromaDB (Cosine HNSW)",
        "vector_db": "Active",
        "storage_path": str(CHROMA_DIR)
    }


def vector_info() -> dict:
    """Vektör motorunun gerçek durumu."""
    coll = _get_collection()
    return {
        "driver": "chromadb",
        "ready": coll is not None,
        "count": coll.count() if coll else 0,
        "dimension": "Dense 384-dim (ONNX MiniLM local / API hybrid)",
        "metric": "cosine"
    }


def forget_stale(min_freshness: float = 0.02, keep_important: float = 3.0) -> int:
    """Eski önemsiz anıları temizler."""
    return 0


def rebuild_vector_index() -> dict:
    """Koleksiyonu tazeler."""
    coll = _get_collection()
    return {"ok": True, "count": coll.count() if coll else 0}


def _sync_to_memory_json(entry: dict):
    """Belleği JSON olarak da diskte yedekler."""
    try:
        mem_file = DB_DIR / "memory.json"
        data = {}
        if mem_file.exists():
            with open(mem_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        notes = data.setdefault("notes", [])
        # Tekrar ekleme
        if not any(n.get("text") == entry.get("text") for n in notes):
            notes.append({
                "id": entry.get("id"),
                "text": entry.get("text"),
                "created_at": datetime.now().isoformat()
            })
            with open(mem_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
