# str-pdf

Offline desktop conversion from PDF to PDF/A with independent veraPDF verification.

## Use

Download the folder for your operating system, extract it, and launch `str-pdf.exe` (Windows), `str-pdf` (Linux), or `str-pdf.app` (macOS, once notarized). The release folder includes Python, Ghostscript, veraPDF, and Java. No account, key, separate runtime installation, or network connection is required for conversion.

Add PDFs with **Add PDF(s)…** (Ctrl+O), **Add Folder…** (tick **Include subfolders** to search recursively), or drag and drop. Select rows (Shift/Ctrl-click, Ctrl+A) for **Convert Selected** or **Remove Selected** (Delete); **Convert All & Verify** processes the whole list. Click a column header to sort. Double-click a converted row to open the result, or right-click for **Show in Folder**. The panel under the list shows the selected file's output path and, for failures, the veraPDF rules that failed.

Under **Save to**, choose **Next to original** (saves `name_pdfa.pdf` beside the source), **Folder**, or **Overwrite original**. Overwrite asks for confirmation and only replaces each original after conversion and verification pass. Select PDF/A-1b, 2b (recommended), or 3b. A file is marked **Verified** (green) only when veraPDF passes the matching profile. If different input files share a name, later outputs receive numbered copy names so they do not replace one another. A pop-up appears only when some files need attention; a clean run is reported in the status bar.

Conversion settings are saved in the operating system's per-user application settings folder. Files and settings are not uploaded.

## Build

Build on each target operating system; PyInstaller does not create portable executables for other operating systems. Install Python 3.13 with Tk support, then install the project with its build tools:

```text
python -m pip install -e ".[build]"
```

Place complete, compatible runtime distributions here before building:

```text
runtime/
  ghostscript/   # Full Ghostscript distribution, including bin/ and iccprofiles/srgb.icc
  verapdf/       # veraPDF installation tree, including bin/verapdf[.bat]
  java/          # Java runtime tree, including bin/java[.exe]
```

Review the engine licenses and notices before distributing a build. Then run:

```text
python build.py --clean
```

The portable folder is created in `dist/str-pdf/`, with a matching ZIP named for the operating system and CPU architecture. Test the folder on a clean machine for the same operating system and CPU architecture. Build the Windows, Intel macOS, Apple Silicon macOS, and Linux variants on native runners.

## Development

```text
src/str_pdf/     app.py (Tkinter UI), conversion.py (Ghostscript + veraPDF), smoke.py, __main__.py
tests/           unit tests (standard-library unittest)
assets/          app icon and screenshot
build.py         portable-folder build
```

```text
python -m str_pdf                          # run the app
python -m unittest discover -s tests       # unit tests
python -m str_pdf --smoke-check            # real conversion + validation with the staged engines
```

The smoke check proves that an ordinary PDF fails the PDF/A check and that generated PDF/A-1b, 2b, and 3b files pass veraPDF. The packaged executable supports `--smoke-check` too, for checking a runtime bundle. The original v1 implementation is available in git history (commit `872ede7`).
