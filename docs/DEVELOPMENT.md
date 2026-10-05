# For maintainers

How to build, test, and release the PDF to PDF/A Converter. End-user instructions are in the [README](../README.md).

## One-time setup

1. Install the [.NET 10 SDK](https://dotnet.microsoft.com/download) (Windows x64).
2. Put the three engines in `runtime/` in the repository root. This folder is git-ignored because it is ~170 MB:

   ```text
   runtime/
     ghostscript/   Ghostscript 10.06.0 for Windows (64-bit): bin/gswin64c.exe, iccprofiles/srgb.icc, doc/COPYING
     verapdf/       veraPDF 1.30.2 (greenfield installation): bin/*.jar
     java/          Java 17 runtime: bin/java.exe, legal/
   ```

   The quickest way is to copy `runtime/` from the latest release folder. To upgrade an engine, replace its folder and update the version in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## Everyday commands

```powershell
dotnet run --project src/StrPdf                     # run the app (it finds runtime/ in the repo root)
dotnet run --project src/StrPdf -- samples          # run it with the sample PDFs already added
dotnet test                                         # unit tests
dotnet run --project src/StrPdf -- --smoke-check    # real conversion + validation with the engines
./tools/make-samples.ps1                            # (re)generate samples/: 13 good, broken, and locked test PDFs
./tools/screenshots.ps1                             # refresh docs/screenshots (light + dark)
```

`samples/README.txt` lists what each test PDF should produce.

## Making a release

1. Update `<Version>` in `src/StrPdf/StrPdf.csproj` and commit.
2. Run:

   ```powershell
   ./build.ps1
   ```

   It stops at the first problem. In order, it:
   - checks the engines are present and the working tree is committed;
   - runs the unit tests;
   - publishes a self-contained `str-pdf-<version>.exe`, and signs it if a certificate is configured;
   - copies the engines, all licence files, and a source archive (`source/str-pdf-source.zip`, required by the AGPL);
   - runs the smoke check on the finished folder;
   - refreshes `docs/screenshots/` (keep hands off the mouse and keyboard for about a minute);
   - writes `dist/str-pdf-<version>-windows-x64.zip` and its `.sha256`.
3. Commit the refreshed screenshots, tag the commit (`git tag v3.0.0`), and upload the ZIP and `.sha256` to a GitHub release.

Options: `-SkipScreenshots`, `-SkipTests`, and `-AllowDirty` for quick local builds.

### Code signing (optional)

Unsigned apps show a SmartScreen warning on first launch. To sign, install a code-signing certificate in your Windows certificate store, install the Windows SDK *Signing Tools*, and set:

```powershell
$env:STR_PDF_SIGN_THUMBPRINT = '<certificate SHA-1 thumbprint>'
./build.ps1
```

## How it works

```text
src/StrPdf/
  Engines.cs         runs Ghostscript (convert) and veraPDF (validate, many files per Java start)
  Batch.cs           convert → validate → save; parallel conversion, cancellation, naming conflicts
  Naming.cs          output paths and unique names
  Settings.cs        %APPDATA%\str-pdf\settings.json
  Smoke.cs           --smoke-check
  MainWindow.xaml    main window (WPF-UI Fluent controls)
  LicenseWindow.xaml in-app licence viewer
tests/StrPdf.Tests/  xUnit tests
tools/               sample and screenshot scripts
licenses/            licence texts shipped with every release
```

- Every file is converted to a hidden temporary file, validated by veraPDF, and only then moved into place. An original is only replaced after it passes.
- Ghostscript writes a blank page and still reports success when it cannot read a file. `Engines.UnreadableInput` catches this, so such files fail instead of being "verified".
- Conversion runs up to 4 files at a time: half the CPU cores, and at most one per 3 GB of memory. So a small laptop converts one file at a time.
- The app uses no network connection.

## Licensing

str.ucture GmbH's code is licensed under the AGPL v3 (because Ghostscript is AGPL), with the additional terms in [NOTICE.md](../NOTICE.md). Keep these rules to stay compliant:

- Ship every release with `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES`, `licenses/`, `runtime/ghostscript/doc/COPYING`, `runtime/java/legal/`, and `source/`. `build.ps1` does this.
- Don't modify the engines. If you ever have to, their modified source must be shipped too.
- Only give releases to people inside str.ucture GmbH. Giving a release to anyone outside the company is distribution under the engines' licences, so check with the maintainer first.
- Before adding a new dependency, check that its licence is compatible with the AGPL v3 and add it to `THIRD_PARTY_NOTICES.md` and `licenses/`.

The previous Python implementation (v2.1) is at commit `eb18cff`.
