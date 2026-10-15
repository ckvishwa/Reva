using System.Threading.Channels;

namespace Reva.Desktop.Voice;

public enum LiveVoiceState
{
    Off,
    Connecting,
    Ready,
    Listening,
    Thinking,
    Approval,
    Speaking,
    Error,
}

/// <summary>
/// The Windows end of the real voice loop (MASTER-LOOP B1). It owns no model and no policy: it
/// opens the microphone, streams 16 kHz PCM to the Core session while push-to-talk is held, plays
/// the reply Core hands back, and reports what is really happening.
///
/// Rules it keeps:
///  * <c>Listening</c> is shown only while the microphone device is really open and being sent.
///    The microphone is closed whenever push-to-talk is not held (no always-on mic).
///  * A mic that disappears returns the loop to a safe idle and tells Core (<c>capture.lost</c>).
///  * Playback belongs to one <c>turn_epoch</c>. A newer epoch, a push-to-talk press, a mute or a
///    stop cuts playback at once; a reply for an older epoch is never played.
///  * Mic mute and speaker mute are separate. A muted speaker still reports the reply as finished.
/// </summary>
public sealed class VoiceLoopController : IAsyncDisposable
{
    private const int MaxQueuedAudioChunks = 400;
    public static readonly TimeSpan ReleaseTail = TimeSpan.FromMilliseconds(180);

    private readonly IVoiceSessionClient _client;
    private readonly IAudioCapture _capture;
    private readonly IAudioPlayback _playback;
    private readonly IPushToTalkSource? _hotkey;
    private readonly Func<TimeSpan, Task> _delay;
    private readonly SemaphoreSlim _gate = new(1, 1);
    private readonly Channel<Outgoing> _outbox = Channel.CreateUnbounded<Outgoing>();
    private readonly Channel<bool> _gestures = Channel.CreateUnbounded<bool>();
    private Task? _sender;
    private Task? _gestureLoop;
    private int _queuedAudio;
    private int _epoch;
    private string _coreState = "idle";
    private bool _pttActive;
    private bool _overflow;
    private bool _running;
    private bool _disposed;

    public VoiceLoopController(
        IVoiceSessionClient client,
        IAudioCapture capture,
        IAudioPlayback playback,
        IPushToTalkSource? hotkey = null,
        Func<TimeSpan, Task>? delay = null)
    {
        _client = client;
        _capture = capture;
        _playback = playback;
        _hotkey = hotkey;
        _delay = delay ?? (span => Task.Delay(span));
        _client.EventReceived += OnEvent;
        _client.Disconnected += OnDisconnected;
        _capture.Frame += OnFrame;
        _capture.Lost += OnCaptureLost;
        _playback.Finished += OnPlaybackFinished;
        _playback.Level += level => PlaybackLevel?.Invoke(level);
        if (_hotkey is not null)
        {
            // Press and release go through one queue so a quick tap can never be reordered.
            _hotkey.Pressed += () => _gestures.Writer.TryWrite(true);
            _hotkey.Released += () => _gestures.Writer.TryWrite(false);
        }
    }

    public event Action? Changed;

    /// <summary>Every event Core sends, after the loop has handled it (the avatar reads faces from these).</summary>
    public event Action<VoiceEvent>? CoreEvent;

    /// <summary>Loudness of the reply being played; only for the current turn.</summary>
    public event Action<PlaybackLevel>? PlaybackLevel;

    public LiveVoiceState State { get; private set; } = LiveVoiceState.Off;

    /// <summary>A fixed, safe sentence for the user; null when there is nothing to say.</summary>
    public string? Message { get; private set; }

    public bool MicMuted { get; private set; }

    public bool SpeakerMuted { get; private set; }

    public string? DeviceId { get; set; }

    public string? LastTranscript { get; private set; }

    public string? LastReply { get; private set; }

    /// <summary>Why the answer came from the local model when the cloud one was expected.</summary>
    public string? LastNotice { get; private set; }

    /// <summary>True only while the microphone device is really open.</summary>
    public bool MicOpen => _capture.IsOpen;

    public int TurnEpoch => _epoch;

    public IReadOnlyList<AudioDeviceInfo> ListMicrophones() => _capture.ListDevices();

    // ------------------------------------------------------------------ session

