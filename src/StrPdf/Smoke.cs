using System.Text;
using System.Windows;
using System.Windows.Documents;
using System.Windows.Media;
using Wpf.Ui.Appearance;
using Wpf.Ui.Controls;

namespace StrPdf;

/// <summary>`str-pdf --smoke-check`: proves the bundled engines reject a plain PDF and produce verified PDF/A-1b, 2b and 3b.</summary>
public static class Smoke
{
    /// <summary>Constructs every window in Light and Dark theme (never shown) to catch XAML/resource
    /// bugs that only surface at runtime - an invalid property value (XamlParseException) or a
    /// hardcoded color that goes invisible in dark mode - before they reach a release build.</summary>
    public static int CheckWindows(TextWriter output)
    {
        foreach (var theme in new[] { ApplicationTheme.Light, ApplicationTheme.Dark })
        {
            try
            {
                ApplicationThemeManager.Apply(theme, WindowBackdropType.None, true);
                _ = new MainWindow([]);
                // MainWindow applies the user's own saved theme preference on construction (often
                // "System"), which can override the forced theme above - reassert it so the checks
                // below are deterministic regardless of the developer machine's OS theme setting.
                ApplicationThemeManager.Apply(theme, WindowBackdropType.None, true);
                _ = new AboutWindow("0.0.0-smoke");
                var license = new LicenseWindow();
                _ = new LogWindow();

                var text = ((SolidColorBrush)App.Current.Resources["TextFillColorPrimaryBrush"]).Color;
                if (LooksHardcoded(text, theme))
                {
                    output.WriteLine($"{theme}: primary text color is {text}, which would be unreadable - check for a hardcoded Foreground.");
                    return 1;
                }
                // The Markdig.Wpf package's own default heading styles hardcode Foreground="#ff000000"
                // (see LicenseWindow.xaml's overrides) - check each one directly, since a hardcoded
                // heading color wouldn't show up in the app-wide TextFillColorPrimaryBrush check above.
                foreach (var key in new object[]
                {
                    Markdig.Wpf.Styles.Heading1StyleKey, Markdig.Wpf.Styles.Heading2StyleKey,
                    Markdig.Wpf.Styles.Heading3StyleKey, Markdig.Wpf.Styles.Heading4StyleKey,
                })
                {
                    if (license.TryFindResource(key) is not Style style)
                        continue;
                    var fg = (style.Setters.OfType<Setter>().FirstOrDefault(s => s.Property == Paragraph.ForegroundProperty)?.Value as SolidColorBrush)?.Color;
                    if (fg is { } color && LooksHardcoded(color, theme))
                    {
                        output.WriteLine($"{theme}: a markdown heading's Foreground is {color}, which would be unreadable.");
                        return 1;
                    }
                }
            }
            catch (Exception ex)
            {
                output.WriteLine($"{theme}: a window failed to construct: {ex}");
                return 1;
            }
            output.WriteLine($"{theme}: all windows constructed OK.");
        }
        return 0;
    }

    /// <summary>True if a color is suspiciously stuck at the wrong end of the brightness range for
    /// its theme - e.g. near-black text on Dark, or near-white text on Light - which is what a
    /// hardcoded (theme-blind) Foreground looks like.</summary>
    static bool LooksHardcoded(Color color, ApplicationTheme theme) => theme switch
    {
        ApplicationTheme.Dark => color.R < 0x40 && color.G < 0x40 && color.B < 0x40,
        _ => color.R > 0xC0 && color.G > 0xC0 && color.B > 0xC0,
    };

    public static async Task<int> RunAsync(TextWriter output)
    {
        if (Engines.MissingEngine() is { } missing)
        {
            output.WriteLine($"Smoke check needs {missing} under {Path.Combine(Engines.Root, "runtime")}.");
            return 2;
        }
        var folder = Directory.CreateTempSubdirectory("str-pdf-smoke-").FullName;
        try
        {
            var source = Path.Combine(folder, "sample.pdf");
            await File.WriteAllBytesAsync(source, SamplePdf());
            var plain = (await Engines.ValidateAsync([source], "2b", CancellationToken.None))[source];
            if (plain.Compliant)
            {
                output.WriteLine("veraPDF accepted the ordinary source PDF as PDF/A-2b.");
                return 1;
            }
            output.WriteLine($"Ordinary source PDF correctly rejected:\n{plain.Details}");
            foreach (var (label, profile) in Engines.Formats)
            {
                var converted = Path.Combine(folder, $"{profile}.pdf");
                await Engines.ConvertAsync(source, converted, label, CancellationToken.None);
                var result = (await Engines.ValidateAsync([converted], profile, CancellationToken.None))[converted];
                if (!result.Compliant)
                {
                    output.WriteLine($"{label} failed veraPDF: {result.Details}");
                    return 1;
                }
                output.WriteLine($"{label}: verified");
            }
            return 0;
        }
        catch (ToolException ex)
        {
            output.WriteLine($"Smoke check failed: {ex.Message}");
            return 1;
        }
        finally
        {
            Directory.Delete(folder, recursive: true);
        }
    }

    /// <summary>A one-page PDF with an unembedded Helvetica font, so it is deliberately not PDF/A.</summary>
    static byte[] SamplePdf()
    {
        const string stream = "BT /F1 18 Tf 72 720 Td (PDF-A check) Tj ET";
        string[] objects =
        [
            "<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            $"<< /Length {stream.Length} >>\nstream\n{stream}\nendstream",
        ];
        var pdf = new StringBuilder("%PDF-1.4\n");
        var offsets = new List<int>();
        for (var i = 0; i < objects.Length; i++)
        {
            offsets.Add(pdf.Length);
            pdf.Append($"{i + 1} 0 obj\n{objects[i]}\nendobj\n");
        }
        var xref = pdf.Length;
        pdf.Append($"xref\n0 {objects.Length + 1}\n0000000000 65535 f \n");
        foreach (var offset in offsets)
            pdf.Append($"{offset:D10} 00000 n \n");
        pdf.Append($"trailer\n<< /Size {objects.Length + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n");
        return Encoding.ASCII.GetBytes(pdf.ToString());
    }
}
