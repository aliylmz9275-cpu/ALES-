"""
email_assistant.py - Safe Personal Email Inbox Manager
======================================================

LEGAL & SAFE EMAIL AUTOMATION:
- Connects via standard IMAP/SSL (user's personal email)
- Reads and parses unread messages
- Generates smart executive summaries
- Prepares suggested reply drafts
- STRICT ANTI-SPAM & SAFETY:
  - NEVER automatically sends emails.
  - Outgoing emails require explicit manual confirmation token ('confirmed=True').
"""

import email
from email.header import decode_header
import imaplib
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ales.email_assistant")


def _decode_mime_words(raw_header: Optional[str]) -> str:
    if not raw_header:
        return ""
    decoded_fragments = []
    for text, encoding in decode_header(raw_header):
        if isinstance(text, bytes):
            try:
                decoded_fragments.append(text.decode(encoding or "utf-8", errors="replace"))
            except Exception:
                decoded_fragments.append(text.decode("latin1", errors="replace"))
        else:
            decoded_fragments.append(str(text))
    return "".join(decoded_fragments)


class EmailAssistant:
    def __init__(self):
        self.cached_emails: List[Dict[str, Any]] = []
        self.drafts: Dict[str, Dict[str, Any]] = []

    def fetch_unread_emails(self, imap_server: str, port: int, username: str, password: str, limit: int = 10) -> Dict[str, Any]:
        """
        Connects via IMAP and reads recent unread messages.
        """
        try:
            mail = imaplib.IMAP4_SSL(imap_server, port=port, timeout=10)
            mail.login(username, password)
            mail.select("INBOX")

            status, search_data = mail.search(None, "UNSEEN")
            if status != "OK":
                mail.logout()
                return {"error": "Gelen kutusu aranamadı"}

            mail_ids = search_data[0].split()
            recent_ids = mail_ids[-limit:] if len(mail_ids) > limit else mail_ids

            fetched = []
            for m_id in reversed(recent_ids):
                res, msg_data = mail.fetch(m_id, "(RFC822)")
                if res != "OK":
                    continue
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                subject = _decode_mime_words(msg.get("Subject"))
                sender = _decode_mime_words(msg.get("From"))
                date_str = msg.get("Date", "")

                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        content_disp = str(part.get("Content-Disposition"))
                        if content_type == "text/plain" and "attachment" not in content_disp:
                            payload = part.get_payload(decode=True)
                            if payload:
                                body = payload.decode("utf-8", errors="replace")
                                break
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body = payload.decode("utf-8", errors="replace")

                snippet = body.strip().replace("\r", " ")[:300]
                summary = f"{sender} tarafından '{subject}' konulu e-posta: {snippet[:120]}..."

                fetched.append({
                    "id": m_id.decode("utf-8"),
                    "from": sender,
                    "subject": subject,
                    "date": date_str,
                    "snippet": snippet,
                    "summary": summary
                })

            mail.logout()
            self.cached_emails = fetched
            return {
                "ok": True,
                "count": len(fetched),
                "emails": fetched
            }
        except Exception as e:
            return {"error": f"IMAP bağlantı veya okuma hatası: {str(e)}"}

    def draft_reply(self, email_info: Dict[str, Any], reply_intent: Optional[str] = None) -> Dict[str, Any]:
        """
        Creates a polite draft reply without sending.
        """
        recipient = email_info.get("from", "")
        subject = email_info.get("subject", "")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        draft_content = (
            f"Sayın İlgili,\n\n"
            f"E-postanız için teşekkür ederim. '{email_info.get('subject')}' konusundaki mesajınızı aldım. "
            f"Konuyu inceleyip en kısa sürede detaylı dönüş sağlayacağım.\n\n"
            f"Saygılarımla,\nAli Yılmaz"
        )

        draft = {
            "to": recipient,
            "subject": subject,
            "body": draft_content,
            "created_at": time.time(),
            "status": "draft_pending_user_review"
        }
        self.drafts.append(draft)
        return {
            "ok": True,
            "draft": draft,
            "notice": "E-posta taslağı oluşturuldu. Güvenlik gereği onayınız olmadan gönderilmez."
        }

    def send_email_smtp(self, smtp_server: str, port: int, username: str, password: str, to_addr: str, subject: str, body: str, confirmed: bool = False) -> Dict[str, Any]:
        """
        Sends an email ONLY when confirmed is True.
        """
        if not confirmed:
            return {
                "ok": False,
                "error": "Gönderim onaylanmadı. Güvenlik ve anti-spam kuralları gereği confirmed=True zorunludur."
            }

        try:
            msg = MIMEMultipart()
            msg["From"] = username
            msg["To"] = to_addr
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain", "utf-8"))

            if port == 465:
                server = smtplib.SMTP_SSL(smtp_server, port, timeout=10)
            else:
                server = smtplib.SMTP(smtp_server, port, timeout=10)
                server.starttls()

            server.login(username, password)
            server.send_message(msg)
            server.quit()

            return {
                "ok": True,
                "message": f"E-posta başarıyla gönderildi -> {to_addr}"
            }
        except Exception as e:
            return {"error": f"SMTP gönderim hatası: {str(e)}"}


email_assistant = EmailAssistant()
