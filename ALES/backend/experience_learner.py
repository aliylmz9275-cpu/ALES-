"""
experience_learner.py — ALES Deneyim & Hata Öğrenme Modülü (Faz 4).

Görev yürütme sırasında (Executor) ardışık veya tekrarlanan hataları izler.
Bir görev 2 veya daha fazla kez aynı hatayla başarısız olduğunda, hatanın
nedenini analiz ederek kural çıkarır ve %APPDATA%\\ALES\\learned_rules.json
dosyasına kaydeder.

Bu kurallar daha sonra:
  1) Manager Agent'a istem oluşturulurken bildirilir (geçmiş hatalardan kaçınma).
  2) Executor Agent'a subtask yürütülürken ipucu olarak verilir.
  3) ALES genel sistem istemine (main.py BASE_SYSTEM) otomatik dahil edilir.
"""
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

from config_manager import get_appdata_dir

RULES_FILE = get_appdata_dir() / "learned_rules.json"

_MAX_RULES = 50

def _normalize_error(err: str) -> str:
    """Hata mesajını sayılardan ve dinamik adreslerden arındırıp temel kalıbı çıkarır."""
    s = str(err or "").strip().lower()
    s = re.sub(r"0x[0-9a-fA-F]+", "HEX", s)
    s = re.sub(r"\d+", "N", s)
    s = re.sub(r"['\"].*?['\"]", "STR", s)
    return s[:120]


def load_data() -> dict:
    """Veri dosyasını yükler, yoksa şablon oluşturur."""
    if not RULES_FILE.exists():
        return {"failures": {}, "rules": []}
    try:
        with open(RULES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {"failures": {}, "rules": []}
            data.setdefault("failures", {})
            data.setdefault("rules", [])
            return data
    except Exception as e:
        print(f"[EXPERIENCE_LEARNER] Dosya okunamadı: {e}")
        return {"failures": {}, "rules": []}


def save_data(data: dict) -> bool:
    """Atomik olarak veriyi kaydeder."""
    try:
        RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = RULES_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(RULES_FILE)
        return True
    except Exception as e:
        print(f"[EXPERIENCE_LEARNER] Kaydetme hatası: {e}")
        return False


def record_failure(action: str, error_msg: str, context: str = "") -> Optional[str]:
    """
    Bir eylemin başarısızlığını kaydeder.
    Aynı (action, error_signature) 2+ kez oluşursa otomatik bir kural üretip kaydeder.
    Yeni kural üretilirse kural metnini döner, aksi halde None döner.
    """
    if not action or not error_msg:
        return None

    data = load_data()
    failures = data.get("failures", {})
    rules = data.get("rules", [])

    err_sig = _normalize_error(error_msg)
    sig_key = f"{action}:{err_sig}"

    entry = failures.get(sig_key, {"count": 0, "last_seen": 0, "sample_err": error_msg})
    entry["count"] = entry.get("count", 0) + 1
    entry["last_seen"] = time.time()
    entry["sample_err"] = str(error_msg)[:200]
    entry["context"] = str(context)[:200]
    failures[sig_key] = entry

    new_rule = None
    # 2 veya daha fazla başarısızlık -> kural oluştur
    if entry["count"] >= 2:
        # Daha önce bu imza için kural yazılmış mı kontrol et
        existing = any(r.get("signature") == sig_key for r in rules)
        if not existing:
            rule_text = _generate_rule_text(action, error_msg, context)
            rule_obj = {
                "id": f"rule_{int(time.time())}_{len(rules)+1}",
                "signature": sig_key,
                "action": action,
                "rule": rule_text,
                "trigger_count": entry["count"],
                "created_at": datetime.now().isoformat(),
            }
            rules.append(rule_obj)
            # Maksimum kural sınırını koru
            if len(rules) > _MAX_RULES:
                rules = rules[-_MAX_RULES:]
            data["rules"] = rules
            new_rule = rule_text
            print(f"[EXPERIENCE_LEARNER] YENİ KURAL ÖĞRENİLDİ: {rule_text}")

    save_data(data)
    return new_rule


def _generate_rule_text(action: str, error_msg: str, context: str) -> str:
    """Hata türüne göre uygulanabilir pratik bir kural oluşturur."""
    err = str(error_msg).lower()
    act = str(action).lower()

    if "timeout" in err or "timed out" in err or "bekleme" in err:
        return f"'{action}' eylemi zaman aşımına uğruyor. İşlemden sonra en az 2-3 saniye bekleme koy ve UI elementinin hazır olduğunu doğrula."
    elif "not found" in err or "bulunamadı" in err or "no such" in err:
        return f"'{action}' hedef elementi veya dosyayı bulamıyor. Çağırmadan önce konumun veya pencere başlığının varlığını doğrula."
    elif "permission" in err or "yetki" in err or "access denied" in err:
        return f"'{action}' işleminde erişim engellendi. Gerekli dosya/uygulama izinlerini kontrol et veya alternatif yol kullan."
    elif "connection" in err or "bağlantı" in err or "network" in err:
        return f"'{action}' ağ bağlantı hatası verdi. Ağ durumunu kontrol et ve isteği yeniden dene."
    elif "click" in act or "desktop" in act:
        return f"Masaüstü eyleminde '{action}' başarısız oldu. Tıklamadan önce pencereyi öne getir (focus) ve 1.5s bekle."
    else:
        return f"'{action}' çalıştırılırken '{str(error_msg)[:60]}' hatası alındı. Ön koşulları kontrol et ve parametreleri doğrula."


def load_rules() -> List[Dict]:
    """Kayıtlı tüm kuralları listeler."""
    data = load_data()
    return data.get("rules", [])


def get_rules_prompt() -> str:
    """Promptlara enjekte edilmek üzere kuralları metin olarak döner."""
    rules = load_rules()
    if not rules:
        return ""

    lines = ["\n[GEÇMİŞ DENEYİMLERDEN ÖĞRENİLEN DERSLER VE KURALLAR]:"]
    for r in rules[-10:]:  # Son 10 güncel kural
        lines.append(f"• ({r.get('action', 'genel')}): {r.get('rule')}")
    lines.append("Bu kurallara dikkat et ve geçmişte yaşanan bu hataları tekrarlama.\n")
    return "\n".join(lines)


def clear_rules() -> bool:
    """Tüm öğrenilen kuralları sıfırlar."""
    return save_data({"failures": {}, "rules": []})
