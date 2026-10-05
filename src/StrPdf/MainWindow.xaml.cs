using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using Microsoft.Win32;
using Wpf.Ui.Appearance;
using Wpf.Ui.Controls;
using MessageBox = Wpf.Ui.Controls.MessageBox;
using MessageBoxResult = Wpf.Ui.Controls.MessageBoxResult;
using TextBlock = System.Windows.Controls.TextBlock;

namespace StrPdf;

public partial class MainWindow : FluentWindow
{
    static readonly Dictionary<string, string> FormatHints = new()
    {
        ["PDF/A-1b"] = "Oldest standard. Use only if an archive system requires it.",
        ["PDF/A-2b"] = "Recommended for most archiving.",
        ["PDF/A-3b"] = "Like 2b, but also allows embedded file attachments.",
    };

    readonly ObservableCollection<FileItem> items = [];
    readonly Settings settings = Settings.Load();
    readonly string version = typeof(MainWindow).Assembly.GetName().Version!.ToString(3);
    CancellationTokenSource? running;
    bool closeWhenDone;
    string? outputDir;
    readonly System.Text.StringBuilder logText = new();
    LogWindow? logWindow;

    public MainWindow(IEnumerable<string> startupPaths)
    {
        InitializeComponent();
        ApplyTheme(settings.Theme);
        Title = AppTitleBar.Title = $"PDF to PDF/A Converter {version}";
        FileList.ItemsSource = items;
        items.CollectionChanged += (_, _) => RefreshState();
        FormatBox.ItemsSource = Engines.Formats.Keys;
        FormatBox.SelectedItem = Engines.Formats.ContainsKey(settings.Format) ? settings.Format : "PDF/A-2b";
        SubfoldersBox.IsChecked = settings.IncludeSubfolders;
        PreserveStructureBox.IsChecked = settings.PreserveSubfolders;
        outputDir = Directory.Exists(settings.OutputDirectory) ? settings.OutputDirectory : null;
        (settings.SaveMode == SaveMode.Folder && outputDir is not null ? FolderRadio : NextRadio).IsChecked = true;
        UpdateFolderText();
        RefreshState();
        Log($"PDF to PDF/A Converter {version}. Conversion and validation run locally, {Batch.Workers} file(s) at a time.");
        var paths = startupPaths.ToList();
        if (paths.Count > 0)
            AddPaths(Expand(paths));
    }

    SaveMode Mode => OverwriteRadio.IsChecked == true ? SaveMode.Overwrite : FolderRadio.IsChecked == true ? SaveMode.Folder : SaveMode.Next;

    List<FileItem> Selected => FileList.SelectedItems.Cast<FileItem>().ToList();

    // ---- Adding and removing files ----

    void AddPaths(IEnumerable<(string Path, string? Root)> paths)
    {
        if (running is not null)
            return;
        var known = Naming.NewPathSet();
        known.UnionWith(items.Select(item => item.Path));
        int added = 0, skipped = 0;
        foreach (var (path, root) in paths)
        {
            if (!File.Exists(path) || !path.EndsWith(".pdf", StringComparison.OrdinalIgnoreCase) || !known.Add(Path.GetFullPath(path)))
            {
                skipped++;
                continue;
            }
            items.Add(new FileItem(path, root));
            added++;
        }
        var detail = $"Added {added} PDF file(s)." + (skipped > 0 ? $" Skipped {skipped} duplicate, missing, or non-PDF item(s)." : "");
        StatusText.Text = detail;
        Log(detail);
    }

    void AddPaths(IEnumerable<string> paths) => AddPaths(paths.Select(path => (path, (string?)null)));

    IEnumerable<string> PdfsIn(string folder) => Directory
        .EnumerateFiles(folder, "*.pdf", new EnumerationOptions
        {
            RecurseSubdirectories = SubfoldersBox.IsChecked == true,
            IgnoreInaccessible = true,
            MatchCasing = MatchCasing.CaseInsensitive,
        })
        .Order(StringComparer.OrdinalIgnoreCase);

    List<(string Path, string? Root)> Expand(IEnumerable<string> paths) => paths
        .SelectMany(path => Directory.Exists(path)
            ? PdfsIn(path).Select(pdf => (pdf, (string?)path))
            : [(path, (string?)null)])
        .ToList();

