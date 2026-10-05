<#
.SYNOPSIS
    Drives the app with UI Automation and saves screenshots of every screen, menu, and dialog, in light and dark theme.
.DESCRIPTION
    Uses its own temporary settings, sample PDFs, and output folder; your settings and files are not touched.
    Needs an unlocked desktop: keep hands off the mouse and keyboard for about a minute while it runs.
.EXAMPLE
    ./tools/screenshots.ps1                                  # uses dist\str-pdf\str-pdf.exe, or the Debug build
    ./tools/screenshots.ps1 -Exe path\to\str-pdf.exe -Out docs\screenshots
#>
param(
    [string]$Exe,
    [string]$Out = (Join-Path $PSScriptRoot '..\docs\screenshots'),
    [string[]]$Themes = @('light', 'dark')
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $Exe) {
    # The release build names the exe str-pdf-<version>.exe; the Debug build stays str-pdf.exe.
    $Exe = @(Get-ChildItem "$root\dist\str-pdf\str-pdf*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName) +
        "$root\src\StrPdf\bin\Debug\net10.0-windows\str-pdf.exe" | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Exe -or -not (Test-Path $Exe)) { throw 'str-pdf.exe not found. Build first (./build.ps1 or dotnet build src/StrPdf), or pass -Exe.' }

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Drawing, System.Windows.Forms
Add-Type @'
using System; using System.Runtime.InteropServices;
public static class Native {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, IntPtr e);
    [DllImport("dwmapi.dll")] public static extern int DwmGetWindowAttribute(IntPtr h, int a, out RECT r, int s);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
    public static void RightClick(int x, int y) { SetCursorPos(x, y); mouse_event(8, 0, 0, 0, IntPtr.Zero); mouse_event(16, 0, 0, 0, IntPtr.Zero); }
}
'@
[Native]::SetProcessDPIAware() | Out-Null
$A = [System.Windows.Automation.AutomationElement]
$Scope = [System.Windows.Automation.TreeScope]

$work = Join-Path ([IO.Path]::GetTempPath()) "str-pdf-shots-$PID"
New-Item -ItemType Directory $work, $Out -Force | Out-Null
$Out = (Resolve-Path $Out).Path
& (Join-Path $PSScriptRoot 'make-samples.ps1') -Out "$work\samples" | Out-Null

function Wait-For([scriptblock]$Condition, [string]$What, [int]$Seconds = 60) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        $result = try { & $Condition } catch { $null }  # UI Automation can fail while windows open or close
        if ($result) { return $result }
        Start-Sleep -Milliseconds 200
    }
    throw "Timed out waiting for $What."
}

