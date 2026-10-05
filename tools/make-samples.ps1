<#
.SYNOPSIS
    Generates test PDFs (good, broken, locked, odd names, subfolders) with the bundled Ghostscript.
.EXAMPLE
    ./tools/make-samples.ps1              # writes samples/ in the repository root
    ./tools/make-samples.ps1 -Out C:\tmp\pdfs
#>
param([string]$Out = (Join-Path $PSScriptRoot '..\samples'))
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
$gs = Join-Path $root 'runtime\ghostscript\bin\gswin64c.exe'
$icc = Join-Path $root 'runtime\ghostscript\iccprofiles\srgb.icc'
if (-not (Test-Path $gs)) { throw "Ghostscript not found at $gs. Set up runtime\ first (see docs/DEVELOPMENT.md)." }

if (Test-Path $Out) { Remove-Item $Out -Recurse -Force }
New-Item -ItemType Directory (Join-Path $Out 'subfolder\deeper') -Force | Out-Null
$work = Join-Path ([IO.Path]::GetTempPath()) "str-pdf-samples-$PID"
New-Item -ItemType Directory $work -Force | Out-Null

function Invoke-Gs([string]$PostScript, [string]$Target, [string[]]$Extra = @()) {
    $source = Join-Path $work ([IO.Path]::GetRandomFileName() + '.ps')
    [IO.File]::WriteAllText($source, "%!PS-Adobe-3.0`n$PostScript", [Text.Encoding]::GetEncoding(28591))
    & $gs -q -dSAFER -dBATCH -dNOPAUSE -sDEVICE=pdfwrite "-sOutputFile=$Target" @Extra $source
    if ($LASTEXITCODE) { throw "Ghostscript failed for $Target" }
}

function Page([string]$Title, [string[]]$Lines, [string]$Footer = '') {
    $ps = "/Helvetica-Bold findfont 22 scalefont setfont 72 720 moveto ($Title) show`n/Helvetica findfont 11 scalefont setfont`n"
    $y = 690
    foreach ($line in $Lines) { $ps += "72 $y moveto ($line) show`n"; $y -= 16 }
    if ($Footer) { $ps += "/Helvetica-Oblique findfont 9 scalefont setfont 72 40 moveto ($Footer) show`n" }
    "${ps}showpage`n"
}

$text = @(
    'This sample was generated for manual testing of the PDF/A converter.',
    'It is an ordinary PDF: no output intent and no PDF/A metadata, so it is not PDF/A.',
    'Converting it should produce a verified PDF/A file.')

Invoke-Gs (Page 'Simple letter' $text) (Join-Path $Out 'simple-letter.pdf')
Invoke-Gs (Page 'Unembedded font' (@('Helvetica is referenced but not embedded.') + $text)) (Join-Path $Out 'unembedded-font.pdf') `
    @('-c', '<< /NeverEmbed [/Helvetica /Helvetica-Bold] >> setdistillerparams', '-f')

$report = foreach ($n in 1..12) {
    $rows = foreach ($r in 1..30) { 'Row {0:00}    Item {1}-{0}    {2,3} units    EUR {3,8:0.00}' -f $r, $n, ($r * 17 % 97), ($r * 12.5) }
    Page "Quarterly report - page $n of 12" $rows 'str.ucture GmbH - sample report'
}
Invoke-Gs ($report -join '') (Join-Path $Out 'multi-page-report.pdf')

Invoke-Gs @'
/Helvetica-Bold findfont 28 scalefont setfont
0 0 0 1 setcmykcolor 72 720 moveto (CMYK print flyer) show
1 0 0 0 setcmykcolor 72 420 150 250 rectfill
0 1 0 0 setcmykcolor 232 420 150 250 rectfill
0 0 1 0 setcmykcolor 392 420 150 250 rectfill
0.2 0.8 0.6 0.1 setcmykcolor 306 250 120 0 360 arc fill
showpage
'@ (Join-Path $Out 'cmyk-print-flyer.pdf') @('-sColorConversionStrategy=LeaveColorUnchanged')

Invoke-Gs @'
/w 300 def /h 400 def /row w 3 mul string def /y 0 def
36 36 translate 540 720 scale
w h 8 [w 0 0 h neg 0 h]
{ 0 1 w 1 sub { /x exch def
    row x 3 mul       x 255 mul w idiv put
    row x 3 mul 1 add y 255 mul h idiv put
    row x 3 mul 2 add x y add 7 mul 256 mod put } for
  /y y 1 add def row }
false 3 colorimage
showpage
'@ (Join-Path $Out 'scanned-image.pdf')

Invoke-Gs (Page 'Rechnung' (@('File name with spaces, umlauts and parentheses.') + $text)) (Join-Path $Out 'Rechnung Übersicht 2026 (Kopie).pdf')
Invoke-Gs ((1..100 | ForEach-Object { Page "Long document - page $_" $text }) -join '') (Join-Path $Out 'long-100-pages.pdf')
Invoke-Gs (Page 'Password protected' (@('Open password: test') + $text)) (Join-Path $Out 'password-protected.pdf') `
    @('-sOwnerPassword=owner', '-sUserPassword=test', '-dEncryptionR=3', '-dKeyLength=128')

