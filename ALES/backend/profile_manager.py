"""
profile_manager.py — ALES Kalıcı Profil ve API Anahtarı Yönetimi (SQLite).

Kullanıcıların API anahtarlarını erişim koduna (access_code) göre SQLite veritabanında
kalıcı olarak saklar. Tarayıcı/mobil yenilendiğinde veya sunucu yeniden başladığında
anahtarların kaybolmasını engeller.
"""

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    from config_manager import get_appdata_dir
    DB_DIR = get_appdata_dir()
except Exception:
    DB_DIR = Path(__file__).resolve().parent

DB_PATH = DB_DIR / "ales_profiles.db"


def _get_connection() -> sqlite3.Connection:
    """SQLite veritabanı bağlantısı açar ve Row factory tanımlar."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Veritabanını ve profiles tablosunu oluşturur."""
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                access_code TEXT UNIQUE NOT NULL,
                groq_key TEXT DEFAULT '',
                gemini_key TEXT DEFAULT '',
                openai_key TEXT DEFAULT '',
                elevenlabs_key TEXT DEFAULT '',
                cerebras_key TEXT DEFAULT '',
                sambanova_key TEXT DEFAULT '',
                openrouter_key TEXT DEFAULT '',
                nvidia_key TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_profiles_access_code ON profiles(access_code);")
        conn.commit()


# Modül yüklendiğinde tabloyu hazırla
init_db()


def save_profile(access_code: str, name: str = "", keys: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
    """
    Erişim koduna göre profili ve anahtarları kaydeder veya günceller (Upsert).
    """
    code = (access_code or "").strip()
    if not code:
        return {"ok": False, "error": "Erişim kodu (access_code) boş olamaz."}

    k = {}
    if keys and isinstance(keys, dict):
        k.update(keys)
    k.update(kwargs)
    groq_key = str(k.get("groq_key") or k.get("groq") or "").strip()
    gemini_key = str(k.get("gemini_key") or k.get("gemini") or "").strip()
    openai_key = str(k.get("openai_key") or k.get("openai") or "").strip()
    elevenlabs_key = str(k.get("elevenlabs_key") or k.get("elevenlabs") or "").strip()
    cerebras_key = str(k.get("cerebras_key") or k.get("cerebras") or "").strip()
    sambanova_key = str(k.get("sambanova_key") or k.get("sambanova") or "").strip()
    openrouter_key = str(k.get("openrouter_key") or k.get("openrouter") or "").strip()
    nvidia_key = str(k.get("nvidia_key") or k.get("nvidia") or "").strip()
    p_name = (name or f"Profil_{code}").strip()
    now = datetime.now().isoformat()

    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM profiles WHERE access_code = ?", (code,))
        row = cursor.fetchone()

        if row:
            # Mevcut profili güncelle
            cursor.execute("""
                UPDATE profiles SET
                    name = ?,
                    groq_key = CASE WHEN ? != '' THEN ? ELSE groq_key END,
                    gemini_key = CASE WHEN ? != '' THEN ? ELSE gemini_key END,
                    openai_key = CASE WHEN ? != '' THEN ? ELSE openai_key END,
                    elevenlabs_key = CASE WHEN ? != '' THEN ? ELSE elevenlabs_key END,
                    cerebras_key = CASE WHEN ? != '' THEN ? ELSE cerebras_key END,
                    sambanova_key = CASE WHEN ? != '' THEN ? ELSE sambanova_key END,
                    openrouter_key = CASE WHEN ? != '' THEN ? ELSE openrouter_key END,
                    nvidia_key = CASE WHEN ? != '' THEN ? ELSE nvidia_key END,
                    updated_at = ?
                WHERE access_code = ?
            """, (
                p_name,
                groq_key, groq_key,
                gemini_key, gemini_key,
                openai_key, openai_key,
                elevenlabs_key, elevenlabs_key,
                cerebras_key, cerebras_key,
                sambanova_key, sambanova_key,
                openrouter_key, openrouter_key,
                nvidia_key, nvidia_key,
                now, code
            ))
        else:
            # Yeni profil ekle
            cursor.execute("""
                INSERT INTO profiles (
                    name, access_code, groq_key, gemini_key, openai_key, elevenlabs_key,
                    cerebras_key, sambanova_key, openrouter_key, nvidia_key, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                p_name, code, groq_key, gemini_key, openai_key, elevenlabs_key,
                cerebras_key, sambanova_key, openrouter_key, nvidia_key, now, now
            ))
        conn.commit()

    return {
        "ok": True,
        "access_code": code,
        "name": p_name,
        "message": f"'{p_name}' profili başarıyla kaydedildi."
    }


def load_profile(access_code: str) -> Dict[str, Any]:
    """
    Erişim koduna göre profili ve anahtarları yükler.
    """
    code = (access_code or "").strip()
    if not code:
        return {"ok": False, "error": "Erişim kodu boş olamaz."}

    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM profiles WHERE access_code = ?", (code,))
        row = cursor.fetchone()

        if not row:
            return {"ok": False, "error": f"'{code}' koduna ait kayıtlı profil bulunamadı."}

        keys = {
            "groq_key": row["groq_key"] or "",
            "gemini_key": row["gemini_key"] or "",
            "openai_key": row["openai_key"] or "",
            "elevenlabs_key": row["elevenlabs_key"] or "",
            "cerebras_key": row["cerebras_key"] or "",
            "sambanova_key": row["sambanova_key"] or "",
            "openrouter_key": row["openrouter_key"] or "",
            "nvidia_key": row["nvidia_key"] or "",
        }

        # Frontend formatı için eşdeğer kısa isimler
        short_keys = {
            "groq": keys["groq_key"],
            "gemini": keys["gemini_key"],
            "openai": keys["openai_key"],
            "elevenlabs": keys["elevenlabs_key"],
            "cerebras": keys["cerebras_key"],
            "sambanova": keys["sambanova_key"],
            "openrouter": keys["openrouter_key"],
            "nvidia": keys["nvidia_key"],
        }

        return {
            "ok": True,
            "id": row["id"],
            "name": row["name"],
            "access_code": row["access_code"],
            "keys": keys,
            "short_keys": short_keys,
            "updated_at": row["updated_at"]
        }


def list_profiles() -> List[Dict[str, Any]]:
    """Kayıtlı profillerin özet listesini döner."""
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, access_code, updated_at FROM profiles ORDER BY updated_at DESC")
        rows = cursor.fetchall()
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "access_code": r["access_code"],
                "updated_at": r["updated_at"]
            }
            for r in rows
        ]


def delete_profile(access_code: str) -> bool:
    """Profili siler."""
    code = (access_code or "").strip()
    if not code:
        return False
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM profiles WHERE access_code = ?", (code,))
        conn.commit()
        return cursor.rowcount > 0
