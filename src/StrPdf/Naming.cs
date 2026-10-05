namespace StrPdf;

public enum SaveMode { Next, Folder, Overwrite }

public static class Naming
{
    public const string NextSuffix = "_pdfa";

    public static HashSet<string> NewPathSet() => new(StringComparer.OrdinalIgnoreCase);

    public static string TargetFor(string source, SaveMode mode, string? folder, string? root = null, bool preserve = false) => mode switch
    {
        SaveMode.Overwrite => source,
        SaveMode.Folder when folder is not null => FolderTarget(source, folder, root, preserve),
        _ => Path.Combine(Path.GetDirectoryName(source)!, Path.GetFileNameWithoutExtension(source) + NextSuffix + Path.GetExtension(source)),
    };

    static string FolderTarget(string source, string folder, string? root, bool preserve)
    {
        if (preserve && root is not null)
        {
            var sourceDir = Path.GetDirectoryName(Path.GetFullPath(source));
            var rootFull = Path.GetFullPath(root);
            if (sourceDir is not null && sourceDir.StartsWith(rootFull, StringComparison.OrdinalIgnoreCase))
            {
                var relativeDir = Path.GetRelativePath(rootFull, sourceDir);
                return Path.Combine(folder, relativeDir, Path.GetFileName(source));
            }
        }
        return Path.Combine(folder, Path.GetFileName(source));
    }

    /// <summary>First "name{suffix}.pdf", "name{suffix}-2.pdf", … that neither exists nor is reserved by this batch.</summary>
    public static string UniqueName(string target, string suffix, ISet<string> reserved)
    {
        var folder = Path.GetDirectoryName(target)!;
        var stem = Path.GetFileNameWithoutExtension(target);
        var extension = Path.GetExtension(target);
        for (var index = 1; ; index++)
        {
            var candidate = Path.Combine(folder, $"{stem}{suffix}{(index == 1 ? "" : $"-{index}")}{extension}");
            if (!File.Exists(candidate) && !reserved.Contains(Path.GetFullPath(candidate)))
                return candidate;
        }
    }
}