    void OnAddFiles(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog { Title = "Select PDF files", Filter = "PDF files (*.pdf)|*.pdf", Multiselect = true };
        if (running is null && dialog.ShowDialog(this) == true)
            AddPaths(dialog.FileNames);
    }

    void OnAddFolder(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFolderDialog { Title = "Select a folder containing PDFs" };
        if (running is not null || dialog.ShowDialog(this) != true)
            return;
        var pdfs = PdfsIn(dialog.FolderName).ToList();
        if (pdfs.Count > 0)
            AddPaths(pdfs.Select(pdf => (pdf, (string?)dialog.FolderName)));
        else
            StatusText.Text = $"No PDFs found in {dialog.FolderName}{(SubfoldersBox.IsChecked == true ? " or its subfolders" : "")}.";
    }

    void OnSubfoldersChanged(object sender, RoutedEventArgs e)
    {
        if (running is not null)
            return;
        var roots = items.Select(item => item.Root).Where(root => root is not null).Cast<string>().Distinct(StringComparer.OrdinalIgnoreCase).ToList();
        int added = 0, removed = 0;
        foreach (var root in roots)
        {
            if (!Directory.Exists(root))
                continue;
            var wanted = PdfsIn(root).ToHashSet(StringComparer.OrdinalIgnoreCase);
            foreach (var item in items.Where(item => string.Equals(item.Root, root, StringComparison.OrdinalIgnoreCase) && !wanted.Contains(item.Path)).ToList())
            {
                items.Remove(item);
                removed++;
            }
            var existing = items.Where(item => string.Equals(item.Root, root, StringComparison.OrdinalIgnoreCase)).Select(item => item.Path).ToHashSet(StringComparer.OrdinalIgnoreCase);
            foreach (var path in wanted.Where(path => !existing.Contains(path)))
            {
                items.Add(new FileItem(path, root));
                added++;
            }
        }
        if (added == 0 && removed == 0)
            return;
        var detail = $"Subfolder setting changed: added {added}, removed {removed} file(s).";
        StatusText.Text = detail;
        Log(detail);
    }

    void OnDragOver(object sender, DragEventArgs e)
    {
        e.Effects = running is null && e.Data.GetDataPresent(DataFormats.FileDrop) ? DragDropEffects.Copy : DragDropEffects.None;
        e.Handled = true;
    }

    void OnDrop(object sender, DragEventArgs e)
    {
        if (e.Data.GetData(DataFormats.FileDrop) is string[] dropped)
            AddPaths(Expand(dropped));
    }

    void OnRemove(object sender, RoutedEventArgs e)
    {
        if (running is not null)
            return;
        foreach (var item in Selected)
            items.Remove(item);
    }

    async void OnClear(object sender, RoutedEventArgs e)
    {
        if (running is not null || items.Count == 0)
            return;
        var noun = items.Count == 1 ? "file" : "files";
        if (await Ask("Remove all files?", $"Remove all {items.Count} {noun} from the list? Files on disk are not touched.", "Remove all", null, "Cancel", suppressEnterKey: true) != MessageBoxResult.Primary)
            return;
        items.Clear();
    }

    // ---- List interaction ----

    void OnSelectionChanged(object sender, SelectionChangedEventArgs e) => RefreshState();

    void OnRowDoubleClick(object sender, MouseButtonEventArgs e)
    {
        if (ItemsControl.ContainerFromElement(FileList, (DependencyObject)e.OriginalSource) is DataGridRow)
            OpenOutput(reveal: false);
    }

    void OnViewFileLog(object sender, RoutedEventArgs e)
    {
        if (((FrameworkElement)sender).DataContext is not FileItem item)
            return;
        var window = new LogWindow { Owner = this };
        window.SetText($"Log — {item.Name}", item.Summary, item.IsFailed ? item.FixTip : null);
        window.Show();
    }

