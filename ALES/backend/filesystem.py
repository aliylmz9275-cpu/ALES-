"""
Dosya sistemi araclari - ALES'in Claude gibi dosya
okuma/yazma/duzenleme yapmasini saglar.
"""
import os
from pathlib import Path

def _safe_path(path: str) -> Path:
    """Kullanici klasorlerine sinirla, sistem dosyalarina dokunma"""
    p = Path(os.path.expandvars(os.path.expanduser(path))).resolve()
    return p

def read_file(path: str, max_chars: int = 8000) -> str:
    """Bir dosyayi oku"""
    try:
        p = _safe_path(path)
        if not p.exists():
            return f"[HATA] Dosya bulunamadi: {p}"
        if p.is_dir():
            return f"[HATA] Bu bir klasor: {p}. list_directory kullan."
        content = p.read_text(encoding='utf-8', errors='replace')
        if len(content) > max_chars:
            return f"[DOSYA: {p}] ({len(content)} karakter, ilk {max_chars} gosteriliyor)\n\n{content[:max_chars]}\n\n...[devami var]"
        return f"[DOSYA: {p}]\n\n{content}"
    except Exception as e:
        return f"[HATA] {e}"

def write_file(path: str, content: str, overwrite: bool = False) -> str:
    """Yeni dosya olustur veya uzerine yaz"""
    try:
        p = _safe_path(path)
        if p.exists() and not overwrite:
            return f"[UYARI] Dosya zaten var: {p}. overwrite=true ile tekrar dene veya add_pending_approval ile onay al."
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding='utf-8')
        return f"[OK] Yazildi: {p} ({len(content)} karakter)"
    except Exception as e:
        return f"[HATA] {e}"

