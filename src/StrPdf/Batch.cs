using System.ComponentModel;
using System.Runtime.CompilerServices;

namespace StrPdf;

public enum Tone { Neutral, Busy, Ok, Bad, Muted }

public sealed class FileItem(string path, string? root = null) : INotifyPropertyChanged
{
    string status = "Queued";
    string? output;
    string details = "";

    public string Path { get; } = System.IO.Path.GetFullPath(path);
    public string? Root { get; } = root is null ? null : System.IO.Path.GetFullPath(root);
    public string Name => System.IO.Path.GetFileName(Path);
    public string Folder => Root is not null
        ? System.IO.Path.GetRelativePath(Root, System.IO.Path.GetDirectoryName(Path) ?? Root)
        : System.IO.Path.GetDirectoryName(Path) ?? "";
    public long Bytes { get; } = new FileInfo(path).Length;
    public string Size => Bytes switch
    {
        < 1024 => $"{Bytes} B",
        < 1024 * 1024 => $"{Bytes / 1024.0:0.0} KB",
        < 1024L * 1024 * 1024 => $"{Bytes / 1048576.0:0.0} MB",
        _ => $"{Bytes / 1073741824.0:0.0} GB",
    };

    public string Status { get => status; set { status = value; Changed(); Changed(nameof(Tone)); Changed(nameof(Summary)); Changed(nameof(ShortReason)); Changed(nameof(FixTip)); Changed(nameof(OutputDisplay)); Changed(nameof(IsFailed)); } }
    public string? Output { get => output; set { output = value; Changed(); Changed(nameof(OutputName)); Changed(nameof(Summary)); Changed(nameof(OutputDisplay)); } }
    public string Details { get => details; set { details = value; Changed(); Changed(nameof(Summary)); Changed(nameof(HasDetails)); Changed(nameof(ShortReason)); Changed(nameof(FixTip)); Changed(nameof(OutputDisplay)); } }
    public string OutputName => output is null ? "" : System.IO.Path.GetFileName(output);
    public bool HasDetails => details.Length > 0;

    // A short, at-a-glance reason for the Output file column, plus a plain-language tip
    // shown on hover. The full message (Ghostscript stderr, veraPDF report, exception text)
    // stays one click away via the "View log" button regardless.
    (string Label, string Tip) Reason => status switch
    {
        "Conversion failed" when details.Contains("is password-protected. Remove the open password", StringComparison.OrdinalIgnoreCase) =>
            ("Password-protected PDF", "This PDF needs a password to open. Remove the password protection (e.g. in Acrobat or another PDF editor) and try again."),
        "Conversion failed" when details.Contains("engine is missing", StringComparison.OrdinalIgnoreCase)
            || details.Contains("was not found beside the bundled engine", StringComparison.OrdinalIgnoreCase)
            || details.Contains("validator is missing", StringComparison.OrdinalIgnoreCase)
            || details.Contains("Could not start ", StringComparison.Ordinal) =>
            ("App files missing or blocked", "A required component wasn't found or couldn't start. Try reinstalling the app; if that doesn't help, check whether your antivirus has quarantined a file in the app folder."),
        "Conversion failed" when details.StartsWith("Could not save the result", StringComparison.Ordinal) =>
            ("Couldn't save output file", "The converted file couldn't be saved. Make sure there's enough free disk space, the destination isn't open in another program, and you have permission to write there."),
        "Conversion failed" when details.Contains("No pages could be read", StringComparison.OrdinalIgnoreCase) =>
            ("Unreadable or damaged PDF", "Ghostscript couldn't read any pages from this file. It may be corrupted or not a real PDF - try opening it in a PDF reader first to confirm."),
        "Conversion failed" =>
            ("Conversion failed", "Something went wrong converting this file. Click \"View log\" for the full technical details."),
        "Validation failed" =>
            ("Not PDF/A compliant", "The converted file didn't pass PDF/A validation. Click \"View log\" to see which rules failed."),
        "Verification error" when details.Contains("no readable validation report", StringComparison.OrdinalIgnoreCase)
            || details.Contains("reported success but exited with code", StringComparison.OrdinalIgnoreCase) =>
            ("Verification tool error", "veraPDF couldn't produce a validation report for this file. This is usually transient - try converting again."),
        "Verification error" =>
            ("Couldn't verify compliance", "Verification didn't run for this file. Try converting again."),
        _ => ("", ""),
    };
    public string ShortReason => Reason.Label;
    public string FixTip => Reason.Tip;
    public bool IsFailed => ShortReason.Length > 0;
    public string OutputDisplay => IsFailed ? ShortReason : OutputName;

