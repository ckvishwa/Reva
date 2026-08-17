namespace Reva.Desktop.Services;

public sealed class MicrophoneArbiter : IMicrophoneArbiter
{
    private readonly object _gate = new();
    private MicrophoneOwner? _currentOwner;

    public MicrophoneOwner? CurrentOwner
    {
        get
        {
            lock (_gate)
            {
                return _currentOwner;
            }
        }
    }

    public Task<IMicrophoneLease?> TryAcquireAsync(
        MicrophoneOwner owner,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        lock (_gate)
        {
            if (_currentOwner is not null)
            {
                return Task.FromResult<IMicrophoneLease?>(null);
            }

            _currentOwner = owner;
            return Task.FromResult<IMicrophoneLease?>(new Lease(this, owner));
        }
    }

    private void Release(Lease lease)
    {
        lock (_gate)
        {
            if (lease.IsActive && _currentOwner == lease.Owner)
            {
                _currentOwner = null;
                lease.MarkInactive();
            }
        }
    }

    private sealed class Lease : IMicrophoneLease
    {
        private readonly MicrophoneArbiter _owner;

        public Lease(MicrophoneArbiter owner, MicrophoneOwner leaseOwner)
        {
            _owner = owner;
            Owner = leaseOwner;
            IsActive = true;
        }

        public MicrophoneOwner Owner { get; }

        public bool IsActive { get; private set; }

        public ValueTask DisposeAsync()
        {
            _owner.Release(this);
            return ValueTask.CompletedTask;
        }

        public void MarkInactive() => IsActive = false;
    }
}
