using StrPdf;

public sealed class FileItemReasonTests
{
    static FileItem Failed(string status, string details)
    {
        var item = new FileItem(typeof(FileItemReasonTests).Assembly.Location);
        item.Finish(status, details, null);
        return item;
    }

    [Theory]
    [InlineData("Conversion failed", "Ghostscript could not convert this file. It may be damaged, password-protected, or not a real PDF.\nThe file is password-protected. Remove the open password and try again.", "Password-protected PDF")]
    [InlineData("Conversion failed", "Ghostscript could not convert this file. It may be damaged, password-protected, or not a real PDF.\nThe bundled Ghostscript engine is missing.", "App files missing or blocked")]
    [InlineData("Conversion failed", "Could not save the result: The process cannot access the file because it is being used by another process.", "Couldn't save output file")]
    [InlineData("Conversion failed", "Ghostscript could not convert this file. It may be damaged, password-protected, or not a real PDF.\nNo pages could be read from the file.\nsome log tail", "Unreadable or damaged PDF")]
    [InlineData("Conversion failed", "Ghostscript could not convert this file. It may be damaged, password-protected, or not a real PDF.\nGhostscript exited with code 1.", "Conversion failed")]
    [InlineData("Validation failed", "Fail\nFailed rule 6.2.11.4.1-1: The font program is not embedded", "Not PDF/A compliant")]
    [InlineData("Verification error", "veraPDF returned no readable validation report. some tail", "Verification tool error")]
    [InlineData("Verification error", "veraPDF returned no result for this file.", "Couldn't verify compliance")]
    public void ClassifiesFailuresIntoShortReasons(string status, string details, string expectedLabel)
    {
        var item = Failed(status, details);
        Assert.Equal(expectedLabel, item.ShortReason);
        Assert.True(item.IsFailed);
        Assert.NotEmpty(item.FixTip);
        Assert.Equal(item.ShortReason, item.OutputDisplay);
    }

    [Fact]
    public void SuccessfulItemsShowTheOutputFileName()
    {
        var item = new FileItem(typeof(FileItemReasonTests).Assembly.Location);
        item.Finish("Verified", "Pass", @"C:\out\file_pdfa.pdf");

        Assert.False(item.IsFailed);
        Assert.Equal("", item.ShortReason);
        Assert.Equal("file_pdfa.pdf", item.OutputDisplay);
    }
}
