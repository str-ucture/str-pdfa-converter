# Third-party notices

Release builds of the PDF to PDF/A Converter include the components below. Each one is unmodified, keeps its own licence, and runs as a separate program (Ghostscript, veraPDF on Java) or as the application runtime (.NET, WPF-UI). The full licence texts are in the `licenses/` folder, and the in-app **… › License and notices** window shows all of them.

| Component | Version | Licence | Licence text in the release | Source code |
|---|---|---|---|---|
| Ghostscript (Artifex Software) | 10.06.0 | GNU AGPL v3 | `runtime/ghostscript/doc/COPYING` | <https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/tag/gs10060> |
| veraPDF CLI (veraPDF Consortium) | 1.30.2 | MPL 2.0 (chosen from its MPL 2.0 / GPL v3+ dual licence) | `licenses/verapdf-MPL-2.0.txt`; bundled libraries: `licenses/verapdf-bundled/` | <https://github.com/veraPDF/veraPDF-apps> |
| Java runtime (OpenJDK) | 17.0.18 | GNU GPL v2 with the Classpath Exception | `runtime/java/legal/` | <https://github.com/openjdk/jdk17u> |
| .NET runtime and WPF (.NET Foundation) | 10.0 | MIT | `licenses/dotnet-MIT.txt`, `licenses/dotnet-runtime-THIRD-PARTY-NOTICES.txt`, `licenses/dotnet-wpf-THIRD-PARTY-NOTICES.txt` | <https://github.com/dotnet/runtime>, <https://github.com/dotnet/wpf> |
| WPF-UI (Leszek Pomianowski and contributors) | 4.3.0 | MIT | `licenses/wpf-ui-MIT.txt` | <https://github.com/lepoco/wpfui> |
| Markdig.Wpf (Markdig.Wpf contributors) | 0.5.0.1 | MIT | `licenses/markdig-wpf-MIT.txt` | <https://github.com/Kryptos-FR/markdig.wpf> |

The sRGB colour profile embedded in converted files is Ghostscript's `iccprofiles/srgb.icc` and is covered by the Ghostscript licence.

## Source code

- **This application:** the complete source code of the exact build is in `source/str-pdf-source.zip` inside the release folder. It is also available from str.ucture GmbH on request (info@str-ucture.com) for at least three years after the release.
- **Ghostscript, veraPDF, OpenJDK, .NET, WPF-UI:** the versions listed above are official, unmodified releases. Their source code is available at the links in the table. str.ucture GmbH will also provide a copy on request under the same terms.

## Updating a component

When an engine is upgraded, update the version in this table, check that its licence has not changed, and rebuild with `build.ps1`, which copies the licence files into the release.
