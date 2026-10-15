// Frame pacing and quality (AR-WIN-007, NFR-019): at most 60 fps, nothing drawn when hidden or off.

export const QUALITY = {
  low: { fps: 30, pixelRatio: 0.6, antialias: false },
  medium: { fps: 60, pixelRatio: 1, antialias: true },
  high: { fps: 60, pixelRatio: 2, antialias: true },
};

export const MAX_FPS = 60;

const intervalFor = (quality) => 1000 / Math.min(MAX_FPS, (QUALITY[quality] ?? QUALITY.medium).fps);

/** Whether the next frame is due. `scheduledMs` is the time the previous frame was scheduled for. */
export function shouldRender(nowMs, scheduledMs, quality = 'medium') {
  return nowMs - scheduledMs >= intervalFor(quality) - 1; // 1 ms of slack for timer jitter
}

/**
 * The schedule slot of the frame just drawn. Stepping by whole intervals (not "now") keeps the average at
 * the target rate on displays whose refresh is not a multiple of it (144 Hz gives 60 fps, not 48),
 * and a long stall resets the schedule instead of drawing a burst to catch up.
 */
export function advanceSchedule(nowMs, scheduledMs, quality = 'medium') {
  const interval = intervalFor(quality);
  return nowMs - scheduledMs > 2 * interval ? nowMs : scheduledMs + interval;
}

/** True when the page should not draw at all. */
export function paused({ hidden, enabled }) {
  return hidden === true || enabled === false;
}

export function pixelRatioFor(quality, devicePixelRatio = 1) {
  const q = QUALITY[quality] ?? QUALITY.medium;
  return Math.max(0.5, Math.min(q.pixelRatio, devicePixelRatio || 1));
}
