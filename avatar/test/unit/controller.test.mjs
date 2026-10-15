import { test } from 'node:test';
import assert from 'node:assert/strict';
import { AvatarController, EXPRESSION_BLEND_SECONDS, MOUTH_TIMEOUT_MS, VERIFIED_FACE_HOLD_MS } from '../../src/controller.js';

const seeded = () => {
  let s = 12345;
  return () => {
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    return s / 0x7fffffff;
  };
};
const make = (options = {}) => new AvatarController({ random: seeded(), ...options });
const state = (c, name, epoch, now = 0) => c.handle({ type: 'avatar.state', state: name, turn_epoch: epoch }, now);
const mouth = (c, rms, epoch, now) => c.handle({ type: 'avatar.mouth', t_ms: now, rms, turn_epoch: epoch }, now);
function run(c, seconds, start = 0, fps = 60) {
  let frame;
  const dt = 1 / fps;
  for (let t = 0; t < seconds; t += dt) frame = c.update(dt, start + t * 1000);
  return frame;
}

// ------------------------------------------------------------- state mirrors the host

test('the avatar mirrors exactly the state the host sends, for every state', () => {
  const c = make();
  for (const [i, name] of ['idle', 'listening', 'thinking', 'speaking', 'approval', 'error'].entries()) {
    assert.equal(state(c, name, i).ok, true);
    assert.equal(c.update(0.016, i * 100).state, name);
  }
});

test('it never becomes listening on its own: only the host message does it', () => {
  const c = make();
  run(c, 5);
  mouth(c, 0.5, 0, 100);
  c.handle({ type: 'avatar.expression', name: 'happy', cause: 'mood' }, 200);
  assert.equal(c.update(0.016, 300).state, 'idle');
});

test('a state from an older turn_epoch is dropped and counted', () => {
  const c = make();
  state(c, 'speaking', 5);
  const result = state(c, 'listening', 4);

  assert.deepEqual(result, { ok: false, reason: 'stale' });
  assert.equal(c.state, 'speaking');
  assert.equal(c.stats.droppedStale, 1);
});

test('a newer epoch is accepted, and the same epoch can change state', () => {
  const c = make();
  state(c, 'listening', 3);
  assert.equal(state(c, 'thinking', 3).ok, true);
  assert.equal(state(c, 'idle', 9).ok, true);
  assert.equal(c.epoch, 9);
});

// -------------------------------------------------------------------------- mouth

test('the mouth moves with the audio while speaking', () => {
  const c = make();
  state(c, 'speaking', 1);
  mouth(c, 0.7, 1, 0);
  const frame = run(c, 0.1);

  assert.ok(frame.mouth.aa > 0.3, `aa ${frame.mouth.aa}`);
});

test('the mouth never moves while not speaking, whatever the host sends', () => {
  for (const name of ['idle', 'listening', 'thinking', 'approval', 'error']) {
    const c = make();
    state(c, name, 1);
    const result = mouth(c, 1, 1, 0);
    const frame = run(c, 0.2);

    assert.equal(result.ok, false, name);
    assert.equal(frame.mouth.aa, 0, name);
  }
});

test('mouth events from an older epoch are dropped', () => {
  const c = make();
  state(c, 'speaking', 4);
  const result = mouth(c, 1, 3, 0);

  assert.equal(result.reason, 'stale');
  assert.equal(run(c, 0.1).mouth.aa, 0);
});

test('an interrupt closes the mouth at once, not after a fade', () => {
  const c = make();
  state(c, 'speaking', 1);
  mouth(c, 1, 1, 0);
  run(c, 0.2);
  assert.ok(c.mouth.aa > 0.3);

  state(c, 'listening', 2, 300);

  assert.equal(c.mouth.aa, 0);
  assert.equal(c.update(0.016, 316).mouth.aa, 0);
});

test('a newer epoch on a mouth message resets the mouth before applying it', () => {
  const c = make();
  state(c, 'speaking', 1);
  mouth(c, 1, 1, 0);
  run(c, 0.2);

  mouth(c, 0.0, 2, 250);

  assert.equal(c.epoch, 2);
  assert.equal(c.mouth.aa, 0);
});

test('if the host goes quiet while speaking the mouth closes', () => {
  const c = make();
  state(c, 'speaking', 1);
  mouth(c, 1, 1, 0);
  run(c, 0.1, 0);
  assert.ok(c.mouth.aa > 0.3);

  const frame = run(c, 0.6, MOUTH_TIMEOUT_MS + 50);

  assert.ok(frame.mouth.aa < 0.05, `aa ${frame.mouth.aa}`);
});

test('visemes drive their own shapes', () => {
  const c = make();
  state(c, 'speaking', 1);
  c.handle({ type: 'avatar.mouth', t_ms: 0, viseme: 'ou', turn_epoch: 1 }, 0);
  const frame = run(c, 0.2);

  assert.ok(frame.mouth.ou > 0.4);
  assert.equal(frame.mouth.aa, 0);
});

// ------------------------------------------------------------------- expressions

const face = (c, name, cause, extra = {}) => c.handle({ type: 'avatar.expression', name, cause, ...extra }, c.clock);
const strongest = (frame) => Object.entries(frame.expression).sort((a, b) => b[1] - a[1])[0][0];

