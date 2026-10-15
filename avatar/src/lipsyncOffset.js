// Lip-sync offset (AR-VA-010: offset <= 100 ms p95 against the audio that is actually playing).
//
// The Windows host records, for each ~60 Hz window of audio it plays, the sample-clock time and the RMS
// it sent to the page. The page records when each mouth value reached the model. This estimates how
// late (positive) or early (negative) the mouth is, by sliding the mouth signal against the audio
// envelope and keeping the shift with the smallest squared difference.
//
// estimateOffset returns offsetMs = how much later the mouth is than the audio (mouth lags: positive).

export function estimateOffset(audio, mouth, { maxShiftMs = 400, stepMs = 5 } = {}) {
  if (audio.length < 2 || mouth.length < 2) return { offsetMs: null, error: null };
  const sample = (series, t) => {
    if (t <= series[0].t_ms) return series[0].value;
    for (let i = 1; i < series.length; i += 1) {
      if (series[i].t_ms >= t) {
        const a = series[i - 1];
        const b = series[i];
        const span = b.t_ms - a.t_ms || 1;
        return a.value + ((b.value - a.value) * (t - a.t_ms)) / span;
      }
    }
    return series[series.length - 1].value;
  };
  const start = Math.max(audio[0].t_ms, mouth[0].t_ms) + maxShiftMs;
  const end = Math.min(audio[audio.length - 1].t_ms, mouth[mouth.length - 1].t_ms) - maxShiftMs;
  if (end <= start) return { offsetMs: null, error: null };
  let best = { offsetMs: 0, error: Infinity };
  for (let shift = -maxShiftMs; shift <= maxShiftMs; shift += stepMs) {
    let error = 0;
    let count = 0;
    for (let t = start; t < end; t += 10) {
      // If the mouth lags by `shift`, the mouth at time t + shift equals the audio at time t.
      const diff = sample(audio, t) - sample(mouth, t + shift);
      error += diff * diff;
      count += 1;
    }
    error /= count;
    if (error < best.error) best = { offsetMs: shift, error };
  }
  return best;
}

export function percentile(values, p) {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1)];
}
