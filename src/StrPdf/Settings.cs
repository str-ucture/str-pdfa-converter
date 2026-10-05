using System.Text.Json;
using System.Text.Json.Serialization;

namespace StrPdf;

public enum ThemeChoice { System, Light, Dark }

/// <summary>Per-user preferences in %APPDATA%\str-pdf\settings.json (same file and keys as the Python v2 app).</summary>
public sealed class Settings
{
    static readonly JsonSerializerOptions Json = new()
    {
        WriteIndented = true,
        Converters = { new JsonStringEnumConverter(JsonNamingPolicy.CamelCase) },
    };

    static string FilePath => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "str-pdf", "settings.json");

    [JsonPropertyName("output_directory")] public string? OutputDirectory { get; set; }
    [JsonPropertyName("output_mode")] public SaveMode SaveMode { get; set; } = SaveMode.Next;
    [JsonPropertyName("pdfa_version")] public string Format { get; set; } = "PDF/A-2b";
    [JsonPropertyName("include_subfolders")] public bool IncludeSubfolders { get; set; }
    [JsonPropertyName("preserve_subfolders")] public bool PreserveSubfolders { get; set; } = true;
    [JsonPropertyName("theme")] public ThemeChoice Theme { get; set; } = ThemeChoice.System;

    public static Settings Load()
    {
        try
        {
            return JsonSerializer.Deserialize<Settings>(File.ReadAllText(FilePath), Json) ?? new();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException)
        {
            return new();
        }
    }

    public void Save()
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(FilePath)!);
            File.WriteAllText(FilePath, JsonSerializer.Serialize(this, Json));
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            // Preferences are a convenience; never block closing the app over them.
        }
    }
}
