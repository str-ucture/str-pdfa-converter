using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;
using Markdig;
using Microsoft.Win32;
using Wpf.Ui.Controls;

namespace StrPdf;

public partial class LicenseWindow : FluentWindow
{
    record Doc(string Label, string[] Files, string? Appendix = null, bool IsMarkdown = false)
    {
        public override string ToString() => Label; // list item name for screen readers
    }

    static readonly MarkdownPipeline MarkdownPipeline = new MarkdownPipelineBuilder().UseAdvancedExtensions().Build();

    static readonly Doc[] Docs =
    [
        new("Notice", ["NOTICE.txt", "NOTICE.md"], IsMarkdown: true),
        new("This app (GNU AGPL v3)", ["LICENSE.txt", "LICENSE"]),
        new("Third-party summary", ["THIRD_PARTY_NOTICES.txt", "THIRD_PARTY_NOTICES.md"], IsMarkdown: true),
        new("Ghostscript (GNU AGPL v3)", ["runtime/ghostscript/doc/COPYING"]),
        new("veraPDF (MPL 2.0 / GPL v3)", ["licenses/verapdf-MPL-2.0.txt"]),
        new("Java runtime (GPL v2 + Classpath Exception)", ["runtime/java/legal/java.base/LICENSE"], "runtime/java/legal/java.base/ASSEMBLY_EXCEPTION"),
        new(".NET runtime (MIT)", ["licenses/dotnet-MIT.txt"]),
        new("WPF-UI (MIT)", ["licenses/wpf-ui-MIT.txt"]),
    ];

    string? source;

    public LicenseWindow()
    {
        InitializeComponent();
        DocMarkdown.Pipeline = MarkdownPipeline;
        DocList.ItemsSource = Docs;
        DocList.SelectedIndex = 0;
    }

    static string Full(string relative) => Path.GetFullPath(Path.Combine(Engines.Root, relative));

    void OnDocChanged(object sender, SelectionChangedEventArgs e)
    {
        if (DocList.SelectedItem is not Doc doc)
            return;
        source = doc.Files.Select(Full).FirstOrDefault(File.Exists);
        string text;
        if (source is null)
            text = $"This document was not found beside the app: {Full(doc.Files[0])}";
        else
        {
            text = File.ReadAllText(source);
            if (doc.Appendix is not null && File.Exists(Full(doc.Appendix)))
                text = $"{text.TrimEnd()}\n\n\n{Path.GetFileName(doc.Appendix)}\n\n{File.ReadAllText(Full(doc.Appendix))}";
        }
        // Always keep the raw text in DocText (even hidden) so Copy/Save keep working unchanged.
        DocText.Text = text;
        DocText.ScrollToHome();

        var showMarkdown = source is not null && doc.IsMarkdown;
        if (showMarkdown)
            DocMarkdown.Markdown = text;
        DocMarkdown.Visibility = showMarkdown ? Visibility.Visible : Visibility.Collapsed;
        DocText.Visibility = showMarkdown ? Visibility.Collapsed : Visibility.Visible;

        SaveButton.IsEnabled = FolderButton.IsEnabled = source is not null;
        StatusText.Text = "";
    }

    async void OnCopy(object sender, RoutedEventArgs e)
    {
        Clipboard.SetText(DocText.Text);
        StatusText.Text = "Copied";
        await Task.Delay(1500);
        if (StatusText.Text == "Copied")
            StatusText.Text = "";
    }

    void OnSave(object sender, RoutedEventArgs e)
    {
        var dialog = new SaveFileDialog
        {
            Title = "Save document",
            FileName = Path.GetFileNameWithoutExtension(source) + ".txt",
            Filter = "Text files (*.txt)|*.txt|All files (*.*)|*.*",
        };
        if (dialog.ShowDialog(this) != true)
            return;
        try
        {
            File.WriteAllText(dialog.FileName, DocText.Text);
            StatusText.Text = $"Saved {dialog.FileName}";
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            StatusText.Text = $"Could not save: {ex.Message}";
        }
    }

    void OnOpenFolder(object sender, RoutedEventArgs e) => Process.Start("explorer.exe", $"/select,\"{source}\"");

    void OnClose(object sender, RoutedEventArgs e) => Close();
}
