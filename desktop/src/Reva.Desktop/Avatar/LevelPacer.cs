namespace Reva.Desktop.Avatar;

/// <summary>
/// Holds mouth levels for a fixed delay before they are sent, so the mouth lines up with the sound
/// that comes out of the speakers rather than the sound handed to the audio device a moment earlier
/// (the output buffer is tens of milliseconds long). The delay is a setting that the lip-sync offset
/// measurement tunes (AR-VA-010). Time is passed in, so tests need no timers.
/// </summary>
public sealed class LevelPacer<T>
{
    private readonly object _lock = new();
    private readonly Queue<(long Due, T Item)> _queue = new();
    private readonly int _capacity;

    public LevelPacer(int delayMs, int capacity = 512)
    {
        DelayMs = Math.Clamp(delayMs, 0, 500);
        _capacity = capacity;
    }

    public int DelayMs { get; set; }

    public int Count
    {
        get
        {
            lock (_lock)
            {
                return _queue.Count;
            }
        }
    }

    /// <summary>Queue an item produced at <paramref name="nowMs"/>. A full queue drops the oldest.</summary>
    public void Add(T item, long nowMs)
    {
        lock (_lock)
        {
            if (_queue.Count >= _capacity)
            {
                _queue.Dequeue();
            }

            _queue.Enqueue((nowMs + DelayMs, item));
        }
    }

    /// <summary>Everything whose time has come, oldest first.</summary>
    public IReadOnlyList<T> TakeDue(long nowMs)
    {
        var due = new List<T>();
        lock (_lock)
        {
            while (_queue.Count > 0 && _queue.Peek().Due <= nowMs)
            {
                due.Add(_queue.Dequeue().Item);
            }
        }

        return due;
    }

    public void Clear()
    {
        lock (_lock)
        {
            _queue.Clear();
        }
    }
}