    public Tone Tone => status switch
    {
        "Verified" => Tone.Ok,
        "Validation failed" or "Verification error" or "Conversion failed" => Tone.Bad,
        "Converting" or "Verifying" => Tone.Busy,
        "Cancelled" => Tone.Muted,
        _ => Tone.Neutral,
    };

    public string Summary =>
        $"{Name}: {Status}\nSource: {Path}" + (output is null ? "" : $"\nOutput: {output}") + (details.Length == 0 ? "" : $"\n{details}");

    public void Finish(string state, string text, string? saved)
    {
        Status = state;
        Details = text;
        Output = saved;
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    void Changed([CallerMemberName] string? name = null) => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}

/// <summary>
/// Converts each file to a hidden temporary PDF, validates all of them in one veraPDF run, then saves each result.
/// Awaited on the UI thread: engines run as child processes, so item updates stay on the dispatcher.
/// </summary>
public static class Batch
{
    public sealed record Job(FileItem Item, string Target);

    sealed record Converted(FileItem Item, string Target, string Temporary);

    /// <summary>
    /// Parallel Ghostscript processes: 1 on a 2-core or 4 GB machine, up to 4 on a workstation.
    /// Each process is single-threaded and needs roughly 100-300 MB for typical office PDFs.
    /// </summary>
    public static int Workers { get; } = Math.Clamp(
        Math.Min(Environment.ProcessorCount / 2, (int)(GC.GetGCMemoryInfo().TotalAvailableMemoryBytes / (3L << 30))), 1, 4);

    public static async Task<string> RunAsync(IReadOnlyList<Job> jobs, string format, bool copyOnConflict, Action<string> log, Action<double> progress, CancellationToken cancel)
    {
        var reserved = Naming.NewPathSet();
        foreach (var job in jobs)
        {
            reserved.Add(Path.GetFullPath(job.Target));
            job.Item.Finish("Queued", "", null);
        }
        var written = Naming.NewPathSet();
        var converted = new List<Converted>();
        var done = 0;

        // Final names are decided up front, in list order, so parallel conversion stays deterministic.
        var planned = new List<(FileItem Item, string Target)>();
        foreach (var job in jobs)
        {
            var target = job.Target;
            if ((copyOnConflict && File.Exists(target)) || written.Contains(Path.GetFullPath(target)))
                target = Naming.UniqueName(target, "-pdf-a-copy", Union(reserved, written));
            written.Add(Path.GetFullPath(target));
            planned.Add((job.Item, target));
        }

        // Every await below resumes on the UI thread, so item updates and the shared lists need no locking.
        using var slots = new SemaphoreSlim(Workers);
        async Task ConvertOne(FileItem item, string target)
        {
            await slots.WaitAsync(cancel);
            var folder = Path.GetDirectoryName(target)!;
            var temporary = Path.Combine(folder, $".{Path.GetFileNameWithoutExtension(target)}-{Guid.NewGuid():N}.pdf");
            try
            {
                item.Finish("Converting", "", null);
                Directory.CreateDirectory(folder);
                var engineLog = await Engines.ConvertAsync(item.Path, temporary, format, cancel);
                if (engineLog.Length > 0)
                    log(engineLog);
                converted.Add(new Converted(item, target, temporary));
                item.Status = "Converted";
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                TryDelete(temporary);
                Report(item, "Conversion failed", $"Ghostscript could not convert this file. It may be damaged, password-protected, or not a real PDF.\n{ex.Message}", null, log);
            }
            catch
            {
                TryDelete(temporary);
                throw;
            }
            finally
            {
                slots.Release();
            }
            progress(++done);
        }

        try
        {
            var conversions = planned.Select(plan => ConvertOne(plan.Item, plan.Target)).ToList();
            try
            {
                await Task.WhenAll(conversions);
            }
            catch (OperationCanceledException)
            {
                // WhenAll rethrows the first cancellation; wait for the rest so every temp file is accounted for.
                await Task.WhenAll(conversions.Select(task => task.ContinueWith(_ => { }, TaskScheduler.Default)));
                throw;
            }
            // Validate and save in list order, not completion order.
            var order = planned.Select((plan, index) => (plan.Item, index)).ToDictionary(pair => pair.Item, pair => pair.index);
            converted.Sort((a, b) => order[a.Item].CompareTo(order[b.Item]));

            if (converted.Count > 0)
                await ValidateAndSave(converted, format, reserved, written, log, cancel);
        }
        catch (OperationCanceledException)
        {
            foreach (var pending in converted)
                TryDelete(pending.Temporary);
            foreach (var job in jobs.Where(job => job.Item.Tone is Tone.Busy or Tone.Neutral))
                Report(job.Item, "Cancelled", "Cancelled before the result was saved.", null, log);
        }

        progress(jobs.Count + 1);
        var counts = jobs.GroupBy(job => job.Item.Status).ToDictionary(group => group.Key, group => group.Count());
        int Count(string state) => counts.GetValueOrDefault(state);
        return $"{Count("Verified")} of {jobs.Count} file(s) converted and verified. {Count("Validation failed")} failed validation, "
            + $"{Count("Verification error")} verification errors, {Count("Conversion failed")} conversion failures.";
    }

