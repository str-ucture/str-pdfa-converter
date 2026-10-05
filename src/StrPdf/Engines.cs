using System.Diagnostics;
using System.Text;
using System.Xml.Linq;

namespace StrPdf;

public sealed class ToolException(string message) : Exception(message);

public sealed record Validation(bool Compliant, string Details);

/// <summary>Bundled Ghostscript conversion and veraPDF validation, run as child processes.</summary>
public static class Engines
{
    public static readonly IReadOnlyDictionary<string, string> Formats = new Dictionary<string, string>
    {
        ["PDF/A-1b"] = "1b",
        ["PDF/A-2b"] = "2b",
        ["PDF/A-3b"] = "3b",
    };

    // Short-lived JVM tuning: veraPDF startup drops from ~1.3 s to ~0.8 s.
    static readonly string[] JavaStartupFlags = ["-XX:TieredStopAtLevel=1", "-XX:+UseSerialGC", "-Xshare:auto"];

    // ponytail: keeps each veraPDF command line far below Windows' 32K character limit.
    const int ValidationChunk = 50;

    /// <summary>Folder holding runtime/ and the license files: the bundle root, or the repository root in development.</summary>
    public static string Root { get; } = FindRoot();

    static string Runtime(params string[] parts) => Path.Combine([Root, "runtime", .. parts]);

    public static string? Ghostscript => FirstFile(Runtime("ghostscript", "bin", "gswin64c.exe"), Runtime("ghostscript", "gswin64c.exe"));

    public static string? Java => FirstFile(Runtime("java", "bin", "java.exe"));

    public static string? VeraPdf => Directory.Exists(Runtime("verapdf", "bin")) && Directory.EnumerateFiles(Runtime("verapdf", "bin"), "*.jar").Any() ? Runtime("verapdf") : null;

    public static string? MissingEngine() =>
        Ghostscript is null ? "Ghostscript" : Java is null ? "the Java runtime" : VeraPdf is null ? "veraPDF" : null;

    static string FindRoot()
    {
        for (var dir = new DirectoryInfo(AppContext.BaseDirectory); dir is not null; dir = dir.Parent)
        {
            if (Directory.Exists(Path.Combine(dir.FullName, "runtime")))
                return dir.FullName;
        }
        return AppContext.BaseDirectory;
    }

    static string? FirstFile(params string[] paths) => paths.FirstOrDefault(File.Exists);

