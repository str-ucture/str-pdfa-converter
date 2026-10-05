using StrPdf;

public sealed class ReportTests
{
    [Fact]
    public void ParsesEveryJobInABatchReport()
    {
        const string xml = """
            <report><jobs>
              <job><item size="1"><name>C:\a.pdf</name></item>
                <validationReport statement="Pass" isCompliant="true"><details failedRules="0"/></validationReport></job>
              <job><item size="1"><name>C:\b.pdf</name></item>
                <validationReport statement="Fail" isCompliant="false"><details>
                  <rule clause="6.2.11.4.1" testNumber="1" status="failed"><description>Fonts shall be embedded</description>
                    <check status="failed"><errorMessage>The font program is not embedded</errorMessage></check></rule>
                  <rule clause="6.6.2.1" testNumber="1" status="failed"><description>Metadata required</description></rule>
                  <rule clause="6.1" testNumber="9" status="passed" />
                </details></validationReport></job>
              <job><item size="1"><name>C:\c.pdf</name></item>
                <taskException><exceptionMessage>Couldn't parse stream</exceptionMessage></taskException></job>
            </jobs></report>
            """;
        var results = Engines.ParseReport(xml);

        Assert.Equal(new Validation(true, "Pass"), results[@"C:\A.PDF"]);
        Assert.Equal(new Validation(false, "Fail\nFailed rule 6.2.11.4.1-1: The font program is not embedded\nFailed rule 6.6.2.1-1: Metadata required"), results[@"C:\b.pdf"]);
        Assert.Equal(new Validation(false, "Couldn't parse stream"), results[@"C:\c.pdf"]);
    }

    [Fact]
    public void UnreadableReportIsAToolError() =>
        Assert.Throws<ToolException>(() => Engines.ParseReport("Error: could not find Java", ""));

    [Fact]
    public void GhostscriptBlankOutputIsDetected()
    {
        Assert.StartsWith("The file is password-protected", Engines.UnreadableInput("   **** This file requires a password for access.\n   **** Error: Couldn't initialise file."));
        Assert.StartsWith("No pages could be read", Engines.UnreadableInput("   **** Error: Couldn't initialise file.\n   No pages will be processed (FirstPage > LastPage)."));
        Assert.Null(Engines.UnreadableInput(""));
    }

    [Fact]
    public void PostScriptPathsAreEscaped() =>
        Assert.EndsWith(@"a\(b\).icc", Engines.PostScriptString(@"C:\folder\a(b).icc"));
}
