import { test } from 'node:test';
import assert from 'node:assert/strict';
import { advanceSchedule, MAX_FPS, paused, pixelRatioFor, QUALITY, shouldRender } from '../../src/scheduler.js';
import { estimateOffset, percentile } from '../../src/lipsyncOffset.js';

function framesOver(seconds, quality, refreshHz) {
  let last = -1e9;
  let drawn = 0;
  for (let t = 0; t < seconds * 1000; t += 1000 / refreshHz) {
    if (shouldRender(t, last, quality)) {
      last = advanceSchedule(t, last, quality);
      drawn += 1;
    }
  }
  return drawn;
}

test('the page never draws faster than 60 fps, even on a 144 Hz display', () => {
  for (const hz of [60, 75, 120, 144, 240]) {
    const drawn = framesOver(10, 'high', hz);
    assert.ok(drawn <= 10 * MAX_FPS + 2, `${hz} Hz drew ${drawn}`);
    assert.ok(drawn >= 10 * 58, `${hz} Hz drew only ${drawn}`); // the average stays at the target
  }
});

test('a long stall does not cause a burst of catch-up frames', () => {
  let last = 0;
  last = advanceSchedule(5000, last, 'high'); // the page was hidden for 5 s
  assert.equal(last, 5000);
  assert.equal(shouldRender(5005, last, 'high'), false);
});

test('low quality caps at 30 fps and draws at a smaller pixel ratio', () => {
  assert.ok(framesOver(10, 'low', 60) <= 10 * 30 + 2);
  assert.equal(QUALITY.low.fps, 30);
  assert.ok(pixelRatioFor('low', 2) < pixelRatioFor('high', 2));
  assert.equal(pixelRatioFor('high', 1), 1);
  assert.equal(pixelRatioFor('nonsense', 1), 1);
});

test('nothing is drawn when the page is hidden or the avatar is off', () => {
  assert.equal(paused({ hidden: true, enabled: true }), true);
  assert.equal(paused({ hidden: false, enabled: false }), true);
  assert.equal(paused({ hidden: false, enabled: true }), false);
});

// ----------------------------------------------------------------- lip-sync offset

const envelope = (lagMs) => {
  const audio = [];
  const mouth = [];
  const v = (time) => Math.max(0, Math.sin(time / 180) * Math.sin(time / 700));
  for (let t = 0; t <= 8000; t += 16) {
    audio.push({ t_ms: t, value: v(t) });
    mouth.push({ t_ms: t, value: v(t - lagMs) }); // the mouth shows the audio from lagMs earlier
  }
  return { audio, mouth };
};

test('the offset script recovers a known delay and a known lead', () => {
  for (const lag of [0, 40, 80, 150, -60]) {
    const { audio, mouth } = envelope(lag);
    const { offsetMs } = estimateOffset(audio, mouth);
    assert.ok(Math.abs(offsetMs - lag) <= 10, `lag ${lag} measured ${offsetMs}`);
  }
});

test('too little data gives no answer rather than a wrong one', () => {
  assert.equal(estimateOffset([], []).offsetMs, null);
  assert.equal(estimateOffset([{ t_ms: 0, value: 0 }], [{ t_ms: 0, value: 0 }]).offsetMs, null);
});

test('percentile', () => {
  assert.equal(percentile([], 95), null);
  assert.equal(percentile([10, 20, 30, 40, 50, 60, 70, 80, 90, 100], 95), 100);
  assert.equal(percentile([5, 1, 3], 50), 3);
});
