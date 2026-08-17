namespace Reva.Desktop.Services;

public sealed class SystemChimePlayer : IChimePlayer
{
    public Task PlayAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        try
        {
            Console.Beep(880, 120);
        }
        catch
        {
            DesktopLogger.Info("wakeword.chime_failed");
        }

        return Task.CompletedTask;
    }
}
