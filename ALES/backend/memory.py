import json
import os
from datetime import datetime
from pathlib import Path

try:
    from config_manager import LONG_MEMORY_FILE as MEMORY_FILE
except:
    MEMORY_FILE = Path("long_memory.json")

def load() -> dict:
    if MEMORY_FILE.exists():
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    return {
        "user": {
            "name": "",
            "preferences": [],
            "skills": [],
            "goals": [],
            "work": {},
            "personality_notes": []
        },
        "facts": [],
        "events": [],
        "learned": []
    }

def save(mem: dict):
    MEMORY_FILE.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")

def remember_fact(fact: str, category: str = "general") -> str:
    mem = load()
    mem["facts"].append({
        "fact": fact,
        "category": category,
        "time": datetime.now().isoformat()
    })
    # Son 200 fact tut
    if len(mem["facts"]) > 200:
        mem["facts"] = mem["facts"][-200:]
    save(mem)
    return f"✅ Öğrendim: {fact}"

def update_user_profile(key: str, value: str) -> str:
    mem = load()
    if key in mem["user"]:
        if isinstance(mem["user"][key], list):
            if value not in mem["user"][key]:
                mem["user"][key].append(value)
        else:
            mem["user"][key] = value
    else:
        mem["user"][key] = value
    save(mem)
    return f"✅ Profil güncellendi: {key} = {value}"

def get_user_profile() -> str:
    mem = load()
    u = mem["user"]
    lines = ["👤 Kullanıcı Profili:"]
    if u.get("name"): lines.append(f"İsim: {u['name']}")
    if u.get("preferences"): lines.append(f"Tercihler: {', '.join(u['preferences'])}")
    if u.get("skills"): lines.append(f"Yetenekler: {', '.join(u['skills'])}")
    if u.get("goals"): lines.append(f"Hedefler: {', '.join(u['goals'])}")
    if u.get("work"): lines.append(f"İş: {u['work']}")
    return "\n".join(lines) if len(lines) > 1 else "Henüz profil bilgisi yok."

def _cosine(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _semantic_rerank(query: str, candidates: list, gemini_key: str) -> list:
    """Gemini'nin embedding API'siyle ANLAMSAL siralama - tam kelime
    eslesmesi olmasa da (esanlamli/farkli ifade) en alakali sonuclar
    one cikar. Maliyet/hiz icin en fazla ilk 12 aday embed edilir,
    HIZ icin paralel calistirilir (sirayla 12 HTTP istegi yerine)."""
    k = (gemini_key or "").strip()
    if not k:
        return candidates
    try:
        from google import genai
        from concurrent.futures import ThreadPoolExecutor
        client = genai.Client(api_key=k)
        q_res = client.models.embed_content(model="gemini-embedding-2", contents=query)
        q_emb = q_res.embeddings[0].values

        def embed_one(c):
            try:
                r = client.models.embed_content(model="gemini-embedding-2", contents=c["content"][:1000])
                return (_cosine(q_emb, r.embeddings[0].values), c)
            except Exception:
                return (0.0, c)

        subset = candidates[:12]
        with ThreadPoolExecutor(max_workers=6) as ex:
            scored = list(ex.map(embed_one, subset))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored] + candidates[12:]
    except Exception as e:
        print(f"[MEMORY] google-genai embed hatasi: {e}")
        return candidates


def search_memory(query: str) -> str:
    """UZUN SURELI HAFIZA: artik sadece kayitli 'facts' listesinde degil,
    GECMISTEKI TUM SOHBETLERDE de arar (conversations.py uzerinden) -
    "gecen hafta X hakkinda ne konusmustuk" gibi sorulara da cevap
    verebilir. Gemini key varsa sonuclar anlamsal olarak da yeniden
    siralanir (esanlamli ifadelerde de dogru sonucu bulur); yoksa
    anahtar kelime eslesmesine duser (yine calisir, sadece daha az esnek)."""
    mem = load()
    query_lower = query.lower()
    fact_hits = [f"• {f['fact']} ({f['time'][:10]})" for f in mem["facts"] if query_lower in f["fact"].lower()]

    convo_hits = []
    try:
        from conversations import search_all_conversations
        convo_hits = search_all_conversations(query, limit=20)
    except Exception:
        pass

    if convo_hits:
        try:
            from config_manager import load_config
            gemini_key = load_config().get("gemini_key", "")
            if gemini_key:
                convo_hits = _semantic_rerank(query, convo_hits, gemini_key)
        except Exception as e:
            print(f"[MEMORY] Semantik siralama basarisiz, anahtar kelimeye devam: {e}")

    if not fact_hits and not convo_hits:
        return f"'{query}' için hafızada bir şey bulunamadı."

    lines = []
    if fact_hits:
        lines.append("📌 Kayıtlı bilgiler:")
        lines.extend(fact_hits[-10:])
    if convo_hits:
        if lines:
            lines.append("")
        lines.append("💬 Geçmiş sohbetlerden:")
        for h in convo_hits[:6]:
            snippet = h["content"][:160].replace("\n", " ")
            date = (h.get("time") or "")[:10]
            lines.append(f"• [{h['title']}, {date}] {h['role']}: {snippet}")
    return "\n".join(lines)

def get_all_facts() -> str:
    mem = load()
    if not mem["facts"]:
        return "📚 Hafıza boş."
    recent = mem["facts"][-15:]
    return "📚 Son öğrendiklerim:\n" + "\n".join([f"• {f['fact']}" for f in recent])

def log_event(event: str) -> str:
    mem = load()
    mem["events"].append({
        "event": event,
        "time": datetime.now().isoformat()
    })
    if len(mem["events"]) > 500:
        mem["events"] = mem["events"][-500:]
    save(mem)
    return f"✅ Olay kaydedildi."

def build_context_prompt() -> str:
    """Her konuşmaya eklenecek hafıza özeti"""
    mem = load()
    u = mem["user"]
    parts = []
    if u.get("name"): parts.append(f"Kullanıcının adı: {u['name']}")
    if u.get("preferences"): parts.append(f"Tercihleri: {', '.join(u['preferences'][:5])}")
    if u.get("goals"): parts.append(f"Hedefleri: {', '.join(u['goals'][:3])}")
    if u.get("skills"): parts.append(f"Yetenekleri: {', '.join(u['skills'][:5])}")
    recent_facts = mem["facts"][-10:]
    if recent_facts:
        facts_str = " | ".join([f["fact"] for f in recent_facts])
        parts.append(f"Son öğrendikleri: {facts_str}")
    return "\n".join(parts) if parts else ""
