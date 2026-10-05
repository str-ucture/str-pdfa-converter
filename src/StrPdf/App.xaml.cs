using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using Wpf.Ui.Appearance;
using Wpf.Ui.Controls;
using MessageBox = Wpf.Ui.Controls.MessageBox;
using MessageBoxResult = Wpf.Ui.Controls.MessageBoxResult;
using TextBlock = System.Windows.Controls.TextBlock;

namespace StrPdf;

public partial class App : Application
{
    [DllImport("kernel32.dll")]
    static extern bool AttachConsole(int processId);

    void SetBand(ApplicationTheme theme) =>
        Resources["BandBrush"] = theme switch
        {
            ApplicationTheme.Dark => new SolidColorBrush(Color.FromRgb(0x16, 0x16, 0x16)),
            ApplicationTheme.HighContrast => SystemColors.WindowBrush,
            _ => new SolidColorBrush(Color.FromRgb(0xE6, 0xE6, 0xE6)),
        };

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        if (e.Args.Contains("--smoke-check"))
        {
            // A WinExe has no console of its own; borrow the parent's so the results are visible.
            if (!Console.IsOutputRedirected)
                AttachConsole(-1);
            // Window construction must happen on this (UI/STA) thread, unlike the engine checks below.
            var windowCode = Smoke.CheckWindows(Console.Out);
            if (windowCode != 0)
            {
                Shutdown(windowCode);
                return;
            }
            Shutdown(Task.Run(() => Smoke.RunAsync(Console.Out)).GetAwaiter().GetResult());
            return;
        }
        // Header and footer bands: a clear step darker than the window body in both themes
        // (the Fluent "secondary" background is only 2% off the base in dark mode).
        ApplicationThemeManager.Changed += (theme, _) => SetBand(theme);
        SetBand(ApplicationThemeManager.GetAppTheme());
        // Pin the accent to the app's brand color (Brand.xaml) instead of the Windows system accent
        // (otherwise every Accent*Brush-based control - radio dots, selection highlight,
        // checked checkboxes, etc. - picks up whatever purple/blue the user has in Windows Settings).
        var brandPink = (Color)Resources["BrandPinkColor"];
        ApplicationAccentColorManager.Apply(brandPink, ApplicationThemeManager.GetAppTheme());
        ApplicationThemeManager.Changed += (theme, _) => ApplicationAccentColorManager.Apply(brandPink, theme);
        // A bug we haven't found yet (or a rare WPF timing quirk, like the ContextMenu crash this
        // replaces) would otherwise kill the app instantly with no chance to save work. This turns
        // that into a recoverable dialog instead - it doesn't fix root causes, just softens them.
        DispatcherUnhandledException += OnUnhandledException;
        // Paths passed on the command line (drag onto the exe, Explorer "Send to") are queued at startup.
        new MainWindow(e.Args.Where(arg => !arg.StartsWith("--"))).Show();
    }

    async void OnUnhandledException(object? sender, System.Windows.Threading.DispatcherUnhandledExceptionEventArgs e)
    {
        e.Handled = true;
        var owner = Windows.OfType<Window>().FirstOrDefault(w => w.IsActive) ?? MainWindow;
        var box = new MessageBox
        {
            Owner = owner,
            Title = "Something went wrong",
            Content = new TextBlock
            {
                Text = $"An unexpected error occurred:\n\n{e.Exception.Message}\n\nYou can keep working, but if this keeps happening, copy the details and report it.",
                TextWrapping = TextWrapping.Wrap,
                MaxWidth = 460,
            },
            PrimaryButtonText = "Copy details",
            PrimaryButtonAppearance = ControlAppearance.Secondary,
            SecondaryButtonText = "Close app",
            SecondaryButtonAppearance = ControlAppearance.Danger,
            CloseButtonText = "Continue",
        };
        var result = await box.ShowDialogAsync();
        if (result == MessageBoxResult.Primary)
        {
            try { Clipboard.SetText(e.Exception.ToString()); } catch (System.Runtime.InteropServices.COMException) { }
        }
        else if (result == MessageBoxResult.Secondary)
        {
            Shutdown(1);
        }
    }
}
