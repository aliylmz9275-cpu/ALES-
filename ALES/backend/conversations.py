"""
ALES Sohbet Gecmisi Yonetimi

Her sohbet ayri bir JSON dosyasi olarak
AppData/Roaming/ALES/conversations/{id}.json icinde saklanir.
Boylece Ali onceki bir sohbete tikladiginda kaldigi yerden
devam edebilir (Claude/ChatGPT arayuzlerindeki gibi).
"""
import json
import re
import uuid
from datetime import datetime
from pathlib import Path

try:
    from config_manager import APPDATA
except Exception:
    APPDATA = Path(".")

CONV_DIR = APPDATA / "conversations"
CONV_DIR.mkdir(parents=True, exist_ok=True)

MAX_MESSAGES_KEPT = 200  # tek sohbette saklanan mesaj siniri (dosya sismesin)


def _path(conv_id: str) -> Path:
    return CONV_DIR / f"{conv_id}.json"


def _title_from_text(text: str) -> str:
    text = " ".join(text.strip().split())
    return (text[:42] + "…") if len(text) > 42 else (text or "Yeni Sohbet")


def create_conversation(first_message: str = "") -> dict:
    conv_id = uuid.uuid4().hex[:12]
    now = datetime.now().isoformat()
    conv = {
        "id": conv_id,
        "title": _title_from_text(first_message) if first_message else "Yeni Sohbet",
        "created": now,
        "updated": now,
        "messages": [],
    }
    _path(conv_id).write_text(json.dumps(conv, ensure_ascii=False, indent=2), encoding="utf-8")
    return conv


def get_conversation(conv_id: str) -> dict | None:
    p = _path(conv_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def append_message(conv_id: str, role: str, content: str) -> None:
    conv = get_conversation(conv_id)
    if conv is None:
        conv = create_conversation(content if role == "user" else "")
        conv_id = conv["id"]
    conv["messages"].append({"role": role, "content": content, "time": datetime.now().isoformat()})
    if len(conv["messages"]) > MAX_MESSAGES_KEPT:
        conv["messages"] = conv["messages"][-MAX_MESSAGES_KEPT:]
    # Ilk kullanici mesajindan otomatik baslik uret
    if conv["title"] == "Yeni Sohbet" and role == "user":
        conv["title"] = _title_from_text(content)
    conv["updated"] = datetime.now().isoformat()
    _path(conv_id).write_text(json.dumps(conv, ensure_ascii=False, indent=2), encoding="utf-8")


def get_history_for_model(conv_id: str, limit: int = 20) -> list:
    conv = get_conversation(conv_id)
    if not conv:
        return []
    return [{"role": m["role"], "content": m["content"]} for m in conv["messages"][-limit:]]


def get_or_create(conv_id: str, title: str = "Sohbet") -> dict:
    conv = get_conversation(conv_id)
    if conv:
        return conv
    now = datetime.now().isoformat()
    conv = {"id": conv_id, "title": title, "created": now, "updated": now, "messages": []}
    _path(conv_id).write_text(json.dumps(conv, ensure_ascii=False, indent=2), encoding="utf-8")
    return conv


def list_conversations() -> list:
    items = []
    for f in CONV_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            last = data["messages"][-1]["content"] if data.get("messages") else ""
            items.append({
                "id": data["id"],
                "title": data.get("title", "Sohbet"),
                "updated": data.get("updated", ""),
                "preview": (last[:60] + "…") if len(last) > 60 else last,
            })
        except Exception:
            continue
    items.sort(key=lambda x: x["updated"], reverse=True)
    return items


def search_all_conversations(query: str, limit: int = 20) -> list:
    """UZUN SURELI HAFIZA: sadece aktif sohbetin son birkac mesaji degil,
    diskteki TUM gecmis sohbetleri tarar. Basit ama etkili bir anahtar
    kelime skorlamasi kullanir (kac farkli sorgu kelimesi eslesti); asil
    'anlamsal' (semantic) yeniden siralama memory.py'de - gemini_key
    varsa - bu sonuclarin uzerine bindiriliyor."""
    query_words = set(w for w in re.findall(r'\w+', query.lower(), re.UNICODE) if len(w) > 2)
    if not query_words:
        return []
    results = []
    for f in CONV_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        title = data.get("title", "Sohbet")
        for m in data.get("messages", []):
            content = m.get("content", "") or ""
            if not content:
                continue
            content_lower = content.lower()
            score = sum(1 for w in query_words if w in content_lower)
            if score > 0:
                results.append({
                    "conv_id": data.get("id", ""),
                    "title": title,
                    "role": m.get("role", "?"),
                    "content": content,
                    "time": m.get("time") or data.get("updated", ""),
                    "score": score,
                })
    results.sort(key=lambda r: (r["score"], r["time"]), reverse=True)
    return results[:limit]


def delete_conversation(conv_id: str) -> bool:
    p = _path(conv_id)
    if p.exists():
        p.unlink()
        return True
    return False


def rename_conversation(conv_id: str, new_title: str) -> bool:
    conv = get_conversation(conv_id)
    if not conv:
        return False
    conv["title"] = new_title.strip()[:60] or conv["title"]
    _path(conv_id).write_text(json.dumps(conv, ensure_ascii=False, indent=2), encoding="utf-8")
    return True
