using System.Diagnostics;
using System.Globalization;

namespace Reva.Desktop.Services;

public sealed class CoreProcessLauncher : ICoreProcessLauncher
{
    public ICoreProcessHandle Launch(CoreExecutableResolution resolution, string dataDirectory, int port)
    {
        if (!resolution.IsAvailable)
        {
            throw new InvalidOperationException($"Cannot launch REVA Core: {resolution.FailureReason}");
        }

        var startInfo = new ProcessStartInfo
        {
            FileName = resolution.FileName,
            Arguments = resolution.Arguments,
            WorkingDirectory = resolution.WorkingDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        // Inherits the current process environment (ProcessStartInfo.Environment
        // is pre-populated from it); only override what Desktop must control so
        // it agrees with Core on data directory and port. Everything else
        // (REVA_ASSISTANT_ORCHESTRATOR, REVA_ADK_MODEL, ...) passes through
        // untouched if the developer already set it before launching Desktop.
        startInfo.Environment["REVA_DATA_DIR"] = dataDirectory;
        startInfo.Environment["REVA_API_PORT"] = port.ToString(CultureInfo.InvariantCulture);

        var process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
        // Slice 8A: routed to the lifecycle log file (never the UI, never
        // telemetry) instead of discarded — the flap/orphan investigation
        // was blind to Core's own stdout/stderr during the failure window.
        // DesktopLogger's sensitive-keyword redaction is defense in depth
        // here, but Core's own logs are operator-facing diagnostic text,
        // not secrets, by the same contract Desktop's own logs follow.
        // Revisit before V1 packaging: verify Core never writes anything
        // more sensitive than that assumption to stdout/stderr.
        process.OutputDataReceived += static (_, e) =>
        {
            if (e.Data is not null)
            {
                DesktopLogger.Info($"[core stdout] {e.Data}");
            }
        };
        process.ErrorDataReceived += static (_, e) =>
        {
            if (e.Data is not null)
            {
                DesktopLogger.Warn($"[core stderr] {e.Data}");
            }
        };

        if (!process.Start())
        {
            throw new InvalidOperationException("Failed to start the REVA Core process.");
        }

        process.BeginOutputReadLine();
        process.BeginErrorReadLine();

        return new CoreProcessHandle(process);
    }

    private sealed class CoreProcessHandle : ICoreProcessHandle
    {
        private readonly Process _process;
        private readonly int? _pid;

        public CoreProcessHandle(Process process)
        {
            _process = process;
            // Captured at construction: reading Process.Id after the process
            // has exited throws, and diagnostics may want the pid at that point.
            _pid = TryGetId(process);
        }

        public bool HasExited => _process.HasExited;

        public int? ExitCode => _process.HasExited ? _process.ExitCode : null;

        public int? Pid => _pid;

        public void Stop()
        {
            try
            {
                if (!_process.HasExited)
                {
                    _process.Kill(entireProcessTree: true);
                }
            }
            catch (InvalidOperationException)
            {
                // Process already exited between the HasExited check and Kill.
            }
        }

        public void Dispose() => _process.Dispose();

        private static int? TryGetId(Process process)
        {
            try
            {
                return process.Id;
            }
            catch (InvalidOperationException)
            {
                return null;
            }
        }
    }
}