function Start-App([string]$Theme, [switch]$WithSamples) {
    # A private %APPDATA% gives the app fresh settings without touching the real ones.
    $appData = "$work\appdata-$Theme"
    Remove-Item $appData, "$work\out" -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory "$appData\str-pdf", "$work\out" -Force | Out-Null
    @{ output_directory = "$work\out"; output_mode = 'folder'; pdfa_version = 'PDF/A-2b'; include_subfolders = $true; theme = $Theme } |
        ConvertTo-Json | Set-Content "$appData\str-pdf\settings.json" -Encoding ascii
    $saved = $env:APPDATA
    $env:APPDATA = $appData
    try {
        $script:proc = if ($WithSamples) { Start-Process $Exe -ArgumentList "`"$work\samples`"" -PassThru } else { Start-Process $Exe -PassThru }
    }
    finally { $env:APPDATA = $saved }
    $script:win = Wait-For { $script:proc.Refresh(); if ($script:proc.MainWindowHandle -ne 0) { $A::FromHandle($script:proc.MainWindowHandle) } } 'the main window'
    Start-Sleep -Milliseconds 1200
}

function Stop-App { if ($script:proc -and -not $script:proc.HasExited) { Stop-Process $script:proc -Force; $script:proc.WaitForExit() } }

function Find([string]$Id) { $script:win.FindFirst($Scope::Descendants, [System.Windows.Automation.PropertyCondition]::new($A::AutomationIdProperty, $Id)) }

# Menus and dialogs are separate top-level windows of the app process.
# Searching only the app's own top-level windows avoids other apps' (sometimes faulty) automation providers.
function Find-Anywhere([string]$Name) {
    $mine = [System.Windows.Automation.PropertyCondition]::new($A::ProcessIdProperty, $script:proc.Id)
    $named = [System.Windows.Automation.PropertyCondition]::new($A::NameProperty, $Name)
    try {
        foreach ($window in $A::RootElement.FindAll($Scope::Children, $mine)) {
            if ($window.Current.Name -eq $Name) { return $window }
            $found = $window.FindFirst($Scope::Descendants, $named)
            if ($found) { return $found }
        }
    }
    catch [System.Runtime.InteropServices.COMException], [System.Windows.Automation.ElementNotAvailableException] { }  # window changing; Wait-For retries
    $null
}

function Invoke-Element($Element) { $Element.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke(); Start-Sleep -Milliseconds 500 }
function Click([string]$Id) { Invoke-Element (Find $Id) }
function Press([string]$Name) { Invoke-Element (Wait-For { Find-Anywhere $Name } "the '$Name' button") }
function Keys([string]$Keys) { [Native]::SetForegroundWindow($script:proc.MainWindowHandle) | Out-Null; [System.Windows.Forms.SendKeys]::SendWait($Keys); Start-Sleep -Milliseconds 400 }

function Shot([string]$Name) {
    $handle = $script:proc.MainWindowHandle
    [Native]::SetForegroundWindow($handle) | Out-Null
    Start-Sleep -Milliseconds 600
    $r = New-Object Native+RECT
    [Native]::DwmGetWindowAttribute($handle, 9, [ref]$r, 16) | Out-Null  # visible frame, without the invisible resize border
    $bitmap = New-Object System.Drawing.Bitmap ($r.R - $r.L), ($r.B - $r.T)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.CopyFromScreen($r.L, $r.T, 0, 0, $bitmap.Size)
    $file = Join-Path $Out "$Name-$theme.png"
    $bitmap.Save($file, [System.Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose(); $bitmap.Dispose()
    Write-Host "  $([IO.Path]::GetFileName($file))"
}

function Open-More { Click 'MoreButton'; Wait-For { Find-Anywhere 'About' } 'the … menu' | Out-Null }

try {
    foreach ($theme in $Themes) {
        Write-Host "Theme: $theme"

        Start-App $theme
        Shot 'main-empty'
        Open-More; Shot 'menu-more'
        $themeItem = Wait-For { Find-Anywhere 'Theme' } 'the Theme menu item'
        $themeItem.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern).Expand()
        Wait-For { Find-Anywhere 'Use system setting' } 'the Theme submenu' | Out-Null
        Shot 'menu-theme'
        Keys '{ESC}'; Keys '{ESC}'
        Open-More; Invoke-Element (Find-Anywhere 'About')
        Wait-For { Find-Anywhere 'Copy email' } 'the About dialog' | Out-Null
        Shot 'dialog-about'
        Press 'Close'
        Open-More; Invoke-Element (Find-Anywhere 'License and notices')
        $license = Wait-For { Find-Anywhere 'License and notices' | Where-Object { $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Window } } 'the license window'
        Shot 'dialog-license'
        $license.GetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern).Close()
        Stop-App

        Start-App $theme -WithSamples
        Shot 'main-queued'
        Click 'ConvertAllButton'
        Wait-For { (Find 'StatusText').Current.Name -match 'converted and verified' } 'the batch to finish' 180 | Out-Null
        Wait-For { Find-Anywhere 'OK' } 'the "files need attention" dialog' | Out-Null
        Shot 'dialog-attention'
        Press 'OK'

        $rows = (Find 'FileList').FindAll($Scope::Children, [System.Windows.Automation.PropertyCondition]::new($A::ControlTypeProperty, [System.Windows.Automation.ControlType]::DataItem))
        $failed = $rows[1]  # broken-truncated.pdf: rows are sorted by path
        $failed.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()
        Shot 'results'
        $point = $failed.GetClickablePoint()
        [Native]::RightClick([int]$point.X, [int]$point.Y)
        Wait-For { Find-Anywhere 'Show in folder' } 'the row menu' | Out-Null
        Shot 'menu-row'
        Keys '{ESC}'

        Click 'LogButton'; Shot 'main-log'; Click 'LogButton'

        Click 'ConvertAllButton'
        Wait-For { Find-Anywhere 'Create copies' } 'the "files already exist" dialog' | Out-Null
        Shot 'dialog-conflict'
        Press 'Cancel'

        (Find 'OverwriteRadio').GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()
        Click 'ConvertAllButton'
        Wait-For { Find-Anywhere 'Overwrite' } 'the overwrite confirmation' | Out-Null
        Shot 'dialog-overwrite'
        Press 'Cancel'
        Stop-App
    }
}
finally {
    Stop-App
    Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Host "Screenshots saved to $Out"