    public async Task StartAsync(CancellationToken cancellationToken = default)
    {
        await _gate.WaitAsync(cancellationToken);
        try
        {
            if (_running || _disposed)
            {
                return;
            }

            Set(LiveVoiceState.Connecting, null);
            var failure = await _client.ConnectAsync(cancellationToken);
            if (failure is not null)
            {
                Set(LiveVoiceState.Error, failure);
                return;
            }

            _running = true;
            _coreState = "idle";
            _sender = Task.Run(SendLoopAsync, CancellationToken.None);
            _gestureLoop = Task.Run(GestureLoopAsync, CancellationToken.None);
            _hotkey?.Enable();
            Set(LiveVoiceState.Ready, null);
        }
        finally
        {
            _gate.Release();
        }
    }

    public async Task StopAsync()
    {
        await _gate.WaitAsync();
        try
        {
            if (!_running)
            {
                return;
            }

            _running = false;
            _hotkey?.Disable();
            _playback.Flush();
            StopCapture();
            _pttActive = false;
            Enqueue(new Outgoing(VoiceControl.Cancel, null, null));
            _outbox.Writer.TryComplete();
            if (_sender is not null)
            {
                await _sender;
                _sender = null;
            }

            _gestureLoop = null; // it ends on its own once _running is false

            await _client.CloseAsync();
            LastTranscript = null;
            LastReply = null;
            LastNotice = null;
            Set(LiveVoiceState.Off, null);
        }
        finally
        {
            _gate.Release();
        }
    }

    // ------------------------------------------------------------- push-to-talk

    /// <summary>Push-to-talk pressed (button or hotkey).</summary>
    public async Task PressAsync()
    {
        await _gate.WaitAsync();
        try
        {
            if (!_running || _pttActive)
            {
                return;
            }

            _playback.Flush(); // the cut is local and immediate; Core is told below
            if (MicMuted)
            {
                Set(State, "The microphone is muted.");
                return;
            }

            if (!await TryStartCaptureAsync())
            {
                return;
            }

            if (_coreState is "idle" or "recoverable_error")
            {
                Enqueue(new Outgoing(VoiceControl.CaptureRequested, null, null));
                Enqueue(new Outgoing(VoiceControl.CaptureOpen, null, null));
                _coreState = "listening";
            }

            _overflow = false;
            _pttActive = true;
            Enqueue(new Outgoing(VoiceControl.PttDown, null, null));
            Set(LiveVoiceState.Listening, null);
        }
        finally
        {
            _gate.Release();
        }
    }

    /// <summary>Push-to-talk released: send the tail of the audio, then close the microphone.</summary>
    public async Task ReleaseAsync()
    {
        if (!_running || !_pttActive)
        {
            return;
        }

        await _delay(ReleaseTail); // the last syllable is still in the device buffer
        await _gate.WaitAsync();
        try
        {
            if (!_pttActive)
            {
                return;
            }

            _pttActive = false;
            StopCapture();
            Enqueue(new Outgoing(_overflow ? VoiceControl.PttCancel : VoiceControl.PttUp, null, null));
            if (_overflow)
            {
                Set(LiveVoiceState.Ready, "That was too long to send. Try a shorter question.");
            }
            else
            {
                Set(LiveVoiceState.Thinking, null);
            }
        }
        finally
        {
            _gate.Release();
        }
    }

    public async Task SetMicMutedAsync(bool muted)
    {
        await _gate.WaitAsync();
        try
        {
            if (MicMuted == muted)
            {
                return;
            }

            MicMuted = muted;
            if (muted && _pttActive)
            {
                _pttActive = false;
                StopCapture();
                Enqueue(new Outgoing(VoiceControl.PttCancel, null, null));
            }

            Enqueue(new Outgoing(muted ? VoiceControl.MicMute : VoiceControl.MicUnmute, null, null));
            Set(_running && State == LiveVoiceState.Listening ? LiveVoiceState.Ready : State, null);
        }
        finally
        {
            _gate.Release();
        }
    }

    public async Task SetSpeakerMutedAsync(bool muted)
    {
        await _gate.WaitAsync();
        try
        {
            SpeakerMuted = muted;
            if (muted && _playback.IsPlaying)
            {
                _playback.Flush();
                Enqueue(new Outgoing(VoiceControl.PlaybackFinished, _epoch, null));
            }

            Set(State, null);
        }
        finally
        {
            _gate.Release();
        }
    }

