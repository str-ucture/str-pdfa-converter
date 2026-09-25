"""Local PDF/A conversion and independent veraPDF validation."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from threading import Event

FORMATS = {"PDF/A-1b": "1b", "PDF/A-2b": "2b", "PDF/A-3b": "3b"}
GS_PARTS = {"1b": "1", "2b": "2", "3b": "3"}


class Cancelled(Exception):
    pass


class ToolError(Exception):
    pass


class ConversionError(ToolError):
    pass


class VerificationError(ToolError):
    pass


def app_dir() -> Path:
    """Folder holding runtime/, assets/ and LICENSE: the bundle when frozen, else the repository root."""
    return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]


def _first_file(paths: list[Path]) -> Path | None:
    return next((path for path in paths if path.is_file()), None)


def find_ghostscript() -> Path | None:
    base = app_dir() / "runtime" / "ghostscript"
    names = ("gswin64c.exe", "gswin32c.exe", "gswin64.exe", "gswin32.exe") if os.name == "nt" else ("gs",)
    packaged = [base / name for name in names]
    packaged += [base / "bin" / name for name in names]
    found = _first_file(packaged)
    if found:
        return found
    located = shutil.which(names[0])
    return Path(located) if located else None


def find_verapdf() -> Path | None:
    base = app_dir() / "runtime" / "verapdf"
    names = ("verapdf.bat", "verapdf.exe", "verapdf") if os.name == "nt" else ("verapdf",)
    found = _first_file([base / name for name in names] + [base / "bin" / name for name in names] + [base / "verapdf" / name for name in names])
    if found:
        return found
    located = shutil.which(names[0])
    return Path(located) if located else None


def find_icc_profile(gs_exe: Path) -> Path:
    candidates = [app_dir() / "runtime" / "ghostscript" / "iccprofiles" / "srgb.icc"]
    candidates.extend(parent / "iccprofiles" / "srgb.icc" for parent in gs_exe.parents)
    found = _first_file(candidates)
    if not found:
        raise ToolError("Ghostscript's srgb.icc profile was not found beside the bundled engine.")
    return found


def _java_home() -> Path | None:
    base = app_dir() / "runtime" / "java"
    executable = "java.exe" if os.name == "nt" else "java"
    if (base / "bin" / executable).is_file():
        return base
    configured = os.getenv("JAVA_HOME")
    return Path(configured) if configured else None


def _ps_string(path: Path) -> str:
    return str(path.resolve()).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _run(args: list[str], cancel: Event, env: dict[str, str] | None = None) -> tuple[int, str]:
    try:
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=env)
    except OSError as exc:
        raise ToolError(f"Could not start {Path(args[0]).name}: {exc}") from exc
    try:
        while True:
            try:
                output, _ = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if cancel.is_set():
                    process.terminate()
                    try:
                        output, _ = process.communicate(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        output, _ = process.communicate()
                    raise Cancelled()
        return process.returncode, output
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def convert(input_pdf: Path, output_pdf: Path, pdfa_format: str, gs_exe: Path, cancel: Event) -> str:
    profile = FORMATS[pdfa_format]
    icc = find_icc_profile(gs_exe)
    fd, def_name = tempfile.mkstemp(prefix=f".{output_pdf.stem}-", suffix=".pdfa.ps", dir=output_pdf.parent)
    os.close(fd)
    def_file = Path(def_name)
    try:
        def_file.write_text(
            f"""%!PS-Adobe-3.0
% Minimal PDF/A output intent using the bundled sRGB profile.
/ICCProfile ({_ps_string(icc)}) def
[/_objdef {{icc_PDFA}} /type /stream /OBJ pdfmark
[{{icc_PDFA}} << /N 3 >> /PUT pdfmark
[{{icc_PDFA}} ICCProfile (r) file /PUT pdfmark
[/_objdef {{OutputIntent_PDFA}} /type /dict /OBJ pdfmark
[{{OutputIntent_PDFA}} << /Type /OutputIntent /S /GTS_PDFA1 /DestOutputProfile {{icc_PDFA}} /OutputConditionIdentifier (sRGB) >> /PUT pdfmark
[{{Catalog}} <</OutputIntents [ {{OutputIntent_PDFA}} ]>> /PUT pdfmark
""",
            encoding="ascii",
        )
        args = [
            str(gs_exe), "-dSAFER", "-dBATCH", "-dNOPAUSE", "-dNOPROMPT",
            f"-dPDFA={GS_PARTS[profile]}", "-dPDFACompatibilityPolicy=2",
            "-sDEVICE=pdfwrite", "-sColorConversionStrategy=RGB", "-sProcessColorModel=DeviceRGB",
            f"-sOutputFile={output_pdf}", f"--permit-file-read={icc}", str(def_file), str(input_pdf),
        ]
        try:
            code, output = _run(args, cancel)
        except ToolError as exc:
            raise ConversionError(str(exc)) from exc
    finally:
        try:
            def_file.unlink()
        except OSError:
            pass
    if code:
        raise ConversionError(_tail(output) or f"Ghostscript exited with code {code}.")
    if not output_pdf.is_file() or output_pdf.stat().st_size == 0:
        raise ConversionError("Ghostscript did not produce an output PDF.")
    return output


def validate(pdf: Path, profile: str, verapdf: Path, cancel: Event, java_home: Path | None = None) -> tuple[bool, str]:
    args = [str(verapdf), "--loglevel", "0", "--format", "xml", "-f", profile, str(pdf)]
    env = os.environ.copy()
    java_home = java_home or _java_home()
    if java_home:
        env["JAVA_HOME"] = str(java_home)
        env["PATH"] = str(java_home / "bin") + os.pathsep + env.get("PATH", "")
    # The Windows launcher is a batch file; execute its quoted command via cmd.exe.
    if os.name == "nt" and verapdf.suffix.lower() == ".bat":
        command = subprocess.list2cmdline([str(verapdf), *args[1:]])
        args = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", command]
    try:
        code, output = _run(args, cancel, env)
    except ToolError as exc:
        raise VerificationError(f"veraPDF: {exc}") from exc
    return parse_verapdf_report(output, code)


def parse_verapdf_report(output: str, return_code: int = 0) -> tuple[bool, str]:
    try:
        root = ET.fromstring(output)
    except ET.ParseError as exc:
        raise VerificationError(f"veraPDF returned no readable validation report. {_tail(output)}") from exc
    report = root.find(".//validationReport")
    if report is None or "isCompliant" not in report.attrib:
        raise VerificationError(f"veraPDF returned no conformance result. {_tail(output)}")
    compliant = report.attrib["isCompliant"].lower() == "true"
    details = [report.attrib.get("statement", "")]
    for rule in report.findall(".//rule[@status='failed']")[:12]:
        clause = rule.attrib.get("clause", "")
        test = rule.attrib.get("testNumber", "")
        details.append(f"Failed rule {clause}-{test}".rstrip("-"))
    if return_code and compliant:
        raise VerificationError(f"veraPDF reported success but exited with code {return_code}.")
    return compliant, "\n".join(part for part in details if part)


def _tail(value: str, limit: int = 2500) -> str:
    return value.strip()[-limit:]