    /// <summary>
    /// Converts just this row to a private temp file, independent of the "Save to" panel, then
    /// lets the user pick where to keep it via a normal Save As dialog. Cancelling that dialog
    /// discards the temp result rather than leaving an orphaned file the user never chose.
    /// </summary>
    async void OnConvertRow(object sender, RoutedEventArgs e)
    {
        if (((FrameworkElement)sender).DataContext is not FileItem item)
            return;
        if (running is not null)
        {
            StatusText.Text = "Finish the current conversion first.";
            return;
        }
        if (Engines.MissingEngine() is { } missing)
        {
            await Ask("Engine missing", $"This app is missing {missing}. Extract the complete download folder and try again.", null, null, "OK");
            return;
        }

        var temp = Path.Combine(Path.GetTempPath(), $"{Path.GetFileNameWithoutExtension(item.Path)}-{Guid.NewGuid():N}.pdf");
        using var cancel = new CancellationTokenSource();
        running = cancel;
        RefreshState();
        StatusText.Text = $"Converting {item.Name}…";
        try
        {
            await Batch.RunAsync([new Batch.Job(item, temp)], (string)FormatBox.SelectedItem, copyOnConflict: false, Log, _ => { }, cancel.Token);
        }
        finally
        {
            running = null;
            RefreshState();
        }

        if (item.Tone != Tone.Ok || item.Output is not { } produced || !File.Exists(produced))
        {
            StatusText.Text = $"{item.Name}: {item.Status}.";
            return;
        }

        // Independent of the "Save to" panel (its Next/Folder/Overwrite modes, including the
        // "_pdfa" suffix "Next to the original" adds, don't apply here - the user picks the
        // name and location themselves in the dialog below).
        var dialog = new SaveFileDialog
        {
            Title = "Save converted PDF/A",
            FileName = Path.GetFileName(item.Path),
            InitialDirectory = Path.GetDirectoryName(item.Path),
            Filter = "PDF files (*.pdf)|*.pdf",
            DefaultExt = ".pdf",
        };
        if (dialog.ShowDialog(this) == true)
        {
            File.Move(produced, dialog.FileName, overwrite: true);
            item.Output = dialog.FileName;
            StatusText.Text = $"Saved {dialog.FileName}";
            Log($"{item.Name}: Saved to {dialog.FileName}");
        }
        else
        {
            try { File.Delete(produced); } catch (IOException) { } catch (UnauthorizedAccessException) { }
            item.Finish("Cancelled", "Conversion succeeded but the Save As dialog was cancelled.", null);
            StatusText.Text = $"{item.Name}: converted but not saved.";
        }
    }

    void OnListRightClick(object sender, MouseButtonEventArgs e)
    {
        if (ItemsControl.ContainerFromElement(FileList, (DependencyObject)e.OriginalSource) is DataGridRow { IsSelected: false } row)
            FileList.SelectedItem = row.Item;
    }

