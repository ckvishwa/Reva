namespace Reva.Desktop.Services;

public static class VoiceLanguageResolver
{
    public static string Resolve(string text)
    {
        var telugu = 0;
        var letters = 0;
        foreach (var ch in text)
        {
            if (!char.IsLetter(ch))
            {
                continue;
            }

            letters++;
            if (ch is >= '\u0C00' and <= '\u0C7F')
            {
                telugu++;
            }
        }

        return letters > 0 && telugu > letters / 2 ? "te" : "en";
    }
}
