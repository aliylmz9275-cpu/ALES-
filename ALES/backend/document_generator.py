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

STATIC_PDFS_DIR = Path(__file__).resolve().parent / "static" / "pdfs"

DOCS_DIR.mkdir(parents=True, exist_ok=True)
STATIC_PDFS_DIR.mkdir(parents=True, exist_ok=True)


def _clean_text_for_pdf(text: str) -> str:
    """LLM çıktısındaki ham kaçış karakterlerini ve XML özel karakterlerini düzenler.

    LLM'ler sıklıkla JSON tool_call argümanlarında satır sonlarını '\\n'
    (iki karakter: backslash + n) olarak gönderir. ReportLab bunları literal
    olarak basar — çirkin '\\n' gösterir. Ayrıca '\\t' ve çift-ters-eğik
    çizgi de temizlenir.
    """
    if not text:
        return ""
    t = str(text)
    # 1. LLM'in gönderdiği literal kaçış dizilerini gerçek karakterlere çevir
    t = t.replace("\\n", "\n")
    t = t.replace("\\t", "    ")
    t = t.replace("\\\\", "\\")
    # 2. XML özel karakterlerini ReportLab Paragraph için güvenli hale getir
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
        from reportlab.lib.enums import TA_JUSTIFY
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Preformatted
        )
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
    except ImportError as e:
        return {
            "ok": False,
            "error": f"ReportLab kütüphanesi eksik: {e}. Lütfen 'pip install reportlab' kurun."
        }

    # ── İÇERİĞİ TEMİZLE (LLM literal \n / JSON escape sorununu çöz) ──
    # LLM tool_call argümanlarında satır sonlarını çoğunlukla literal
    # '\\n' (iki karakter) olarak gönderir. Önce bunları gerçek newline'a çevir.
    clean_content = str(content or "")
    clean_content = clean_content.replace("\\n", "\n")
    clean_content = clean_content.replace("\\t", "    ")
    clean_content = clean_content.replace("\\\\", "\\")
    # Üst üste gelen boş satırları tek satıra düşür
    clean_content = re.sub(r"\n{3,}", "\n\n", clean_content)
    clean_title = str(title or "Belge").replace("\\n", " ").strip()

    safe_title = re.sub(r"[^\w\-_]", "_", clean_title) or "Belge"
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_title}_{timestamp_str}.pdf"
    pdf_path = STATIC_PDFS_DIR / filename

    try:
        # ── Türkçe karakter desteği: DejaVuSans (UTF-8 tam Unicode) ──
        _FONT_REG = "DejaVuSans"
        _FONT_BOLD = "DejaVuSans-Bold"
        _FONT_MONO = "DejaVuMono"
        _turkish_font_ok = False
        try:
            import shutil
            # Windows'ta DejaVu genelde yoktur; sistem fontlarından bul
            _font_dirs = [
                Path(__file__).resolve().parent / "fonts",
                Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
                Path("/usr/share/fonts/truetype/dejavu"),
                Path("/usr/share/fonts/dejavu"),
            ]
            _reg_path = _bold_path = _mono_path = None
            for fd in _font_dirs:
                if not fd.exists():
                    continue
                for f in fd.iterdir():
                    nm = f.name.lower()
                    if "dejavusans" in nm and "bold" not in nm and "oblique" not in nm and nm.endswith(".ttf"):
                        _reg_path = _reg_path or f
                    if "dejavusans" in nm and "bold" in nm and "oblique" not in nm and nm.endswith(".ttf"):
                        _bold_path = _bold_path or f
                    if "dejavusansmono" in nm and "bold" not in nm and "oblique" not in nm and nm.endswith(".ttf"):
                        _mono_path = _mono_path or f
            if _reg_path:
                pdfmetrics.registerFont(TTFont(_FONT_REG, str(_reg_path)))
                if _bold_path:
                    pdfmetrics.registerFont(TTFont(_FONT_BOLD, str(_bold_path)))
                else:
                    _FONT_BOLD = _FONT_REG
                if _mono_path:
                    pdfmetrics.registerFont(TTFont(_FONT_MONO, str(_mono_path)))
                else:
                    _FONT_MONO = "Courier"
                _turkish_font_ok = True
        except Exception as font_err:
            print(f"[PDF] DejaVu font yüklenemedi, Helvetica kullanılacak: {font_err}")

        if not _turkish_font_ok:
            _FONT_REG = "Helvetica"
            _FONT_BOLD = "Helvetica-Bold"
            _FONT_MONO = "Courier"

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
                self.setFont(_FONT_REG, 9)
                self.setFillColor(colors.HexColor("#71717A"))
                # Altbilgi çizgisi
                self.setStrokeColor(colors.HexColor("#E4E4E7"))
                self.setLineWidth(0.5)
                self.line(40, 40, A4[0] - 40, 40)
                # Sol: Telif/Üreten
                self.drawString(40, 28, f"ALES Belge Sistemi \u2022 {author}")
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
            leading=28,
            textColor=colors.HexColor("#0F172A"),
            spaceAfter=6,
            fontName=_FONT_BOLD
        )
        meta_style = ParagraphStyle(
            "DocMeta",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#64748B"),
            spaceAfter=14,
            fontName=_FONT_REG
        )
        h1_style = ParagraphStyle(
            "H1",
            parent=styles["Heading2"],
            fontSize=15,
            leading=19,
            textColor=colors.HexColor("#1E293B"),
            spaceBefore=14,
            spaceAfter=6,
            fontName=_FONT_BOLD
        )
        h2_style = ParagraphStyle(
            "H2",
            parent=styles["Heading3"],
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#334155"),
            spaceBefore=10,
            spaceAfter=4,
            fontName=_FONT_BOLD
        )
        body_style = ParagraphStyle(
            "Body",
            parent=styles["Normal"],
            fontSize=10,
            leading=15,
            textColor=colors.HexColor("#334155"),
            spaceAfter=6,
            fontName=_FONT_REG,
            alignment=TA_JUSTIFY
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
            fontName=_FONT_MONO
        )
        bullet_style = ParagraphStyle(
            "Bullet",
            parent=body_style,
            leftIndent=15,
            bulletIndent=5,
            spaceAfter=3,
            fontName=_FONT_REG
        )

        story = []

        # 1. Başlık & Meta Bilgi
        pdf_title = _clean_text_for_pdf(clean_title)
        story.append(Paragraph(pdf_title, title_style))
        date_str = datetime.now().strftime("%d.%m.%Y %H:%M")
        meta_text = f"Olu\u015fturulma Tarihi: {date_str} | Sistem: {author}"
        story.append(Paragraph(meta_text, meta_style))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0284C7"), spaceAfter=14))

        # 2. Markdown İçerik Ayrıştırma (temizlenmiş clean_content üzerinde)
        lines = clean_content.split("\n")
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
                story.append(Paragraph(f"\u2022 {b_text}", bullet_style))
            elif re.match(r"^\d+\.\s+", trimmed):
                num_match = re.match(r"^(\d+)\.\s+(.*)", trimmed)
                num_prefix = num_match.group(1) if num_match else ""
                num_text = num_match.group(2) if num_match else trimmed
                num_text = _clean_text_for_pdf(num_text)
                num_text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", num_text)
                story.append(Paragraph(f"{num_prefix}. {num_text}", bullet_style))
            elif trimmed.startswith("---") or trimmed.startswith("***"):
                story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#E2E8F0"), spaceAfter=8))
            else:
                p_text = _clean_text_for_pdf(trimmed)
                p_text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", p_text)
                p_text = re.sub(r"\*(.*?)\*", r"<i>\1</i>", p_text)
                p_text = re.sub(r"`(.*?)`", rf"<font name='{_FONT_MONO}'>\1</font>", p_text)
                story.append(Paragraph(p_text, body_style))

        # Kapanmamış kod bloğu varsa kapat
        if in_code_block and code_lines:
            raw_code = "\n".join(code_lines)
            clean_code = _clean_text_for_pdf(raw_code)
            story.append(Preformatted(clean_code, code_style))

        doc.build(story, canvasmaker=NumberedCanvas)

        # AppData yedek kopyası
        try:
            import shutil
            shutil.copy2(str(pdf_path), str(DOCS_DIR / filename))
        except Exception:
            pass

        size_bytes = pdf_path.stat().st_size
        download_url = f"/static/pdfs/{filename}"

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
    target = STATIC_PDFS_DIR / clean_name
    if target.exists() and target.is_file():
        return target
    target2 = DOCS_DIR / clean_name
    if target2.exists() and target2.is_file():
        return target2
    return None