    static async Task ValidateAndSave(List<Converted> converted, string format, HashSet<string> reserved, HashSet<string> written, Action<string> log, CancellationToken cancel)
    {
        foreach (var item in converted)
            item.Item.Status = "Verifying";
        Dictionary<string, Validation>? results = null;
        string? batchError = null;
        try
        {
            results = await Engines.ValidateAsync(converted.Select(item => item.Temporary).ToList(), Engines.Formats[format], cancel);
        }
        catch (ToolException ex)
        {
            batchError = ex.Message;
        }
        cancel.ThrowIfCancellationRequested();

        foreach (var (item, target, temporary) in converted)
        {
            var result = results?.GetValueOrDefault(Path.GetFullPath(temporary));
            var state = result is null ? "Verification error" : result.Compliant ? "Verified" : "Validation failed";
            var details = result?.Details ?? batchError ?? "veraPDF returned no result for this file.";
            try
            {
                if (result is { Compliant: true })
                {
                    File.Move(temporary, target, overwrite: true);
                    Report(item, state, details, target, log);
                }
                else if (string.Equals(Path.GetFullPath(target), item.Path, StringComparison.OrdinalIgnoreCase))
                {
                    TryDelete(temporary);
                    Report(item, state, details + "\nOriginal left unchanged.", null, log);
                }
                else
                {
                    var failed = Naming.UniqueName(target, "-validation-failed", Union(reserved, written));
                    File.Move(temporary, failed);
                    Report(item, state, details + $"\nCandidate retained at: {failed}", failed, log);
                }
            }
            catch (IOException ex)
            {
                TryDelete(temporary);
                Report(item, "Conversion failed", $"Could not save the result: {ex.Message}", null, log);
            }
            catch (UnauthorizedAccessException ex)
            {
                TryDelete(temporary);
                Report(item, "Conversion failed", $"Could not save the result: {ex.Message}", null, log);
            }
        }
    }

    static void Report(FileItem item, string state, string details, string? saved, Action<string> log)
    {
        item.Finish(state, details, saved);
        log($"{item.Name}: {state}\nSource: {item.Path}\n{(saved is null ? "" : $"Saved to: {saved}\n")}{details}\n");
    }

    static HashSet<string> Union(HashSet<string> a, HashSet<string> b)
    {
        var all = Naming.NewPathSet();
        all.UnionWith(a);
        all.UnionWith(b);
        return all;
    }

    static void TryDelete(string path)
    {
        try { File.Delete(path); } catch (IOException) { } catch (UnauthorizedAccessException) { }
    }
}
