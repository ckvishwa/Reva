namespace Reva.Desktop.Services;

public interface IChimePlayer
{
    Task PlayAsync(CancellationToken cancellationToken = default);
}

public sealed class SilentChimePlayer : IChimePlayer
{
    public Task PlayAsync(CancellationToken cancellationToken = default) => Task.CompletedTask;
}