test('expressions blend over about 200 ms, not instantly', () => {
  const c = make();
  face(c, 'happy', 'mood');
  const early = c.update(0.05, 50);
  assert.ok(early.expression.happy > 0 && early.expression.happy < 0.6);
  const done = run(c, EXPRESSION_BLEND_SECONDS + 0.1, 100);
  assert.equal(done.expression.happy, 1);
  assert.equal(done.expression.relaxed, 0);
});

test('reduced motion switches faces without blending and stops idle sway', () => {
  const c = make({ reducedMotion: true });
  face(c, 'happy', 'mood');
  const frame = c.update(0.016, 5000);

  assert.equal(frame.expression.happy, 1);
  const a = c.update(0.016, 6000);
  const b = c.update(0.016, 9000);
  assert.equal(JSON.stringify(a.head), JSON.stringify(b.head));
  assert.equal(JSON.stringify(a.spine), JSON.stringify(b.spine));
});

test('idle sway exists when motion is allowed', () => {
  const c = make();
  const a = run(c, 2, 0).head;
  const b = run(c, 2, 6000).head;
  assert.notDeepEqual(a, b);
});

test('during an approval the face is neutral and expression events are ignored', () => {
  const c = make();
  face(c, 'happy', 'mood');
  state(c, 'approval', 1);
  const result = face(c, 'happy', 'mood');

  assert.equal(result.ok, false);
  assert.equal(strongest(run(c, 0.5)), 'neutral');
  assert.equal(c.update(0.016, 600).state, 'approval');
});

test('on error the face is sad whatever else was requested', () => {
  const c = make();
  face(c, 'happy', 'mood');
  state(c, 'error', 1);

  assert.equal(strongest(run(c, 0.5)), 'sad');
  assert.equal(face(c, 'surprised', 'mood').ok, false);
});

test('a positive face cannot be attached to an error cause', () => {
  const c = make();
  assert.equal(face(c, 'happy', 'error').ok, false);
  assert.equal(face(c, 'surprised', 'error').ok, false);
  assert.equal(face(c, 'sad', 'error').ok, true);
});

test('a result face needs a verified outcome with an action id, and fades back by itself', () => {
  const c = make();
  assert.equal(face(c, 'happy', 'verified_outcome').ok, false);
  assert.equal(c.stats.rejected, 1);

  assert.equal(face(c, 'happy', 'verified_outcome', { action_id: 'act-12345678' }).ok, true);
  assert.equal(strongest(run(c, 0.5, 0)), 'happy');

  const later = run(c, 0.6, VERIFIED_FACE_HOLD_MS + 500);
  assert.equal(strongest(later), 'relaxed');
});

test('a mood face persists until replaced', () => {
  const c = make();
  face(c, 'sad', 'mood');
  assert.equal(strongest(run(c, 30, 0)), 'sad');
});

// --------------------------------------------------------------------------- blinks

test('the avatar blinks every few seconds and more often while listening', () => {
  const count = (stateName) => {
    const c = make();
    state(c, stateName, 1);
    let blinks = 0;
    let was = false;
    for (let i = 0; i < 60 * 60; i += 1) {
      const frame = c.update(1 / 60, i * 16.67);
      const now = frame.blink > 0.5;
      if (now && !was) blinks += 1;
      was = now;
    }
    return blinks;
  };

  const idle = count('idle');
  const listening = count('listening');

  assert.ok(idle >= 8 && idle <= 30, `idle ${idle}`);
  assert.ok(listening > idle, `${listening} vs ${idle}`);
});

// ------------------------------------------------------------------- poses/settings

test('each state has its own pose', () => {
  const heads = {};
  for (const name of ['idle', 'listening', 'thinking', 'speaking', 'approval', 'error']) {
    const c = make({ reducedMotion: true });
    state(c, name, 1);
    const frame = c.update(0.016, 0);
    heads[name] = JSON.stringify([frame.head.x, frame.head.y, frame.head.z].map((v) => +v.toFixed(3)));
  }
  assert.equal(new Set(Object.values(heads)).size, 6, JSON.stringify(heads));
});

test('thinking looks up and the error pose looks down', () => {
  const t = make({ reducedMotion: true });
  state(t, 'thinking', 1);
  const e = make({ reducedMotion: true });
  state(e, 'error', 1);

  assert.ok(t.update(0.016, 0).lookUp > 0.5);
  assert.ok(e.update(0.016, 0).head.x > 0.1);
});

test('settings turn the avatar off, set reduced motion and quality, and close the mouth', () => {
  const c = make();
  state(c, 'speaking', 1);
  mouth(c, 1, 1, 0);
  run(c, 0.1);

  c.handle({ type: 'avatar.settings', enabled: false, reduced_motion: true, quality: 'low' }, 200);

  assert.equal(c.enabled, false);
  assert.equal(c.reducedMotion, true);
  assert.equal(c.quality, 'low');
  assert.equal(c.mouth.aa, 0);
  assert.equal(c.update(0.016, 300).enabled, false);
});

test('a refused message changes nothing', () => {
  const c = make();
  state(c, 'listening', 2);
  const before = JSON.stringify([c.state, c.epoch, c.baseExpression, c.enabled]);

  for (const bad of [{ type: 'avatar.state', state: 'dancing', turn_epoch: 9 }, { type: 'nope' }, null, 'x']) {
    assert.equal(c.handle(bad, 0).ok, false);
  }

  assert.equal(JSON.stringify([c.state, c.epoch, c.baseExpression, c.enabled]), before);
  assert.equal(c.stats.rejected, 4);
});
