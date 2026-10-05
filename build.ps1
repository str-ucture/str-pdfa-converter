<#
.SYNOPSIS
    Builds the production release: tests, portable folder, licences, source archive, smoke check, screenshots, ZIP + SHA-256.
.EXAMPLE
    ./build.ps1                         # full release build from a clean, committed tree
    ./build.ps1 -SkipScreenshots        # same, without refreshing docs/screenshots
    ./build.ps1 -AllowDirty -SkipTests  # quick local build with uncommitted changes
.NOTES
    Code signing is optional: set STR_PDF_SIGN_THUMBPRINT to the SHA-1 thumbprint of a code-signing
    certificate in your certificate store (or pass -CertThumbprint) and the exe is signed and timestamped.
#>
param(
    [switch]$SkipTests,
    [switch]$SkipScreenshots,
    [switch]$AllowDirty,
    [string]$CertThumbprint = $env:STR_PDF_SIGN_THUMBPRINT,
    [string]$TimestampUrl = 'http://timestamp.digicert.com'
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$runtime = Join-Path $root 'runtime'
$dist = Join-Path $root 'dist'
$bundle = Join-Path $dist 'str-pdf'
function Step([string]$Text) { Write-Host "`n== $Text" -ForegroundColor Cyan }

Step 'Checking prerequisites'
$required = @{
    'Ghostscript executable'   = 'ghostscript\bin\gswin64c.exe'
    'Ghostscript sRGB profile' = 'ghostscript\iccprofiles\srgb.icc'
    'Ghostscript licence'      = 'ghostscript\doc\COPYING'
    'veraPDF'                  = 'verapdf\bin\*.jar'
    'Java runtime'             = 'java\bin\java.exe'
    'Java licences'            = 'java\legal'
}
$missing = $required.GetEnumerator() | Where-Object { -not (Test-Path (Join-Path $runtime $_.Value)) } | ForEach-Object Key
if ($missing) { throw "Missing runtime components:`n  - $($missing -join "`n  - ")`n`nSet up runtime\ as described in docs/DEVELOPMENT.md, then build again." }
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) { throw 'The .NET 10 SDK is not installed (https://dotnet.microsoft.com/download).' }
$dirty = git -C $root status --porcelain --untracked-files=no
if ($dirty -and -not $AllowDirty) { throw "Uncommitted changes. Commit them first (the release includes the committed source), or pass -AllowDirty for a local test build.`n$($dirty -join "`n")" }
[xml]$project = Get-Content (Join-Path $root 'src\StrPdf\StrPdf.csproj')
$version = $project.Project.PropertyGroup.Version | Where-Object { $_ } | Select-Object -First 1
Write-Host "Version $version, commit $(git -C $root rev-parse --short HEAD)$(if ($dirty) { ' + uncommitted changes' })"

if (-not $SkipTests) {
    Step 'Running unit tests'
    dotnet test (Join-Path $root 'tests\StrPdf.Tests') --nologo -v quiet
    if ($LASTEXITCODE) { throw 'Unit tests failed.' }
}

Step 'Publishing str-pdf.exe'
if (Test-Path $dist) { Remove-Item $dist -Recurse -Force }
# Compression: 132 MB -> 61 MB exe for ~0.2 s slower startup; ReadyToRun adds size without a startup gain here.
dotnet publish (Join-Path $root 'src\StrPdf') -c Release -r win-x64 --self-contained --nologo -v quiet `
    -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -p:EnableCompressionInSingleFile=true `
    -p:DebugType=none -o $bundle
if ($LASTEXITCODE) { throw 'dotnet publish failed.' }
# Named with the version so the exe is self-describing if shipped or archived on its own, outside the zip.
$exeName = "str-pdf-$version.exe"
Rename-Item (Join-Path $bundle 'str-pdf.exe') $exeName
$exe = Join-Path $bundle $exeName

if ($CertThumbprint) {
    Step 'Signing str-pdf.exe'
    $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $signtool) { throw 'signtool.exe not found. Install the Windows SDK "Signing Tools" component.' }
    & $signtool.FullName sign /sha1 $CertThumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 /d 'PDF to PDF/A Converter' $exe
    if ($LASTEXITCODE) { throw 'Signing failed.' }
}
else {
    Write-Host 'Not signed (no certificate configured). Users will see a SmartScreen prompt on first run.' -ForegroundColor Yellow
}

Step 'Copying engines, licences, and source'
robocopy $runtime (Join-Path $bundle 'runtime') /E /NFL /NDL /NJH /NJS /NP /XD Uninstaller /XF .installationinformation | Out-Null
if ($LASTEXITCODE -ge 8) { throw 'Copying runtime\ failed.' }
foreach ($doc in 'README.md', 'NOTICE.md', 'THIRD_PARTY_NOTICES.md', 'LICENSE') {
    Copy-Item (Join-Path $root $doc) (Join-Path $bundle ([IO.Path]::GetFileNameWithoutExtension($doc) + '.txt'))
}
Copy-Item (Join-Path $root 'licenses') (Join-Path $bundle 'licenses') -Recurse
# veraPDF ships as one jar; its bundled libraries' licence and notice files live inside it.
Add-Type -AssemblyName System.IO.Compression.FileSystem
$bundled = New-Item -ItemType Directory (Join-Path $bundle 'licenses\verapdf-bundled') -Force
foreach ($jar in Get-ChildItem (Join-Path $runtime 'verapdf\bin\*.jar')) {
    $zip = [IO.Compression.ZipFile]::OpenRead($jar.FullName)
    try {
        foreach ($entry in $zip.Entries | Where-Object { $_.FullName -match '^META-INF/[^/]*(LICEN[CS]E|NOTICE)[^/]*$' }) {
            $name = if ($entry.Name.EndsWith('.txt')) { $entry.Name } else { "$($entry.Name).txt" }  # LICENSE, LICENSE.md, LICENSE.txt stay distinct
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, (Join-Path $bundled $name), $true)
        }
    }
    finally { $zip.Dispose() }
}
# AGPL: every copy of the program comes with its corresponding source.
# Zips the working tree (tracked + new, minus .gitignore) so it matches exactly what was built.
New-Item -ItemType Directory (Join-Path $bundle 'source') | Out-Null
$sources = git -C $root ls-files --cached --others --exclude-standard | Where-Object { Test-Path (Join-Path $root $_) }
$archive = [IO.Compression.ZipFile]::Open((Join-Path $bundle 'source\str-pdf-source.zip'), 'Create')
try { foreach ($file in $sources) { [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, (Join-Path $root $file), $file) | Out-Null } }
finally { $archive.Dispose() }

Step 'Smoke check (real conversion and validation)'
$smoke = Start-Process $exe -ArgumentList '--smoke-check' -NoNewWindow -Wait -PassThru
if ($smoke.ExitCode) { throw "The bundled smoke check failed (exit code $($smoke.ExitCode))." }

if (-not $SkipScreenshots) {
    Step 'Screenshots (hands off mouse and keyboard for about a minute)'
    & (Join-Path $root 'tools\screenshots.ps1') -Exe $exe
}

Step 'Packaging'
$zipName = "str-pdf-$version-windows-x64.zip"
$zipPath = Join-Path $dist $zipName
Compress-Archive -Path $bundle -DestinationPath $zipPath
$hash = (Get-FileHash $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content "$zipPath.sha256" "$hash  $zipName" -Encoding ascii
$size = '{0:n0} MB' -f ((Get-Item $zipPath).Length / 1MB)
Write-Host "`nRelease $version ready.`n  Folder:  $bundle`n  Archive: $zipPath ($size)`n  SHA-256: $hash" -ForegroundColor Green
exit 0  # robocopy leaves LASTEXITCODE=1 ("files copied") on success
