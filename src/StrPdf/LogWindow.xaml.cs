using System.Windows;

namespace StrPdf;

public partial class LogWindow : Wpf.Ui.Controls.FluentWindow
{
    public LogWindow()
    {
        InitializeComponent();
    }

    public void Append(string text)
    {
        LogText.AppendText(text.TrimEnd() + Environment.NewLine);
        LogText.ScrollToEnd();
    }

    public void SetText(string title, string text, string? headline = null)
    {
        Title = AppTitleBar.Title = title;
        LogText.Text = text.TrimEnd() + Environment.NewLine;
        if (string.IsNullOrEmpty(headline))
        {
            Headline.Visibility = Visibility.Collapsed;
        }
        else
        {
            Headline.Text = $"“{headline}”";
            Headline.Visibility = Visibility.Visible;
        }
    }

    void OnCopy(object sender, RoutedEventArgs e) => Clipboard.SetText(LogText.Text);

    void OnClose(object sender, RoutedEventArgs e) => Close();
}
