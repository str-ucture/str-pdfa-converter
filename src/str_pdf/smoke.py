"""Create, convert, and validate one tiny PDF for each supported PDF/A profile."""

from __future__ import annotations

import tempfile
from pathlib import Path
from threading import Event

from str_pdf.conversion import FORMATS, convert, find_ghostscript, find_verapdf, validate


def make_pdf(path: Path) -> None:
    stream = b"BT /F1 18 Tf 72 720 Td (PDF-A check) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode())
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    path.write_bytes(pdf)


def main() -> None:
    gs, validator = find_ghostscript(), find_verapdf()
    if not gs or not validator:
        raise SystemExit("Smoke check needs Ghostscript and veraPDF on PATH or in runtime/.")
    with tempfile.TemporaryDirectory(prefix="str-pdf-smoke-") as temp:
        run(Path(temp), gs, validator)


def run(folder: Path, gs: Path, validator: Path) -> None:
    source = folder / "sample.pdf"
    make_pdf(source)
    valid, details = validate(source, "2b", validator, Event())
    if valid:
        raise SystemExit("veraPDF accepted the ordinary source PDF as PDF/A-2b.")
    print(f"Ordinary source PDF correctly rejected: {details}")
    for label, profile in FORMATS.items():
        output = folder / f"{profile}.pdf"
        convert(source, output, label, gs, Event())
        valid, details = validate(output, profile, validator, Event())
        if not valid:
            raise SystemExit(f"{label} failed veraPDF: {details}")
        print(f"{label}: verified ({details})")

