using System.Diagnostics;
using System.Windows;

namespace StrPdf;

public partial class AboutWindow : Wpf.Ui.Controls.FluentWindow
{
    const string Email = "info@str-ucture.com";
    const string WebsiteUrl = "https://str-ucture.com";

    public AboutWindow(string version)
    {
        InitializeComponent();
        TitleText.Text = $"PDF to PDF/A Converter {version}";
    }

    void OnCopyEmail(object sender, RoutedEventArgs e) => Clipboard.SetText(Email);

    void OnOpenWebsite(object sender, RoutedEventArgs e) => Process.Start(new ProcessStartInfo(WebsiteUrl) { UseShellExecute = true });

    void OnLicense(object sender, RoutedEventArgs e) => new LicenseWindow { Owner = Owner }.ShowDialog();
}