    /// <summary>Stop talking: cut the reply and interrupt the turn.</summary>
    public async Task InterruptAsync()
    {
        await _gate.WaitAsync();
        try
        {
            _playback.Flush();
            if (_running)
            {
                Enqueue(new Outgoing(VoiceControl.Interrupt, null, null));
            }
        }
        finally
        {
            _gate.Release();
        }
    }

    // ------------------------------------------------------------------ capture

    private async Task<bool> TryStartCaptureAsync()
    {
        if (_capture.IsOpen)
        {
            return true;
        }

        try
        {
            var device = DeviceId;
            await Task.Run(() => _capture.Start(device)); // device start takes tens of ms: off the UI thread
            return true;
        }
        catch (CaptureStartException ex)
        {
            if (_coreState is "idle" or "recoverable_error")
            {
                Enqueue(new Outgoing(VoiceControl.CaptureRequested, null, null));
                _coreState = "acquiring_permission";
            }

            if (ex.Failure == CaptureFailure.PermissionDenied)
            {
                Enqueue(new Outgoing(VoiceControl.CaptureDenied, null, null));
            }

            Set(
                State == LiveVoiceState.Off ? LiveVoiceState.Off : LiveVoiceState.Error,
                ex.Failure switch
                {
                    CaptureFailure.NoDevice => "No microphone was found.",
                    CaptureFailure.PermissionDenied => "Windows is blocking microphone access for REVA.",
                    _ => "The microphone could not be started.",
                });
            return false;
        }
    }

    private void StopCapture()
    {
        try
        {
            _capture.Stop();
        }
        catch (Exception)
        {
            // Stopping a device that is already gone is not an error worth surfacing.
        }
    }

    private void OnFrame(byte[] pcm)
    {
        if (!_pttActive || MicMuted || _overflow)
        {
            return;
        }

        if (Volatile.Read(ref _queuedAudio) >= MaxQueuedAudioChunks)
        {
            _overflow = true; // the network stalled: this utterance is dropped whole, never sent in part
            return;
        }

        Interlocked.Increment(ref _queuedAudio);
        Enqueue(new Outgoing(null, null, pcm));
    }

    private void OnCaptureLost()
    {
        _ = Task.Run(async () =>
        {
            await _gate.WaitAsync();
            try
            {
                if (!_running)
                {
                    return;
                }

                _pttActive = false;
                StopCapture();
                Enqueue(new Outgoing(VoiceControl.CaptureLost, null, null));
                _coreState = "idle";
                Set(LiveVoiceState.Ready, "The microphone was disconnected.");
            }
            finally
            {
                _gate.Release();
            }
        });
    }

    // ----------------------------------------------------------- events from Core

    private void OnEvent(VoiceEvent ev)
    {
        if (ev.TurnEpoch > _epoch)
        {
            _epoch = ev.TurnEpoch;
            _playback.Flush(); // anything still playing belongs to an older turn
        }

        try
        {
            HandleCoreEvent(ev);
        }
        finally
        {
            CoreEvent?.Invoke(ev);
        }
    }

    private void HandleCoreEvent(VoiceEvent ev)
    {
        switch (ev.Kind)
        {
            case "session.state":
                OnCoreState(ev.Text("state") ?? string.Empty);
                break;
            case "speech.transcript.final":
                LastTranscript = ev.Text("text");
                LastNotice = null;
                Raise();
                break;
            case "assistant.text.final":
                LastReply = ev.Text("text");
                LastNotice = ev.Text("notice");
                Raise();
                break;
            case "tts.started" when ev.Text("purpose") == "reply":
                _ = PlayReplyAsync(ev);
                break;
            case "tts.stopped" when ev.Text("reason") == "interrupt":
                _playback.Flush();
                break;
            case "error":
                OnCoreError(ev.Text("code") ?? string.Empty);
                break;
        }
    }

    private void OnCoreState(string state)
    {
        _coreState = state;
        var next = state switch
        {
            "listening" => _pttActive ? LiveVoiceState.Listening : LiveVoiceState.Ready,
            "endpointing" or "transcribing" or "reasoning" or "executing" => LiveVoiceState.Thinking,
            "approval_pending" => LiveVoiceState.Approval,
            "speaking" => LiveVoiceState.Speaking,
            "idle" or "cancelling" => LiveVoiceState.Ready,
            "recoverable_error" or "fatal_error" => LiveVoiceState.Error,
            _ => State,
        };
        if (State != LiveVoiceState.Off && !(State == LiveVoiceState.Error && next == LiveVoiceState.Ready))
        {
            Set(next, next == LiveVoiceState.Error ? Message : null);
        }
    }

