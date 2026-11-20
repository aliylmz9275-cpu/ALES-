"""
freelance_bridge.py - Freelance Message Manager (Fiverr & Bionluk)
==================================================================

LEGAL & TOS-COMPLIANT FREELANCE AUTOMATION:
- Works with the user's OWN single account (no proxies, no multi-account abuse)
- Reads messages/orders via browser automation
- Generates smart summaries of inquiries
- Drafts proposed polite professional replies
- STRICTLY DOES NOT AUTO-SEND: User must review and manually send replies.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ales.freelance_bridge")

MESSAGES_CACHE_FILE = Path("freelance_cache.json")


class FreelanceBridge:
    def __init__(self):
        self.cached_messages: List[Dict[str, Any]] = []
        self.drafts: Dict[str, Dict[str, Any]] = {}
        self._load_cache()

    def _load_cache(self):
        try:
            if MESSAGES_CACHE_FILE.exists():
                data = json.loads(MESSAGES_CACHE_FILE.read_text(encoding="utf-8"))
                self.cached_messages = data.get("messages", [])
                self.drafts = data.get("drafts", {})
        except Exception as e:
            logger.warning(f"Failed to load freelance cache: {e}")

    def _save_cache(self):
        try:
            data = {
                "messages": self.cached_messages,
                "drafts": self.drafts,
                "updated_at": time.time()
            }
            MESSAGES_CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to save freelance cache: {e}")

    def fetch_messages(self, platform: str = "all", visible: bool = False) -> Dict[str, Any]:
        """
        Fetches incoming messages from Fiverr and/or Bionluk.
        """
        results = {}
        from fiverr import get_fiverr_messages_manual, get_bionluk_messages_manual

        if platform in ("fiverr", "all"):
            try:
                fiverr_res = get_fiverr_messages_manual(visible=visible)
                results["fiverr"] = fiverr_res
                self._parse_and_append("fiverr", fiverr_res)
            except Exception as e:
                results["fiverr"] = f"Error: {e}"

        if platform in ("bionluk", "all"):
            try:
                bionluk_res = get_bionluk_messages_manual(visible=visible)
                results["bionluk"] = bionluk_res
                self._parse_and_append("bionluk", bionluk_res)
            except Exception as e:
                results["bionluk"] = f"Error: {e}"

        self._save_cache()
        return {
            "status": "success",
            "results": results,
            "cached_count": len(self.cached_messages)
        }

    def _parse_and_append(self, platform: str, raw_text: str):
        if not raw_text or "HATA" in raw_text or "Giris yapilmamis" in raw_text:
            return
        snippets = [s.strip() for s in raw_text.split("---") if s.strip()]
        for idx, s in enumerate(snippets):
            msg_id = f"{platform}_{int(time.time())}_{idx}"
            # Check if text already exists
            if any(m.get("content") == s for m in self.cached_messages):
                continue
            self.cached_messages.append({
                "id": msg_id,
                "platform": platform,
                "content": s,
                "timestamp": time.time(),
                "summary": None,
                "draft_reply": None
            })

    def summarize_message(self, message_id: str, custom_summary: Optional[str] = None) -> Dict[str, Any]:
        """Summarizes a client inquiry."""
        msg = next((m for m in self.cached_messages if m["id"] == message_id), None)
        if not msg:
            return {"error": f"Message {message_id} not found"}

        if custom_summary:
            msg["summary"] = custom_summary
        else:
            # Deterministic heuristic summary if no LLM passed
            content = msg["content"]
            lines = [l.strip() for l in content.split("\n") if l.strip()]
            first_line = lines[0] if lines else "Mesaj"
            msg["summary"] = f"Müşteri Talebi: {first_line[:80]}... (Toplam {len(content)} karakter)"

        self._save_cache()
        return {"status": "ok", "message_id": message_id, "summary": msg["summary"]}

    def draft_reply(self, message_id: str, client_context: Optional[str] = None) -> Dict[str, Any]:
        """
        Creates a proposed reply draft.
        HONEST SAFETY NOTICE: ALES NEVER auto-sends.
        """
        msg = next((m for m in self.cached_messages if m["id"] == message_id), None)
        if not msg:
            return {"error": f"Message {message_id} not found"}

        # Generate a polite, structured freelance template
        platform = msg.get("platform", "fiverr").capitalize()
        draft_text = (
            f"Merhaba,\n\n"
            f"Mesajınız ve projeniz için teşekkür ederim! Belirttiğiniz gereksinimleri inceledim. "
            f"İstediğiniz teslimat süresi ve detaylar üzerinde tam olarak anlaşabilirsek memnuniyetle yardımcı olabilirim.\n\n"
            f"Sorularınız varsa veya detayları netleştirmek isterseniz lütfen paylaşın.\n\n"
            f"İyi çalışmalar dilerim."
        )

        msg["draft_reply"] = draft_text
        self.drafts[message_id] = {
            "draft_text": draft_text,
            "created_at": time.time(),
            "auto_send_allowed": False,
            "note": "Taslak hazırlandı. Otomatik gönderim YAPILMAZ; inceleyip platform üzerinden kendiniz gönderiniz."
        }
        self._save_cache()
        return {
            "status": "draft_created",
            "message_id": message_id,
            "draft": draft_text,
            "auto_send": False
        }

    def get_all(self) -> Dict[str, Any]:
        return {
            "messages": self.cached_messages,
            "drafts": self.drafts,
            "policy": "No auto-send. Manual user review required."
        }


freelance_manager = FreelanceBridge()
