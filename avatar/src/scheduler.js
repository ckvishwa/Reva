// Frame pacing and quality (AR-WIN-007, NFR-019): at most 60 fps, nothing drawn when hidden or off.

export const QUALITY = {
  low: { fps: 30, pixelRatio: 0.6, antialias: false },
  medium: { fps: 60, pixelRatio: 1, antialias: true },
  high: { fps: 60, pixelRatio: 2, antialias: true },
};

export const MAX_FPS = 60;

/** Whether enough time has passed to draw another frame at this quality's rate. */
export function shouldRender(nowMs, lastRenderMs, quality = 'medium') {
  const fps = Math.min(MAX_FPS, (QUALITY[quality] ?? QUALITY.medium).fps);
  return nowMs - lastRenderMs >= 1000 / fps - 1; // 1 ms of slack for timer jitter
}

/** True when the page should not draw at all. */
export function paused({ hidden, enabled }) {
  return hidden === true || enabled === false;
}

export function pixelRatioFor(quality, devicePixelRatio = 1) {
  const q = QUALITY[quality] ?? QUALITY.medium;
  return Math.max(0.5, Math.min(q.pixelRatio, devicePixelRatio || 1));
}
