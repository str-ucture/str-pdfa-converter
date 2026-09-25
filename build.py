"""Build a portable folder from local, license-reviewed runtime distributions."""

from __future__ import annotations

import argparse
import hashlib
import platform
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"


def require_runtime() -> None:
    checks = {
        "Ghostscript executable": [RUNTIME / "ghostscript" / "bin" / "gswin64c.exe", RUNTIME / "ghostscript" / "bin" / "gs", RUNTIME / "ghostscript" / "gs"],
        "Ghostscript sRGB profile": [RUNTIME / "ghostscript" / "iccprofiles" / "srgb.icc"],
        "veraPDF launcher": [RUNTIME / "verapdf" / "bin" / "verapdf.bat", RUNTIME / "verapdf" / "bin" / "verapdf", RUNTIME / "verapdf" / "verapdf.bat", RUNTIME / "verapdf" / "verapdf"],
        "Java runtime": [RUNTIME / "java" / "bin" / "java.exe", RUNTIME / "java" / "bin" / "java"],
    }
    missing = [label for label, candidates in checks.items() if not any(path.is_file() for path in candidates)]
    if missing:
        raise SystemExit("Missing runtime components:\n  - " + "\n  - ".join(missing) + "\n\nPlace the full folders under runtime/ as described in README.md, then build again.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a self-contained str-pdf folder for this operating system.")
    parser.add_argument("--clean", action="store_true", help="remove previous build output")
    args = parser.parse_args()
    if sys.platform not in ("win32", "darwin", "linux"):
        raise SystemExit("Build on Windows, macOS, or Linux.")
    require_runtime()

    import PyInstaller.__main__

    work = ROOT / "build"
    dist = ROOT / "dist"
    if args.clean:
        for generated in (work / "str-pdf", work / "str-pdf.spec", dist / "str-pdf", dist / "str-pdf.app"):
            if generated.is_dir():
                shutil.rmtree(generated)
            elif generated.is_file():
                generated.unlink()
    command = [
        str(ROOT / "src" / "str_pdf" / "__main__.py"), "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", "str-pdf", "--distpath", str(dist), "--workpath", str(work),
        "--specpath", str(work), "--paths", str(ROOT / "src"),
        "--collect-all", "tkinterdnd2",
    ]
    if sys.platform == "win32":
        icon = ROOT / "assets" / "str.ico"
        command.extend(("--icon", str(icon), "--add-data", f"{icon};assets"))
    PyInstaller.__main__.run(command)
    if sys.platform == "darwin":
        bundle = dist / "str-pdf"
        bundle.mkdir(exist_ok=True)
        app_bundle = dist / "str-pdf.app"
        shutil.move(str(app_bundle), str(bundle / app_bundle.name))
        internal = bundle / "str-pdf.app" / "Contents" / "Frameworks"
    else:
        bundle = dist / "str-pdf"
        internal = bundle / "_internal"
    internal.mkdir(exist_ok=True)
    shutil.copytree(RUNTIME, internal / "runtime", dirs_exist_ok=True, ignore=shutil.ignore_patterns(".installationinformation", "Uninstaller"))
    shutil.copy2(ROOT / "README.md", bundle / "README.txt")
    shutil.copy2(ROOT / "LICENSE", bundle / "LICENSE.txt")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", bundle / "THIRD_PARTY_NOTICES.txt")
    os_name = {"win32": "windows", "darwin": "macos", "linux": "linux"}[sys.platform]
    arch = {"AMD64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine(), platform.machine().lower())
    archive = dist / f"str-pdf-{os_name}-{arch}"
    shutil.make_archive(str(archive), "zip", root_dir=dist, base_dir=bundle.name)
    archive_path = Path(f"{archive}.zip")
    with archive_path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    Path(f"{archive_path}.sha256").write_text(f"{digest}  {archive_path.name}\n", encoding="ascii")
    print(f"Portable folder: {bundle}\nDownload archive: {archive_path}\nSHA-256: {digest}")


if __name__ == "__main__":
    main()
