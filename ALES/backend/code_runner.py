import subprocess, sys, tempfile, os, traceback


def _interpreter() -> str:
    """Kodu calistiracak GERCEK python.exe'yi bul.

    KRITIK (PyInstaller): donmus derlemede sys.executable ALES.exe'dir,
    python.exe DEGIL. Onu calistirmak kodu YURUTMEZ; ikinci bir ALES ornegi
    baslatir (port 8000 cakismasi + yeni tarayici sekmesi). Ayni sorun
    code_act_executor'da da vardi; cozumu orada duruyor ve tek dogru yer
    olmasi icin onu cagiriyoruz.
    """
    if not getattr(sys, "frozen", False):
        return sys.executable or ""
    try:
        from code_act_executor import _python_exe
        return _python_exe() or ""
    except Exception:
        import shutil
        me = os.path.basename(sys.executable or "").lower()
        for n in ("python", "python3", "py"):
            p = shutil.which(n)
            if p and os.path.basename(p).lower() != me:
                return p
        return ""


def run_python_code(code: str) -> str:
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(code)
            tmp = f.name
        py = _interpreter()
        if not py:
            os.unlink(tmp)
            return ("❌ Python yorumlayıcısı bulunamadı. Paketlenmiş ALES.exe "
                    "içinde Python kodu çalıştırmak için sistemde kurulu bir "
                    "Python gerekir: python.org'dan kurun ve kurulumda "
                    "\"Add python.exe to PATH\" seçeneğini işaretleyin.")
        result = subprocess.run([py, tmp], capture_output=True, text=True, timeout=30,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        os.unlink(tmp)
        out = result.stdout.strip()
        err = result.stderr.strip()
        if err and not out:
            return f"❌ Hata:\n{err}"
        return f"✅ Sonuç:\n{out}" + (f"\n⚠️ Uyarı:\n{err}" if err else "")
    except subprocess.TimeoutExpired:
        return "❌ Zaman aşımı (30s)"
    except Exception as e:
        return f"❌ {e}"
