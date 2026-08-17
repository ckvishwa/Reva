namespace Reva.Desktop.Services;

public enum WakeWordSubmitOutcome
{
    Empty,
    RoutedCommand,
    ComposerPopulated,
}

public sealed record WakeWordSubmitResult(WakeWordSubmitOutcome Outcome);

public interface IComposerSink
{
    void AppendTranscription(string text);

    Task<WakeWordSubmitResult> SubmitTranscriptionAsync(
        string text,
        CancellationToken cancellationToken = default);
}
