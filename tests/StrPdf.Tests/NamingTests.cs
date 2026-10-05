using StrPdf;

public sealed class NamingTests : IDisposable
{
    readonly string folder = Directory.CreateTempSubdirectory("str-pdf-tests-").FullName;
    readonly string source;

    public NamingTests()
    {
        source = Path.Combine(folder, "a.pdf");
        File.WriteAllText(source, "%PDF-1.4");
    }

    public void Dispose() => Directory.Delete(folder, recursive: true);

    [Fact]
    public void TargetsFollowSaveMode()
    {
        Assert.Equal(Path.Combine(folder, "a_pdfa.pdf"), Naming.TargetFor(source, SaveMode.Next, null));
        Assert.Equal(Path.Combine(folder, "out", "a.pdf"), Naming.TargetFor(source, SaveMode.Folder, Path.Combine(folder, "out")));
        Assert.Equal(source, Naming.TargetFor(source, SaveMode.Overwrite, null));
    }

    [Fact]
    public void UniqueNameSkipsExistingAndReserved()
    {
        Assert.Equal("a-copy.pdf", Path.GetFileName(Naming.UniqueName(source, "-copy", Naming.NewPathSet())));
        var reserved = Naming.NewPathSet();
        reserved.Add(Path.Combine(folder, "a-copy.pdf"));
        Assert.Equal("a-copy-2.pdf", Path.GetFileName(Naming.UniqueName(source, "-copy", reserved)));
        File.WriteAllText(Path.Combine(folder, "a-copy-2.pdf"), "");
        Assert.Equal("a-copy-3.pdf", Path.GetFileName(Naming.UniqueName(source, "-copy", reserved)));
    }
}