    private void OnCoreError(string code)
    {
        var text = code switch
        {
            "STT_UNAVAILABLE" => "Speech recognition isn't available right now.",
            "STT_NO_TRANSCRIPT" => "I didn't catch that.",
            "STT_TIMEOUT" => "Speech recognition took too long.",
            "MODEL_TIMEOUT" => "That took too long to answer.",
            "TTS_UNAVAILABLE" or "TTS_TIMEOUT" => "I couldn't speak that reply. The text is above.",
            "UTTERANCE_TOO_LONG" => "That was too long. Try a shorter question.",
            "CAPTURE_LOST" => "The microphone was disconnected.",
            "PERMISSION_DENIED" => "Windows is blocking microphone access for REVA.",
            _ => "Something went wrong with voice.",
        };
        Set(State == LiveVoiceState.Off ? State : LiveVoiceState.Ready, text);
    }

    private async Task PlayReplyAsync(VoiceEvent ev)
    {
        var epoch = ev.TurnEpoch;
        var path = ev.Text("audio_path");
        if (path is null)
        {
            return;
        }

        var wav = await _client.FetchAudioAsync(path);
        if (epoch != _epoch)
        {
            return; // a barge-in happened while it was downloading
        }

        if (wav is null)
        {
            Enqueue(new Outgoing(VoiceControl.PlaybackFinished, epoch, null));
            Set(State, "I couldn't fetch the spoken reply. The text is above.");
            return;
        }

        if (SpeakerMuted)
        {
            Enqueue(new Outgoing(VoiceControl.PlaybackFinished, epoch, null));
            return;
        }

        try
        {
            _playback.Play(wav, epoch);
        }
        catch (Exception)
        {
            Enqueue(new Outgoing(VoiceControl.PlaybackFinished, epoch, null));
            Set(State, "I couldn't play the reply on this speaker.");
        }
    }

    private void OnPlaybackFinished(int epoch)
    {
        if (epoch == _epoch)
        {
            Enqueue(new Outgoing(VoiceControl.PlaybackFinished, epoch, null));
        }
    }

    private void OnDisconnected(string reason)
    {
        _ = Task.Run(async () =>
        {
            await _gate.WaitAsync();
            try
            {
                if (!_running)
                {
                    return;
                }

                _running = false;
                _pttActive = false;
                _hotkey?.Disable();
                _playback.Flush();
                StopCapture();
                _outbox.Writer.TryComplete();
                Set(LiveVoiceState.Error, reason);
            }
            finally
            {
                _gate.Release();
            }
        });
    }

    // --------------------------------------------------------------------- sending

    private sealed record Outgoing(string? Control, int? Epoch, byte[]? Audio);

    private void Enqueue(Outgoing item) => _outbox.Writer.TryWrite(item);

    private async Task GestureLoopAsync()
    {
        while (await _gestures.Reader.WaitToReadAsync())
        {
            while (_gestures.Reader.TryRead(out var down))
            {
                if (!_running)
                {
                    continue;
                }

                if (down)
                {
                    await PressAsync();
                }
                else
                {
                    await ReleaseAsync();
                }
            }
        }
    }

    private async Task SendLoopAsync()
    {
        await foreach (var item in _outbox.Reader.ReadAllAsync())
        {
            try
            {
                if (item.Audio is not null)
                {
                    Interlocked.Decrement(ref _queuedAudio);
                    await _client.SendAudioAsync(item.Audio);
                }
                else if (item.Control is not null)
                {
                    await _client.SendControlAsync(item.Control, item.Epoch);
                }
            }
            catch (Exception)
            {
                // A failed send shows up as a disconnect from the client; keep draining so the
                // queue never grows without bound.
            }
        }
    }

    private void Set(LiveVoiceState state, string? message)
    {
        State = state;
        Message = message;
        Raise();
    }

    private void Raise() => Changed?.Invoke();

    public async ValueTask DisposeAsync()
    {
        if (_disposed)
        {
            return;
        }

        await StopAsync();
        _disposed = true;
        _client.EventReceived -= OnEvent;
        _client.Disconnected -= OnDisconnected;
        _capture.Frame -= OnFrame;
        _capture.Lost -= OnCaptureLost;
        _playback.Finished -= OnPlaybackFinished;
        _hotkey?.Dispose();
        _gestures.Writer.TryComplete();
        _gate.Dispose();
    }
}