# Already PDF/A-2b, made the same way the app converts.
$definition = Join-Path $work 'pdfa.ps'
$iccPs = $icc.Replace('\', '\\').Replace('(', '\(').Replace(')', '\)')
[IO.File]::WriteAllText($definition, @"
%!PS-Adobe-3.0
/ICCProfile ($iccPs) def
[/_objdef {icc_PDFA} /type /stream /OBJ pdfmark
[{icc_PDFA} << /N 3 >> /PUT pdfmark
[{icc_PDFA} ICCProfile (r) file /PUT pdfmark
[/_objdef {OutputIntent_PDFA} /type /dict /OBJ pdfmark
[{OutputIntent_PDFA} << /Type /OutputIntent /S /GTS_PDFA1 /DestOutputProfile {icc_PDFA} /OutputConditionIdentifier (sRGB) >> /PUT pdfmark
[{Catalog} <</OutputIntents [ {OutputIntent_PDFA} ]>> /PUT pdfmark
"@, [Text.Encoding]::ASCII)
& $gs -q -dSAFER -dBATCH -dNOPAUSE -dPDFA=2 -dPDFACompatibilityPolicy=2 -sDEVICE=pdfwrite -sColorConversionStrategy=RGB -sProcessColorModel=DeviceRGB `
    "-sOutputFile=$(Join-Path $Out 'already-pdfa-2b.pdf')" "--permit-file-read=$icc" $definition (Join-Path $Out 'simple-letter.pdf')

$bytes = [IO.File]::ReadAllBytes((Join-Path $Out 'multi-page-report.pdf'))
[IO.File]::WriteAllBytes((Join-Path $Out 'broken-truncated.pdf'), $bytes[0..([int]($bytes.Length / 3))])
[IO.File]::WriteAllText((Join-Path $Out 'not-really-a-pdf.pdf'), "This is a plain text file with a .pdf extension.`n")

Invoke-Gs (Page 'Nested invoice' $text) (Join-Path $Out 'subfolder\nested-invoice.pdf')
Invoke-Gs (Page 'Deeper archive' $text) (Join-Path $Out 'subfolder\deeper\deeper-archive.pdf')

[IO.File]::WriteAllText((Join-Path $Out 'README.txt'), @'
Manual test PDFs, generated by tools/make-samples.ps1 (not committed to git).

Expected result of "Convert all & verify" with "Include subfolders" ticked (13 files):
  Verified           simple-letter, unembedded-font, multi-page-report, cmyk-print-flyer,
                     scanned-image, Rechnung Übersicht 2026 (Kopie), long-100-pages,
                     already-pdfa-2b, subfolder/nested-invoice, subfolder/deeper/deeper-archive
  Conversion failed  broken-truncated, not-really-a-pdf, password-protected (password: test)

Things to try:
  - Add folder on samples/ with and without "Include subfolders" (11 vs 13 files)
  - Convert twice with "Next to the original" to see the "files already exist" dialog
  - Start long-100-pages and press Cancel
  - Drag the whole folder onto the window, or onto str-pdf.exe
'@, [Text.UTF8Encoding]::new($false))

Remove-Item $work -Recurse -Force
Write-Host "Sample PDFs written to $(Resolve-Path $Out)"
