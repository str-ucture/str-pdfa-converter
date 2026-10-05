# Changelog

All notable changes to this project are documented here. Versioning follows
[Semantic Versioning](https://semver.org/) (MAJOR.MINOR.PATCH): PATCH for
bug fixes, MINOR for backwards-compatible features, MAJOR for breaking
changes. The version shown in the app's title bar and About window comes
from `<Version>` in `src/StrPdf/StrPdf.csproj`.

## [3.1.0] - 2026-09-28

### Added
- Brand color tokens (`Brand.xaml`) so the app's pink/danger/tertiary colors are defined once and reused everywhere, instead of repeated hex codes.
- A new app icon (accurate "str./pdf" wordmark) replacing the old plain-font one, with a theme-aware in-app title bar icon (pink "str.", theme text color "pdf" so it's visible in dark mode).
- `Ctrl+Shift+O` shortcut to add a folder, alongside the existing `Ctrl+O` for files.
- Per-row "Convert & Save As" button in the file table: converts just that file and lets you choose where to save it via a standard Save As dialog, independent of the "Save to" panel.
- "Reset to defaults" option in the "..." menu, with a confirmation dialog, resetting save location/format/subfolder/theme preferences.
- A confirmation dialog before "Next to the original" conversions, so creating many new files isn't a surprise (matching the existing "Overwrite" confirmation).
- Short, categorized failure reasons (e.g. "Password-protected PDF", "Not PDF/A compliant") in the Output file column for failed conversions, with plain-language fix tips on hover and in the log window.
- A global crash-recovery dialog: an unhandled error now offers Copy details / Close app / Continue instead of silently crashing.

### Fixed
- Crash when opening the License and notices window (bad `Markdig.Wpf` resource reference).
- Crash when opening the "..." menu (WPF `ContextMenu`/`Popup` timing race).
- Rare crash when switching away from "Use system setting" theme immediately after startup.
- Corrected "adds `_pdfa`" naming text (was showing a nonexistent double-underscore suffix).

### Changed
- Various visual polish: button hover/pressed colors, title bar text and icon sizing, table column spacing so the last row buttons aren't clipped.

## [3.0.0] - 2026-09

Baseline release: offline Treeview UI, `src` package layout.