    public static async Task<(int Code, string Output, string Errors)> RunAsync(string fileName, IEnumerable<string> args, CancellationToken cancel)
    {
        var info = new ProcessStartInfo(fileName)
        {
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        foreach (var arg in args)
            info.ArgumentList.Add(arg);

        using var process = new Process { StartInfo = info };
        try
        {
            process.Start();
        }
        catch (Exception ex) when (ex is System.ComponentModel.Win32Exception or InvalidOperationException)
        {
            throw new ToolException($"Could not start {Path.GetFileName(fileName)}: {ex.Message}");
        }
        var output = process.StandardOutput.ReadToEndAsync(CancellationToken.None);
        var errors = process.StandardError.ReadToEndAsync(CancellationToken.None);
        try
        {
            await process.WaitForExitAsync(cancel).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            process.Kill(entireProcessTree: true);
            throw;
        }
        return (process.ExitCode, await output.ConfigureAwait(false), await errors.ConfigureAwait(false));
    }

    public static async Task<string> ConvertAsync(string input, string output, string format, CancellationToken cancel)
    {
        var gs = Ghostscript ?? throw new ToolException("The bundled Ghostscript engine is missing.");
        var profile = Formats[format];
        var icc = FirstFile(Runtime("ghostscript", "iccprofiles", "srgb.icc"))
            ?? throw new ToolException("Ghostscript's srgb.icc profile was not found beside the bundled engine.");
        var definition = Path.Combine(Path.GetDirectoryName(output)!, $".{Path.GetFileNameWithoutExtension(output)}.pdfa.ps");
        await File.WriteAllTextAsync(definition, PdfaDefinition(icc), Encoding.ASCII, cancel).ConfigureAwait(false);
        try
        {
            var (code, stdout, stderr) = await RunAsync(gs,
            [
                "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-dNOPROMPT",
                $"-dPDFA={profile[..1]}", "-dPDFACompatibilityPolicy=2",
                "-sDEVICE=pdfwrite", "-sColorConversionStrategy=RGB", "-sProcessColorModel=DeviceRGB",
                $"-sOutputFile={output}", $"--permit-file-read={icc}", definition, input,
            ], cancel).ConfigureAwait(false);
            var log = (stdout + stderr).Trim();
            if (code != 0)
                throw new ToolException(Tail(log) is { Length: > 0 } tail ? tail : $"Ghostscript exited with code {code}.");
            if (UnreadableInput(log) is { } reason)
                throw new ToolException(reason);
            if (!File.Exists(output) || new FileInfo(output).Length == 0)
                throw new ToolException("Ghostscript did not produce an output PDF.");
            return log;
        }
        finally
        {
            File.Delete(definition);
        }
    }

    /// <summary>
    /// Ghostscript exits 0 and writes one blank, valid page when it cannot open the input at all.
    /// That blank page would pass veraPDF, so its own messages are the only signal.
    /// </summary>
    public static string? UnreadableInput(string log) =>
        log.Contains("requires a password", StringComparison.OrdinalIgnoreCase)
            ? "The file is password-protected. Remove the open password and try again."
            : log.Contains("Couldn't initialise file", StringComparison.OrdinalIgnoreCase) || log.Contains("No pages will be processed", StringComparison.OrdinalIgnoreCase)
                ? $"No pages could be read from the file.\n{Tail(log)}"
                : null;

    /// <summary>Validates every file against one profile, starting veraPDF once per chunk instead of once per file.</summary>
    public static async Task<Dictionary<string, Validation>> ValidateAsync(IReadOnlyList<string> pdfs, string profile, CancellationToken cancel)
    {
        var java = Java ?? throw new ToolException("The bundled Java runtime is missing.");
        var home = VeraPdf ?? throw new ToolException("The bundled veraPDF validator is missing.");
        var results = new Dictionary<string, Validation>(StringComparer.OrdinalIgnoreCase);
        foreach (var chunk in pdfs.Chunk(ValidationChunk))
        {
            // Same launch as veraPDF's own verapdf.bat, minus cmd.exe, so cancelling kills Java directly.
            var (code, xml, errors) = await RunAsync(java,
            [
                .. JavaStartupFlags,
                "-classpath", $"{Path.Combine(home, "etc")};{Path.Combine(home, "bin", "*")}",
                "-Dfile.encoding=UTF8", "-XX:+IgnoreUnrecognizedVMOptions",
                $"-Dapp.home={home}", $"-Dbasedir={home}", $"-Dapp.repo={Path.Combine(home, "bin")}",
                "--add-exports=java.base/sun.security.pkcs=ALL-UNNAMED",
                "org.verapdf.apps.GreenfieldCliWrapper", "--loglevel", "0", "--format", "xml", "-f", profile,
                .. chunk,
            ], cancel).ConfigureAwait(false);
            foreach (var (name, result) in ParseReport(xml, errors))
                results[Path.GetFullPath(name)] = result;
            if (code != 0 && results.Values.All(result => result.Compliant))
                throw new ToolException($"veraPDF reported success but exited with code {code}. {Tail(errors)}");
        }
        return results;
    }

    public static Dictionary<string, Validation> ParseReport(string xml, string errors = "")
    {
        XDocument document;
        try
        {
            document = XDocument.Parse(xml);
        }
        catch (System.Xml.XmlException)
        {
            throw new ToolException($"veraPDF returned no readable validation report. {Tail(errors + xml)}");
        }
        var results = new Dictionary<string, Validation>(StringComparer.OrdinalIgnoreCase);
        foreach (var job in document.Descendants("job"))
        {
            var name = job.Element("item")?.Element("name")?.Value;
            if (name is null)
                continue;
            var report = job.Element("validationReport");
            if (report?.Attribute("isCompliant") is not { } compliant)
            {
                var problem = job.Element("taskException")?.Element("exceptionMessage")?.Value ?? "veraPDF returned no conformance result.";
                results[name] = new Validation(false, problem);
                continue;
            }
            var lines = new List<string> { report.Attribute("statement")?.Value ?? "" };
            foreach (var rule in report.Descendants("rule").Where(r => (string?)r.Attribute("status") == "failed").Take(12))
            {
                var id = $"{rule.Attribute("clause")?.Value}-{rule.Attribute("testNumber")?.Value}".Trim('-');
                var message = rule.Descendants("errorMessage").FirstOrDefault()?.Value ?? rule.Element("description")?.Value;
                lines.Add(message is null ? $"Failed rule {id}" : $"Failed rule {id}: {message}");
            }
            results[name] = new Validation(string.Equals(compliant.Value, "true", StringComparison.OrdinalIgnoreCase), string.Join("\n", lines.Where(line => line.Length > 0)));
        }
        return results;
    }

    public static string PdfaDefinition(string icc) => $$"""
        %!PS-Adobe-3.0
        % Minimal PDF/A output intent using the bundled sRGB profile.
        /ICCProfile ({{PostScriptString(icc)}}) def
        [/_objdef {icc_PDFA} /type /stream /OBJ pdfmark
        [{icc_PDFA} << /N 3 >> /PUT pdfmark
        [{icc_PDFA} ICCProfile (r) file /PUT pdfmark
        [/_objdef {OutputIntent_PDFA} /type /dict /OBJ pdfmark
        [{OutputIntent_PDFA} << /Type /OutputIntent /S /GTS_PDFA1 /DestOutputProfile {icc_PDFA} /OutputConditionIdentifier (sRGB) >> /PUT pdfmark
        [{Catalog} <</OutputIntents [ {OutputIntent_PDFA} ]>> /PUT pdfmark

        """;

    public static string PostScriptString(string path) =>
        Path.GetFullPath(path).Replace("\\", "\\\\").Replace("(", "\\(").Replace(")", "\\)");

    static string Tail(string value, int limit = 2500)
    {
        value = value.Trim();
        return value.Length > limit ? value[^limit..] : value;
    }
}
