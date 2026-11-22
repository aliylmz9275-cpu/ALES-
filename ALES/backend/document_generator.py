"""
document_generator.py — ALES Profesyonel PDF ve Belge Üretici Modülü (Faz 6).

Markdown ve düz metin içeriklerinden ReportLab motoru ile gerçek, biçimlendirilmiş
PDF belgeleri oluşturur.

Özellikler:
  - Başlık, tarih damgası, meta-bilgi blokları
  - Markdown başlıkları (# H1, ## H2, ### H3), kalın, italik ve madde işaretleri
  - Kod blokları ve alıntılar için özel biçimlendirme
  - Otomatik sayfa numaralandırma ve kurumsal altbilgi
  - Dosyaları `generated_docs` klasörüne kaydeder ve indirme URL'si döner
"""

import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

try:
    from config_manager import get_appdata_dir
    DOCS_DIR = get_appdata_dir() / "generated_docs"
except Exception:
    DOCS_DIR = Path("generated_docs")

DOCS_DIR.mkdir(parents=True, exist_ok=True)


def _clean_text_for_pdf(text: str) -> str:
    """XML ve HTML kaçış karakterlerini düzenler."""
    if not text:
        return ""
    t = str(text)
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return t


def generate_pdf(title: str, content: str, author: str = "ALES AI Assistant") -> Dict[str, Any]:
    """
    Markdown / metin içeriğinden gerçek bir PDF dosyası üretir.
    Döner: {"ok": True, "filename": str, "url": str, "path": str, "size_bytes": int}
    """
    try:
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Preformatted
        )
        from reportlab.pdfgen import canvas
    except ImportError as e:
        return {
            "ok": False,
            "error": f"ReportLab kütüphanesi eksik: {e}. Lütfen 'pip install reportlab' kurun."
        }

    safe_title = re.sub(r"[^\w\-_]", "_", title.strip()) or "Belge"
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_title}_{timestamp_str}.pdf"
    pdf_path = DOCS_DIR / filename

    try:
        # Sayfa numaralandırma için özel Canvas
        class NumberedCanvas(canvas.Canvas):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._saved_page_states = []

            def showPage(self):
                self._saved_page_states.append(dict(self.__dict__))
                self._startPage()

            def save(self):
                num_pages = len(self._saved_page_states)
                for state in self._saved_page_states:
                    self.__dict__.update(state)
                    self.draw_page_decorations(num_pages)
                    super().showPage()
                super().save()

            def draw_page_decorations(self, page_count):
                self.saveState()
                self.setFont("Helvetica", 9)
                self.setFillColor(colors.HexColor("#71717A"))
                # Altbilgi çizgisi
                self.setStrokeColor(colors.HexColor("#E4E4E7"))
                self.setLineWidth(0.5)
                self.line(40, 40, A4[0] - 40, 40)
                # Sol: Telif/Üreten
                self.drawString(40, 28, f"ALES Belge Sistemi • {author}")
                # Sağ: Sayfa Numarası
                page_text = f"Sayfa {self._pageNumber} / {page_count}"
                self.drawRightString(A4[0] - 40, 28, page_text)
                self.restoreState()

        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=A4,
            leftMargin=40,
            rightMargin=40,
            topMargin=45,
            bottomMargin=55
        )

        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            "DocTitle",
            parent=styles["Heading1"],
            fontSize=22,
            leading=26,
            textColor=colors.HexColor("#0F172A"),
            spaceAfter=6,
            fontName="Helvetica-Bold"
        )
        meta_style = ParagraphStyle(
            "DocMeta",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#64748B"),
            spaceAfter=14,
            fontName="Helvetica"
        )
        h1_style = ParagraphStyle(
            "H1",
            parent=styles["Heading2"],
            fontSize=15,
            leading=19,
            textColor=colors.HexColor("#1E293B"),
            spaceBefore=14,
            spaceAfter=6,
            fontName="Helvetica-Bold"
        )
        h2_style = ParagraphStyle(
            "H2",
            parent=styles["Heading3"],
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#334155"),
            spaceBefore=10,
            spaceAfter=4,
            fontName="Helvetica-Bold"
        )
        body_style = ParagraphStyle(
            "Body",
            parent=styles["Normal"],
            fontSize=10,
            leading=15,
            textColor=colors.HexColor("#334155"),
            spaceAfter=6,
            fontName="Helvetica"
        )
        code_style = ParagraphStyle(
            "CodeBlock",
            parent=styles["Code"],
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#0F172A"),
            backColor=colors.HexColor("#F1F5F9"),
            borderColor=colors.HexColor("#CBD5E1"),
            borderWidth=0.5,
            borderPadding=6,
            spaceBefore=6,
            spaceAfter=8,
            fontName="Courier"
        )
        bullet_style = ParagraphStyle(
            "Bullet",
            parent=body_style,
            leftIndent=15,
            bulletIndent=5,
            spaceAfter=3,
            fontName="Helvetica"
        )

        story = []

        # 1. Başlık & Meta Bilgi
        clean_title = _clean_text_for_pdf(title)
        story.append(Paragraph(clean_title, title_style))
        date_str = datetime.now().strftime("%d.%m.%Y %H:%M")
        meta_text = f"Oluşturulma Tarihi: {date_str} | Sistem: {author}"
        story.append(Paragraph(meta_text, meta_style))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0284C7"), spaceAfter=14))

        # 2. Markdown İçerik Ayrıştırma
        lines = content.split("\n")
        in_code_block = False
        code_lines = []

        for line in lines:
            trimmed = line.strip()

            # Kod blokları (```)
            if trimmed.startswith("```"):
                if in_code_block:
                    # Kod bloğu sonu
                    raw_code = "\n".join(code_lines)
                    clean_code = _clean_text_for_pdf(raw_code)
                    story.append(Preformatted(clean_code, code_style))
                    code_lines = []
                    in_code_block = False
                else:
                    in_code_block = True
                    code_lines = []
                continue

            if in_code_block:
                code_lines.append(line)
                continue

            if not trimmed:
                story.append(Spacer(1, 4))
                continue

            # Başlıklar
            if trimmed.startswith("# "):
                h_text = _clean_text_for_pdf(trimmed[2:])
                story.append(Paragraph(h_text, h1_style))
            elif trimmed.startswith("## "):
                h_text = _clean_text_for_pdf(trimmed[3:])
                story.append(Paragraph(h_text, h1_style))
            elif trimmed.startswith("### "):
                h_text = _clean_text_for_pdf(trimmed[4:])
                story.append(Paragraph(h_text, h2_style))
            # Madde İşaretleri
            elif trimmed.startswith(("- ", "* ", "+ ")):
                b_text = _clean_text_for_pdf(trimmed[2:])
                # Basit kalın/italik desteği
                b_text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", b_text)
                b_text = re.sub(r"\*(.*?)\*", r"<i>\1</i>", b_text)
                story.append(Paragraph(f"&bull; {b_text}", bullet_style))
            elif re.match(r"^\d+\.\s+", trimmed):
                num_text = re.sub(r"^\d+\.\s+", "", trimmed)
                num_text = _clean_text_for_pdf(num_text)
                num_text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", num_text)
                story.append(Paragraph(f"&bull; {num_text}", bullet_style))
            elif trimmed.startswith("---") or trimmed.startswith("***"):
                story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#E2E8F0"), spaceAfter=8))
            else:
                p_text = _clean_text_for_pdf(trimmed)
                p_text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", p_text)
                p_text = re.sub(r"\*(.*?)\*", r"<i>\1</i>", p_text)
                p_text = re.sub(r"`(.*?)`", r"<font name='Courier'>\1</font>", p_text)
                story.append(Paragraph(p_text, body_style))

        # Kapanmamış kod bloğu varsa kapat
        if in_code_block and code_lines:
            raw_code = "\n".join(code_lines)
            clean_code = _clean_text_for_pdf(raw_code)
            story.append(Preformatted(clean_code, code_style))

        doc.build(story, canvasmaker=NumberedCanvas)

        size_bytes = pdf_path.stat().st_size
        download_url = f"/api/download/pdf/{filename}"

        return {
            "ok": True,
            "filename": filename,
            "url": download_url,
            "path": str(pdf_path),
            "size_bytes": size_bytes,
            "message": f"📄 **PDF Belgesi Başarıyla Oluşturuldu:** [{filename}]({download_url}) ({round(size_bytes/1024, 1)} KB)"
        }

    except Exception as e:
        print(f"[DOCUMENT_GENERATOR] PDF üretme hatası: {e}")
        return {
            "ok": False,
            "error": f"PDF oluşturulamadı: {str(e)}"
        }


def get_pdf_path(filename: str) -> Optional[Path]:
    """Güvenli şekilde oluşturulan PDF dosya yolunu döner (Path traversal korumalı)."""
    clean_name = os.path.basename(filename)
    target = DOCS_DIR / clean_name
    if target.exists() and target.is_file():
        return target
    return None
