"""
report_generator.py - Automated Data Summary & PDF/HTML Report Generator
========================================================================

Reads tabular data (CSV, TSV, Excel) and automatically produces:
1. Executive statistical summaries (row counts, column types, averages, extremes).
2. Clean, beautifully styled HTML reports (printable to PDF via browser/system).
3. Structured JSON summaries for LLM consumption and fast insight delivery.
"""

import csv
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ales.report_generator")


class ReportGenerator:
    def __init__(self):
        self.reports_generated: List[Dict[str, Any]] = []

    def parse_tabular_file(self, file_path: str, max_rows: int = 5000) -> Dict[str, Any]:
        """
        Parses CSV, TSV, or Excel (.xlsx) file and computes tabular statistics.
        Works without heavy mandatory dependencies (fallback to csv/text parsing).
        """
        p = Path(file_path).resolve()
        if not p.exists():
            return {"error": f"Dosya bulunamadı: {file_path}"}

        ext = p.suffix.lower()
        rows: List[List[str]] = []
        headers: List[str] = []

        if ext in (".csv", ".tsv", ".txt"):
            delimiter = "\t" if ext == ".tsv" else ","
            try:
                with open(p, mode="r", encoding="utf-8", errors="replace") as f:
                    reader = csv.reader(f, delimiter=delimiter)
                    for idx, row in enumerate(reader):
                        if idx == 0:
                            headers = [c.strip() for c in row]
                        else:
                            rows.append([c.strip() for c in row])
                        if len(rows) >= max_rows:
                            break
            except Exception as e:
                return {"error": f"CSV okuma hatası: {e}"}

        elif ext in (".xlsx", ".xls"):
            # Attempt to use openpyxl or pandas if available
            try:
                import openpyxl
                wb = openpyxl.load_workbook(p, data_only=True)
                ws = wb.active
                for idx, row in enumerate(ws.iter_rows(values_only=True)):
                    clean_row = [str(c) if c is not None else "" for c in row]
                    if idx == 0:
                        headers = clean_row
                    else:
                        rows.append(clean_row)
                    if len(rows) >= max_rows:
                        break
            except ImportError:
                return {
                    "error": "Excel (.xlsx) dosyalarını okumak için 'openpyxl' gereklidir. Lütfen CSV formatını deneyin veya 'pip install openpyxl' çalıştırın."
                }
            except Exception as e:
                return {"error": f"Excel okuma hatası: {e}"}
        else:
            return {"error": f"Desteklenmeyen dosya biçimi: {ext}. CSV veya XLSX gereklidir."}

        # Analyze columns
        col_stats: Dict[str, Dict[str, Any]] = {}
        for c_idx, h in enumerate(headers):
            h_name = h or f"Kolon_{c_idx+1}"
            col_values = [r[c_idx] for r in rows if c_idx < len(r) and r[c_idx] != ""]
            
            # Check if numeric
            nums = []
            for v in col_values:
                try:
                    nums.append(float(v.replace(",", ".")))
                except ValueError:
                    pass

            if nums and len(nums) > len(col_values) * 0.5:
                col_stats[h_name] = {
                    "type": "numeric",
                    "count": len(col_values),
                    "sum": round(sum(nums), 2),
                    "avg": round(sum(nums) / len(nums), 2),
                    "min": round(min(nums), 2),
                    "max": round(max(nums), 2)
                }
            else:
                col_stats[h_name] = {
                    "type": "text",
                    "count": len(col_values),
                    "distinct_sample": list(set(col_values))[:5]
                }

        summary = {
            "file_name": p.name,
            "total_rows": len(rows),
            "columns": headers,
            "column_stats": col_stats,
            "sample_rows": rows[:5]
        }
        return summary

    def generate_html_report(self, file_path: str, title: str = "ALES Veri Analiz Raporu") -> Dict[str, Any]:
        """
        Generates a standalone, responsive, modern dark-themed HTML report.
        """
        data = self.parse_tabular_file(file_path)
        if "error" in data:
            return data

        p = Path(file_path)
        out_path = p.parent / f"{p.stem}_rapor.html"

        col_cards_html = ""
        for col_name, stats in data["column_stats"].items():
            if stats["type"] == "numeric":
                col_cards_html += f"""
                <div class="card">
                    <h3>{col_name} <span class="tag num">Sayısal</span></h3>
                    <div class="metric"><span class="label">Toplam:</span> <b>{stats['sum']:,}</b></div>
                    <div class="metric"><span class="label">Ortalama:</span> <b>{stats['avg']:,}</b></div>
                    <div class="metric"><span class="label">Min / Max:</span> <b>{stats['min']:,} / {stats['max']:,}</b></div>
                    <div class="metric"><span class="label">Dolu Satır:</span> <b>{stats['count']}</b></div>
                </div>
                """
            else:
                samples = ", ".join(stats.get("distinct_sample", []))
                col_cards_html += f"""
                <div class="card">
                    <h3>{col_name} <span class="tag txt">Metin</span></h3>
                    <div class="metric"><span class="label">Dolu Satır:</span> <b>{stats['count']}</b></div>
                    <div class="metric"><span class="label">Örnekler:</span> <span class="small">{samples}</span></div>
                </div>
                """

        # Sample rows table
        th_html = "".join(f"<th>{h}</th>" for h in data["columns"])
        tr_html = ""
        for row in data["sample_rows"]:
            td_html = "".join(f"<td>{c}</td>" for c in row)
            tr_html += f"<tr>{td_html}</tr>"

        html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<title>{title} - {data['file_name']}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f1117; color: #e1e4ea; margin: 0; padding: 24px; }}
  .container {{ max-width: 1000px; margin: 0 auto; }}
  header {{ border-bottom: 1px solid #2a2e3d; padding-bottom: 16px; margin-bottom: 24px; display: flex; justify-content: space-between; align-items: flex-end; }}
  h1 {{ margin: 0 0 6px 0; font-size: 24px; color: #4ade80; }}
  .meta {{ font-size: 13px; color: #8b949e; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; margin-bottom: 32px; }}
  .card {{ background: #161b26; border: 1px solid #2a2e3d; border-radius: 8px; padding: 16px; }}
  .card h3 {{ margin: 0 0 12px 0; font-size: 15px; display: flex; justify-content: space-between; align-items: center; }}
  .tag {{ font-size: 10px; padding: 2px 6px; border-radius: 4px; text-transform: uppercase; font-family: monospace; }}
  .tag.num {{ background: #1e3a5f; color: #60a5fa; }}
  .tag.txt {{ background: #2d2640; color: #c084fc; }}
  .metric {{ display: flex; justify-content: space-between; font-size: 13px; padding: 4px 0; border-bottom: 1px solid #1f2430; }}
  .metric:last-child {{ border-bottom: none; }}
  .label {{ color: #8b949e; }}
  .small {{ font-size: 11px; color: #adb5bd; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 12px; }}
  th, td {{ padding: 8px 12px; text-align: left; border: 1px solid #2a2e3d; }}
  th {{ background: #1c2230; color: #cbd5e1; }}
  tr:nth-child(even) {{ background: #141824; }}
  .badge {{ background: #059669; color: white; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; }}
  @media print {{ body {{ background: white; color: black; }} .card {{ border: 1px solid #ccc; }} }}
</style>
</head>
<body>
<div class="container">
  <header>
    <div>
      <h1>📊 {title}</h1>
      <div class="meta">Kaynak Dosya: <b>{data['file_name']}</b> | Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
    </div>
    <span class="badge">{data['total_rows']} Satır Kayıt</span>
  </header>

  <h2>Kolon Özetleri</h2>
  <div class="grid">
    {col_cards_html}
  </div>

  <h2>Örnek Veri Önizleme (İlk 5 Satır)</h2>
  <div style="overflow-x: auto;">
    <table>
      <thead><tr>{th_html}</tr></thead>
      <tbody>{tr_html}</tbody>
    </table>
  </div>
</div>
</body>
</html>"""

        try:
            out_path.write_text(html_content, encoding="utf-8")
            record = {
                "file": str(out_path),
                "generated_at": time.time(),
                "rows": data["total_rows"]
            }
            self.reports_generated.append(record)
            return {
                "ok": True,
                "report_file": str(out_path),
                "summary": f"{data['file_name']} için rapor oluşturuldu: {data['total_rows']} satır analiz edildi.",
                "data": data
            }
        except Exception as e:
            return {"error": f"Rapor dosyası yazılamadı: {e}"}


report_generator = ReportGenerator()