    void OnListKey(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Delete)
            OnRemove(sender, e);
        else if (e.Key == Key.Enter)
            OpenOutput(reveal: false);
        else
            return;
        e.Handled = true;
    }

    void OnWindowKey(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.O && Keyboard.Modifiers == (ModifierKeys.Control | ModifierKeys.Shift))
            OnAddFolder(sender, e);
        else if (e.Key == Key.O && Keyboard.Modifiers == ModifierKeys.Control)
            OnAddFiles(sender, e);
        else if (e.Key == Key.Escape && running is null)
            FileList.UnselectAll();
        else
            return;
        e.Handled = true;
    }

    void OnOpen(object sender, RoutedEventArgs e) => OpenOutput(reveal: false);

    void OnReveal(object sender, RoutedEventArgs e) => OpenOutput(reveal: true);

    void OpenOutput(bool reveal)
    {
        if (FileList.SelectedItem is not FileItem { Output: { } output } || !File.Exists(output))
        {
            StatusText.Text = "This file has no saved output yet. Convert it first.";
            return;
        }
        try
        {
            Process.Start(reveal ? new ProcessStartInfo("explorer.exe", $"/select,\"{output}\"") : new ProcessStartInfo(output) { UseShellExecute = true });
        }
        catch (Win32Exception ex)
        {
            StatusText.Text = $"Could not open {output}: {ex.Message}";
        }
    }

    // ---- Options ----

    void OnBrowse(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFolderDialog { Title = "Select a folder to save verified files" };
        if (dialog.ShowDialog(this) == true)
        {
            outputDir = dialog.FolderName;
            FolderRadio.IsChecked = true;
            Log($"Output folder: {outputDir}");
        }
        else if (outputDir is null && FolderRadio.IsChecked == true)
        {
            NextRadio.IsChecked = true;
        }
        UpdateFolderText();
    }

    /// <summary>Folder picker for a one-off "save to folder instead" choice - unlike <see cref="OnBrowse"/>,
    /// it doesn't touch the "Save to" panel's own selection, since that choice only applies to this run.</summary>
    bool PickFolder(out string? folder)
    {
        var dialog = new OpenFolderDialog { Title = "Select a folder to save verified files" };
        folder = dialog.ShowDialog(this) == true ? dialog.FolderName : null;
        return folder is not null;
    }

    void OnFolderChecked(object sender, RoutedEventArgs e)
    {
        if (outputDir is null && IsLoaded)
            OnBrowse(sender, e);
    }

    void UpdateFolderText()
    {
        FolderText.Text = outputDir ?? "Not selected";
        FolderText.ToolTip = outputDir;
    }

    void OnFormatChanged(object sender, SelectionChangedEventArgs e) =>
        FormatHint.Text = FormatBox.SelectedItem is string format ? FormatHints[format] : "";

    void OnShowLog(object sender, RoutedEventArgs e)
    {
        if (logWindow is not null)
        {
            logWindow.Activate();
            return;
        }
        logWindow = new LogWindow { Owner = this };
        logWindow.Append(logText.ToString().TrimEnd());
        logWindow.Closed += (_, _) => logWindow = null;
        logWindow.Show();
    }

    void Log(string text)
    {
        logText.AppendLine(text.TrimEnd());
        logWindow?.Append(text);
    }

    void RefreshState()
    {
        var idle = running is null;
        var any = items.Count > 0;
        var selected = FileList.SelectedItems.Count > 0;
        foreach (var control in new Control[] { AddButton, FolderButton, SubfoldersBox, BrowseButton, FormatBox, NextRadio, FolderRadio, OverwriteRadio, PreserveStructureBox })
            control.IsEnabled = idle;
        ClearButton.IsEnabled = ConvertAllButton.IsEnabled = idle && any;
        RemoveButton.IsEnabled = ConvertSelectedButton.IsEnabled = idle && selected;
        EmptyHint.Visibility = any ? Visibility.Collapsed : Visibility.Visible;
        ConvertAllButton.Visibility = idle ? Visibility.Visible : Visibility.Collapsed;
        CancelButton.Visibility = idle ? Visibility.Collapsed : Visibility.Visible;
        if (idle)
        {
            CancelButton.IsEnabled = true;
            CancelButton.Content = "Cancel";
        }
    }

    // ---- Converting ----

    async void OnConvertAll(object sender, RoutedEventArgs e) => await StartAsync(items.ToList());

    async void OnConvertSelected(object sender, RoutedEventArgs e) => await StartAsync(Selected);

    void OnCancel(object sender, RoutedEventArgs e)
    {
        running?.Cancel();
        CancelButton.IsEnabled = false;
        CancelButton.Content = "Cancelling…";
        Log("Cancellation requested; stopping the current engine process…");
    }

    async Task StartAsync(List<FileItem> selection)
    {
        if (running is not null || selection.Count == 0)
            return;
        var mode = Mode;
        var folder = outputDir;
        if (mode == SaveMode.Folder && folder is null)
        {
            OnBrowse(this, new RoutedEventArgs());
            folder = outputDir;
            if (folder is null)
                return;
        }
        if (Engines.MissingEngine() is { } missing)
        {
            await Ask("Engine missing", $"This app is missing {missing}. Extract the complete download folder and try again.", null, null, "OK");
            return;
        }
        if (mode == SaveMode.Overwrite)
        {
            var answer = await Ask("Overwrite original files?",
                $"Replace the original PDF file(s) for this batch ({selection.Count} total)?\n\nEach original is replaced only after conversion and PDF/A verification both succeed.",
                "Overwrite", "Save to folder instead…", "Cancel");
            if (answer == MessageBoxResult.None)
                return;
            if (answer == MessageBoxResult.Secondary)
            {
                if (!PickFolder(out folder))
                    return;
                mode = SaveMode.Folder;
            }
        }
        else if (mode == SaveMode.Next)
        {
            var answer = await Ask("Create new PDF/A file(s)?",
                $"This creates {selection.Count} new PDF/A file(s) next to their originals, each named with a \"_pdfa\" suffix (e.g. file.pdf → file_pdfa.pdf). Your original files are left untouched.",
                "Convert", "Save to folder instead…", "Cancel");
            if (answer == MessageBoxResult.None)
                return;
            if (answer == MessageBoxResult.Secondary)
            {
                if (!PickFolder(out folder))
                    return;
                mode = SaveMode.Folder;
            }
        }

        var preserveStructure = PreserveStructureBox.IsChecked == true;
        var jobs = selection.Select(item => new Batch.Job(item, Naming.TargetFor(item.Path, mode, folder, item.Root, preserveStructure))).ToList();
        var duplicates = jobs.GroupBy(job => Path.GetFullPath(job.Target), StringComparer.OrdinalIgnoreCase).Where(group => group.Count() > 1).ToList();
        if (duplicates.Count > 0 && await Ask("Duplicate output names",
                $"Different inputs would target the same filename in {duplicates.Count} group(s):\n\n{Bullets(duplicates.Select(group => $"{Path.GetFileName(group.Key)} ({group.Count()} inputs)").ToList())}\n\nLater results in each group will be saved with a numbered copy name.",
                "Continue", null, "Cancel") != MessageBoxResult.Primary)
            return;

        var copyOnConflict = false;
        if (mode != SaveMode.Overwrite)
        {
            var conflicts = jobs.Where(job => File.Exists(job.Target)).Select(job => Path.GetFileName(job.Target)).Distinct(StringComparer.OrdinalIgnoreCase).ToList();
            if (conflicts.Count > 0)
            {
                var answer = await Ask("Files already exist", $"{conflicts.Count} output file(s) already exist:\n\n{Bullets(conflicts)}", "Overwrite all", "Create copies", "Cancel");
                if (answer == MessageBoxResult.None)
                    return;
                copyOnConflict = answer == MessageBoxResult.Secondary;
            }
        }

        using var cancel = new CancellationTokenSource();
        running = cancel;
        RefreshState();
        Progress.Maximum = jobs.Count + 1;
        Progress.Value = 0;
        StatusText.Text = $"Converting… 0 of {jobs.Count} done";
        string summary;
        try
        {
            summary = await Batch.RunAsync(jobs, (string)FormatBox.SelectedItem, copyOnConflict, Log, value =>
            {
                Progress.Value = value;
                StatusText.Text = value < jobs.Count ? $"Converting… {value} of {jobs.Count} done" : "Verifying with veraPDF…";
            }, cancel.Token);
        }
        finally
        {
            running = null;
            RefreshState();
        }

        StatusText.Text = (cancel.IsCancellationRequested ? "Cancelled. " : "") + summary;
        Log(StatusText.Text);
        if (closeWhenDone)
            Close();
        else if (!cancel.IsCancellationRequested && jobs.Any(job => job.Item.Tone == Tone.Bad))
            await Ask("Some files need attention", $"{summary}\n\nSelect a red row to see why.", null, null, "OK");
    }

    static string Bullets(List<string> names) =>
        string.Join("\n", names.Take(6).Select(name => $"•  {name}")) + (names.Count > 6 ? $"\n…and {names.Count - 6} more" : "");

    async Task<MessageBoxResult> Ask(string title, string text, string? primary, string? secondary, string close, bool suppressEnterKey = false)
    {
        var box = new MessageBox
        {
            Owner = this,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            ShowInTaskbar = false,
            Topmost = false, // Wpf.Ui makes it globally topmost; stay above the owner only
            Title = title,
            Content = new TextBlock { Text = text, TextWrapping = TextWrapping.Wrap, MaxWidth = 460 },
            PrimaryButtonText = primary ?? "",
            IsPrimaryButtonEnabled = primary is not null,
            PrimaryButtonAppearance = ControlAppearance.Primary,
            SecondaryButtonText = secondary ?? "",
            IsSecondaryButtonEnabled = secondary is not null,
            CloseButtonText = close,
        };
        // MessageBox is a plain Window with no built-in default-button/Enter-key handling, so for
        // destructive prompts we swallow Enter entirely rather than risk it silently hitting whichever
        // button the internal template happens to focus first.
        if (suppressEnterKey)
            box.PreviewKeyDown += (_, e) => e.Handled = e.Key == Key.Enter;
        return await box.ShowDialogAsync();
    }

    // ---- Theme, about, license, closing ----

    void ApplyTheme(ThemeChoice choice)
    {
        settings.Theme = choice;
        // IsLoaded can be true slightly before WPF-UI's own Loaded hook (registered inside Watch())
        // has actually attached - switching theme in that narrow window makes UnWatch throw even
        // though nothing is actively watched yet, which is harmless to ignore.
        if (IsLoaded)
        {
            try { SystemThemeWatcher.UnWatch(this); }
            catch (InvalidOperationException) { }
        }
        if (choice == ThemeChoice.System)
        {
            // Follows Windows live, including High Contrast.
            ApplicationThemeManager.ApplySystemTheme(true);
            SystemThemeWatcher.Watch(this, WindowBackdropType.None, true);
        }
        else
        {
            ApplicationThemeManager.Apply(choice == ThemeChoice.Dark ? ApplicationTheme.Dark : ApplicationTheme.Light, WindowBackdropType.None, true);
        }
        ThemeSystem.IsChecked = choice == ThemeChoice.System;
        ThemeLight.IsChecked = choice == ThemeChoice.Light;
        ThemeDark.IsChecked = choice == ThemeChoice.Dark;
        ThemeMenu.Icon = new SymbolIcon(choice switch
        {
            ThemeChoice.Light => SymbolRegular.WeatherSunny24,
            ThemeChoice.Dark => SymbolRegular.WeatherMoon24,
            _ => SymbolRegular.DarkTheme24,
        });
    }

    void OnThemePicked(object sender, RoutedEventArgs e) => ApplyTheme(Enum.Parse<ThemeChoice>((string)((FrameworkElement)sender).Tag));

    async void OnResetSettings(object sender, RoutedEventArgs e)
    {
        if (running is not null)
        {
            StatusText.Text = "Finish the current conversion first.";
            return;
        }
        if (await Ask("Reset to defaults?",
                "This resets the save location, PDF/A format, subfolder options, and theme back to their defaults. The current file list is left as-is.",
                "Reset", null, "Cancel") != MessageBoxResult.Primary)
            return;

        var fresh = new Settings();
        settings.OutputDirectory = fresh.OutputDirectory;
        settings.SaveMode = fresh.SaveMode;
        settings.Format = fresh.Format;
        settings.IncludeSubfolders = fresh.IncludeSubfolders;
        settings.PreserveSubfolders = fresh.PreserveSubfolders;
        settings.Theme = fresh.Theme;
        settings.Save();

        outputDir = null;
        FormatBox.SelectedItem = fresh.Format;
        SubfoldersBox.IsChecked = fresh.IncludeSubfolders;
        PreserveStructureBox.IsChecked = fresh.PreserveSubfolders;
        NextRadio.IsChecked = true;
        UpdateFolderText();
        ApplyTheme(fresh.Theme);
        StatusText.Text = "Settings reset to defaults.";
    }

    void OnMore(object sender, RoutedEventArgs e)
    {
        MoreButton.ContextMenu.PlacementTarget = MoreButton;
        // Deferred: opening a ContextMenu synchronously inside the same Click that raised it can
        // race WPF's internal Popup/binding setup and throw a NullReferenceException deep in
        // FrugalMap (a known WPF issue). Waiting for the click to fully unwind avoids it.
        Dispatcher.BeginInvoke(() => MoreButton.ContextMenu.IsOpen = true, System.Windows.Threading.DispatcherPriority.Input);
    }

    void OnAbout(object sender, RoutedEventArgs e) => new AboutWindow(version) { Owner = this }.ShowDialog();

    void OnLicense(object sender, RoutedEventArgs e) => new LicenseWindow { Owner = this }.ShowDialog();

    async void OnClosing(object? sender, CancelEventArgs e)
    {
        if (running is null)
        {
            if (Mode != SaveMode.Overwrite)
                settings.SaveMode = Mode; // overwrite is never remembered, so a restart never starts destructive
            settings.OutputDirectory = outputDir;
            settings.Format = (string)FormatBox.SelectedItem;
            settings.IncludeSubfolders = SubfoldersBox.IsChecked == true;
            settings.PreserveSubfolders = PreserveStructureBox.IsChecked == true;
            settings.Save();
            return;
        }
        e.Cancel = true;
        if (!closeWhenDone && await Ask("Conversion in progress", "Cancel the current conversion and exit?", "Cancel and exit", null, "Keep working") == MessageBoxResult.Primary)
        {
            closeWhenDone = true;
            OnCancel(this, new RoutedEventArgs());
        }
    }
}
