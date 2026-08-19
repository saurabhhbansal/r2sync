"""Automated build script for compiling r2sync Windows executables and Inno Setup installer."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PACKAGING_DIR = ROOT_DIR / "packaging"
DIST_DIR = ROOT_DIR / "dist"
BUILD_DIR = ROOT_DIR / "build"
R2SYNC_DIST = DIST_DIR / "r2sync"


def run_step(cmd: list[str], description: str) -> None:
    print(f"\n==========================================")
    print(f"[*] {description}")
    print(f"    Command: {' '.join(cmd)}")
    print(f"==========================================")
    result = subprocess.run(cmd, cwd=str(ROOT_DIR))
    if result.returncode != 0:
        print(f"\n[!] Error: {description} failed with exit code {result.returncode}")
        sys.exit(result.returncode)


def clean() -> None:
    print("[*] Cleaning build and dist directories...")
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR, ignore_errors=True)
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR, ignore_errors=True)
    R2SYNC_DIST.mkdir(parents=True, exist_ok=True)


def find_iscc() -> str | None:
    # Check PATH
    iscc_path = shutil.which("iscc")
    if iscc_path:
        return iscc_path
    
    # Common Inno Setup paths on Windows
    common_paths = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path("C:/Program Files (x86)/Inno Setup 6/ISCC.exe"),
        Path("C:/Program Files/Inno Setup 6/ISCC.exe"),
        Path("C:/Program Files (x86)/Inno Setup 5/ISCC.exe"),
        Path("C:/Program Files/Inno Setup 5/ISCC.exe"),
    ]
    for p in common_paths:
        if p.exists():
            return str(p)
    return None


def main() -> None:
    clean()

    # 1. Build GUI App (r2sync.exe)
    run_step(
        [sys.executable, "-m", "PyInstaller", str(PACKAGING_DIR / "r2sync.spec"), "--distpath", str(R2SYNC_DIST), "--noconfirm"],
        "Compiling r2sync GUI Executable",
    )

    # 2. Build Service Daemon (r2sync-service.exe)
    run_step(
        [sys.executable, "-m", "PyInstaller", str(PACKAGING_DIR / "r2sync-service.spec"), "--distpath", str(R2SYNC_DIST), "--noconfirm"],
        "Compiling r2sync-service Executable",
    )

    # 3. Build CLI (r2sync-cli.exe)
    run_step(
        [sys.executable, "-m", "PyInstaller", str(PACKAGING_DIR / "r2sync-cli.spec"), "--distpath", str(R2SYNC_DIST), "--noconfirm"],
        "Compiling r2sync-cli Executable",
    )

    print("\n[+] All executables built successfully into:", R2SYNC_DIST)

    # 4. Compile Inno Setup installer
    iscc = find_iscc()
    if iscc:
        run_step([iscc, str(PACKAGING_DIR / "installer.iss")], "Compiling Inno Setup Installer (r2sync-setup.exe)")
        setup_exe = DIST_DIR / "r2sync-setup.exe"
        if setup_exe.exists():
            size_mb = setup_exe.stat().st_size / (1024 * 1024)
            print(f"\n==========================================")
            print(f"[SUCCESS] Windows Installer created: {setup_exe} ({size_mb:.2f} MB)")
            print(f"==========================================")
    else:
        print("\n[!] Inno Setup Compiler (ISCC.exe) not found.")
        print("    If you are on Windows, install Inno Setup 6 (https://jrsoftware.org/isdl.php) and rerun:")
        print(f"    iscc {PACKAGING_DIR / 'installer.iss'}")


if __name__ == "__main__":
    main()
