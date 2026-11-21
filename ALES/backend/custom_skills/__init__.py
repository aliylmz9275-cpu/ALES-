"""
ALES Custom Skills Registry
Self-Evolution (Darwin-Gödel) motorunun otomatik ürettiği ve doğruladığı Python becerileri.
"""
import os
import sys
import importlib
from pathlib import Path

def load_all_custom_skills():
    """custom_skills klasöründeki tüm geçerli .py modüllerini dinamik olarak yükler."""
    skills_dir = Path(__file__).resolve().parent
    loaded = {}
    for f in skills_dir.glob("skill_*.py"):
        modname = f.stem
        try:
            if modname in sys.modules:
                mod = importlib.reload(sys.modules[modname])
            else:
                mod = importlib.import_module(f"custom_skills.{modname}")
            if hasattr(mod, "run"):
                loaded[modname] = mod
                print(f"[CUSTOM_SKILLS] Becerisi yüklendi: {modname}")
        except Exception as e:
            print(f"[CUSTOM_SKILLS] {modname} yükleme hatası: {e}")
    return loaded