def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Dosyada metin degistir (find & replace)"""
    return str_replace_editor(path, old_text, new_text)

def str_replace_editor(file_path: str, old_string: str, new_string: str) -> str:
    """Claude Code uyumlu kesin metin değiştirici (str_replace_editor).
    Belirtilen dosyada old_string'i arar ve new_string ile drop-in değiştirir.
    """
    try:
        p = _safe_path(file_path)
        if not p.exists():
            return f"[HATA] Dosya bulunamadi: {p}"
        content = p.read_text(encoding='utf-8', errors='replace')
        if old_string not in content:
            return f"[HATA] Belirtilen metin (old_string) dosyada bulunamadı. Lütfen 'read_file' ile dosya içeriğini kontrol edin ve satır/boşluk eşleşmesine dikkat edin."
        count = content.count(old_string)
        if count > 1:
            return f"[UYARI] Bu metin dosyada {count} kez geçiyor. Değişikliğin tek ve kesin olması için lütfen etrafındaki birkaç satırı da ekleyerek daha fazla bağlamla çağırın."
        new_content = content.replace(old_string, new_string)
        p.write_text(new_content, encoding='utf-8')
        return f"✅ [OK] Başarıyla güncellendi: {p} (str_replace_editor)"
    except Exception as e:
        return f"[HATA] {e}"

def list_directory(path: str = ".") -> str:
    """Klasor icerigini listele"""
    try:
        p = _safe_path(path)
        if not p.exists():
            return f"[HATA] Klasor bulunamadi: {p}"
        if not p.is_dir():
            return f"[HATA] Bu bir dosya: {p}"
        items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        lines = [f"[KLASOR: {p}]"]
        for item in items[:100]:
            if item.name.startswith('.'):
                continue
            if item.is_dir():
                lines.append(f"  [D] {item.name}/")
            else:
                size = item.stat().st_size
                size_str = f"{size}B" if size < 1024 else f"{size//1024}KB" if size < 1024*1024 else f"{size//1024//1024}MB"
                lines.append(f"  [F] {item.name} ({size_str})")
        if len(items) > 100:
            lines.append(f"  ... ve {len(items)-100} dosya daha")
        return "\n".join(lines)
    except Exception as e:
        return f"[HATA] {e}"

def create_directory(path: str) -> str:
    """Yeni klasor olustur"""
    try:
        p = _safe_path(path)
        p.mkdir(parents=True, exist_ok=True)
        return f"[OK] Klasor olusturuldu: {p}"
    except Exception as e:
        return f"[HATA] {e}"

def delete_path(path: str) -> str:
    """Dosya/klasor sil - SADECE onaydan sonra cagrilir"""
    try:
        p = _safe_path(path)
        if not p.exists():
            return f"[HATA] Bulunamadi: {p}"
        if p.is_dir():
            import shutil
            shutil.rmtree(p)
            return f"[OK] Klasor silindi: {p}"
        else:
            p.unlink()
            return f"[OK] Dosya silindi: {p}"
    except Exception as e:
        return f"[HATA] {e}"

def search_files(directory: str, pattern: str) -> str:
    """Klasorde dosya adi veya icerikte arama yap"""
    try:
        p = _safe_path(directory)
        if not p.exists():
            return f"[HATA] Klasor bulunamadi: {p}"
        matches = []
        for item in p.rglob("*"):
            if item.is_file() and len(matches) < 30:
                if pattern.lower() in item.name.lower():
                    matches.append(f"  [AD] {item.relative_to(p)}")
                    continue
                try:
                    if item.stat().st_size < 500_000:
                        content = item.read_text(encoding='utf-8', errors='ignore')
                        if pattern.lower() in content.lower():
                            matches.append(f"  [ICERIK] {item.relative_to(p)}")
                except: pass
        if not matches:
            return f"[SONUC] '{pattern}' icin sonuc bulunamadi."
        return f"[ARAMA: '{pattern}' in {p}]\n" + "\n".join(matches)
    except Exception as e:
        return f"[HATA] {e}"

def get_file_info(path: str) -> str:
    """Dosya/klasor hakkinda bilgi"""
    try:
        p = _safe_path(path)
        if not p.exists():
            return f"[HATA] Bulunamadi: {p}"
        stat = p.stat()
        import datetime
        modified = datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%d.%m.%Y %H:%M')
        kind = "Klasor" if p.is_dir() else "Dosya"
        size = stat.st_size
        size_str = f"{size}B" if size < 1024 else f"{size//1024}KB" if size < 1024*1024 else f"{size/1024/1024:.1f}MB"
        return f"[{kind}] {p}\nBoyut: {size_str}\nSon degisiklik: {modified}"
    except Exception as e:
        return f"[HATA] {e}"

# ─── ALES SKILLS (siparis sablonlari ve rehberler) ──────────────
# Bu fonksiyonlar PyInstaller ile paketlenmis exe icindeki "skills/"
# klasorunu de bulabilmek icin hem dev hem paketli ortamda calisan
# bir yol cozumlemesi kullanir.

def _skills_dir() -> Path:
    # main.py'nin oldugu klasor (dev'de backend/, pakette _MEIPASS veya exe yani)
    here = Path(__file__).resolve().parent
    candidates = [
        here / "skills",
        Path(os.getcwd()) / "skills",
    ]
    # PyInstaller --onefile calisirken: gecici cikartma klasoru (_MEIPASS),
    # AMA skills/ buraya otomatik gelmez (sadece import edilen .py modulleri
    # gelir, klasor degil). Bu yuzden ayrica exe'nin KENDI durdugu klasore
    # bakiyoruz - build.bat bu klasore skills/'i kopyalar.
    meipass = getattr(__import__("sys"), "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "skills")
    exe_dir = Path(__import__("sys").executable).resolve().parent
    candidates.append(exe_dir / "skills")
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]  # bulunamazsa ilkini don, list_skills hata mesaji verir

def list_skills() -> str:
    """Mevcut siparis sablonlarini ve rehberleri listele"""
    d = _skills_dir()
    if not d.exists():
        return f"[HATA] Skills klasoru bulunamadi: {d}"
    files = sorted([f.name for f in d.iterdir() if f.is_file()])
    if not files:
        return f"[BILGI] Skills klasoru bos: {d}"
    return f"[SKILLS: {d}]\n" + "\n".join(f"  * {f}" for f in files)

def read_skill(filename: str) -> str:
    """Bir siparis sablonunu veya rehberi oku (skills/ klasorunden)"""
    d = _skills_dir()
    p = d / filename
    if not p.exists():
        available = ", ".join(f.name for f in d.iterdir()) if d.exists() else "klasor yok"
        return f"[HATA] '{filename}' bulunamadi. Mevcut dosyalar: {available}"
    try:
        return f"[SKILL: {filename}]\n\n{p.read_text(encoding='utf-8', errors='replace')}"
    except Exception as e:
        return f"[HATA] {e}"
