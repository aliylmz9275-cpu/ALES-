"""
file_organizer.py - Safe & Intelligent Local File Organizer
===========================================================

Automates file categorization and archiving with safety-first guarantees:
- Always supports dry-run / preview before executing any file moves.
- Categorizes by extension, age, or custom patterns.
- Safe collision handling: avoids overwriting existing files by appending counters.
- Generates transparent operation audit logs.
"""

import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CATEGORY_RULES = {
    "Belgeler": [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".txt", ".csv", ".rtf", ".odt"],
    "Görseller": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".psd"],
    "Arşivler": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"],
    "Kod & Geliştirme": [".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".json", ".xml", ".sql", ".sh", ".bat"],
    "Ses & Müzik": [".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg"],
    "Videolar": [".mp4", ".mkv", ".mov", ".avi", ".wmv", ".webm"],
    "Kurulum Dosyaları": [".exe", ".msi", ".dmg", ".iso"]
}


class FileOrganizer:
    def __init__(self):
        self.history: List[Dict[str, Any]] = []

    def scan_directory(self, folder_path: str) -> Dict[str, Any]:
        """Scans a directory and returns file statistics."""
        path = Path(folder_path).resolve()
        if not path.exists() or not path.is_dir():
            return {"error": f"Dizin bulunamadı: {folder_path}"}

        files_found = []
        now = time.time()
        for root, dirs, files in os.walk(path):
            # Only examine the top level by default to prevent unintended deep recursion
            for f in files:
                full_p = Path(root) / f
                try:
                    stat = full_p.stat()
                    age_days = (now - stat.st_mtime) / (24 * 3600)
                    files_found.append({
                        "name": f,
                        "path": str(full_p),
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "age_days": round(age_days, 1),
                        "ext": full_p.suffix.lower()
                    })
                except Exception:
                    pass
            break  # Top level only

        return {
            "folder": str(path),
            "file_count": len(files_found),
            "files": files_found[:200]
        }

    def preview_organization(self, folder_path: str, mode: str = "by_category", older_than_days: Optional[int] = None, custom_target: Optional[str] = None) -> Dict[str, Any]:
        """
        Calculates planned file movements WITHOUT making any changes.
        """
        scan = self.scan_directory(folder_path)
        if "error" in scan:
            return scan

        folder = Path(folder_path).resolve()
        planned_actions = []

        for item in scan["files"]:
            p = Path(item["path"])
            ext = item["ext"]
            age = item["age_days"]

            if older_than_days is not None and age < older_than_days:
                continue

            target_subfolder = "Diger"
            if mode == "by_category":
                for cat, exts in CATEGORY_RULES.items():
                    if ext in exts:
                        target_subfolder = cat
                        break
            elif mode == "archive_old":
                target_subfolder = custom_target or "Arsiv"
            elif mode == "by_extension":
                target_subfolder = ext.replace(".", "").upper() or "Uzantısız"

            target_dir = folder / target_subfolder
            target_path = target_dir / p.name

            planned_actions.append({
                "source": str(p),
                "destination_dir": str(target_dir),
                "destination_file": str(target_path),
                "filename": p.name,
                "category": target_subfolder,
                "reason": f"Kural: {mode} (Yaş: {age} gün)"
            })

        return {
            "folder": str(folder),
            "planned_count": len(planned_actions),
            "actions": planned_actions
        }

    def execute_organization(self, folder_path: str, actions: List[Dict[str, Any]], confirmed: bool = False) -> Dict[str, Any]:
        """
        Safely applies the approved planned actions.
        """
        if not confirmed:
            return {
                "ok": False,
                "error": "Onay verilmedi. Güvenlik gereği organize işlemi için 'confirmed=True' gereklidir."
            }

        moved_count = 0
        errors = []

        for act in actions:
            src = Path(act["source"])
            dst_dir = Path(act["destination_dir"])
            dst_file = Path(act["destination_file"])

            if not src.exists():
                continue

            try:
                dst_dir.mkdir(parents=True, exist_ok=True)
                
                # Collision protection
                final_dst = dst_file
                counter = 1
                while final_dst.exists() and final_dst.resolve() != src.resolve():
                    stem = dst_file.stem
                    suffix = dst_file.suffix
                    final_dst = dst_dir / f"{stem}_{counter}{suffix}"
                    counter += 1

                if final_dst.resolve() != src.resolve():
                    shutil.move(str(src), str(final_dst))
                    moved_count += 1
            except Exception as e:
                errors.append(f"{src.name}: {str(e)}")

        record = {
            "timestamp": time.time(),
            "folder": folder_path,
            "moved_count": moved_count,
            "errors": errors
        }
        self.history.append(record)

        return {
            "ok": True,
            "moved_count": moved_count,
            "errors": errors,
            "summary": f"{moved_count} dosya başarıyla taşındı ve organize edildi."
        }


organizer = FileOrganizer()
