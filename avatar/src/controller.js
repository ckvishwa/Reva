// The avatar's brain: events in, a frame of pose/expression/mouth values out. No three.js, no DOM,
// no clock of its own (the caller passes time), so it is fully testable in plain Node.
//
// The avatar shows only true state (CLAUDE.md):
//   * "listening" is whatever the host says the microphone is doing, never inferred here;
//   * the mouth moves only while the host says speaking, from the audio that is actually playing;
//   * a message from an older turn_epoch is dropped (the host has already moved on);
//   * a positive face for an action result needs cause "verified_outcome" (schema-enforced) and
//     it fades back on its own; during an approval the face stays neutral, and on error it is sad.

import { validate } from './protocol.js';
import { POSES } from './pose.js';

export const POSITIVE = ['happy', 'surprised'];
export const EXPRESSION_BLEND_SECONDS = 0.2; // persona: expression changes blend over 150-250 ms
export const MOUTH_TIMEOUT_MS = 150; // no mouth event for this long while speaking: close
export const VERIFIED_FACE_HOLD_MS = 4000;
const MOUTH_ATTACK = 0.03;
const MOUTH_RELEASE = 0.07;
const POSE_TAU = 0.25;
const BLINK_SECONDS = 0.14;

const VISEME_SHAPES = { aa: 'aa', ih: 'ih', ou: 'ou', ee: 'ee', oh: 'oh' };

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

export class AvatarController {
  constructor({ random = Math.random, reducedMotion = false, now = 0 } = {}) {
    this.random = random;
    this.state = 'idle';
    this.epoch = 0;
    this.enabled = true;
    this.reducedMotion = reducedMotion;
    this.quality = 'medium';
    this.stats = { droppedStale: 0, rejected: 0, ignored: 0 };

    this.baseExpression = 'relaxed'; // what the face rests on between events
    this.heldExpression = null; // a result face, with its own expiry
    this.heldUntilMs = 0;
    this.weights = { neutral: 0, happy: 0, sad: 0, relaxed: 1, surprised: 0 };

    this.mouthTarget = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };
    this.mouth = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };
    this.lastMouthMs = Number.NEGATIVE_INFINITY;

    this.pose = { ...POSES.idle };
    this.blinkTimer = this.nextBlinkIn();
    this.blinkProgress = -1; // -1: not blinking
    this.clock = now;
  }

  // ------------------------------------------------------------------ events

  /** Applies one host message. Returns {ok, reason}; a refused message changes nothing. */
  handle(message, nowMs = this.clock) {
    const problem = validate(message);
    if (problem !== null) {
      this.stats.rejected += 1;
      return { ok: false, reason: problem };
    }
    switch (message.type) {
      case 'avatar.state':
        return this.onState(message);
      case 'avatar.mouth':
        return this.onMouth(message, nowMs);
      case 'avatar.expression':
        return this.onExpression(message, nowMs);
      case 'avatar.settings':
        return this.onSettings(message);
      default:
        return { ok: false, reason: 'unknown type' };
    }
  }

  onState(message) {
    if (message.turn_epoch < this.epoch) return this.stale();
    const previous = this.state;
    this.epoch = message.turn_epoch;
    this.state = message.state;
    if (previous === 'speaking' && message.state !== 'speaking') {
      // Interrupt or end of speech: the mouth stops with the audio, not after a fade.
      this.closeMouthNow();
    }
    if (message.state === 'approval' || message.state === 'error') this.heldExpression = null;
    return { ok: true };
  }

  onMouth(message, nowMs) {
    if (message.turn_epoch < this.epoch) return this.stale();
    if (message.turn_epoch > this.epoch) {
      this.epoch = message.turn_epoch;
      this.closeMouthNow();
    }
    if (this.state !== 'speaking') {
      this.stats.ignored += 1;
      return { ok: false, reason: 'not speaking' };
    }
    this.lastMouthMs = nowMs;
    const target = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };
    if (message.viseme !== undefined) {
      const shape = VISEME_SHAPES[message.viseme];
      if (shape) target[shape] = 0.85;
    } else {
      target.aa = clamp(Math.pow(clamp(message.rms * 3, 0, 1), 0.6) * 0.9, 0, 1);
    }
    this.mouthTarget = target;
    return { ok: true };
  }

  onExpression(message, nowMs) {
    if (this.state === 'approval') {
      this.stats.ignored += 1;
      return { ok: false, reason: 'the face stays neutral during an approval' };
    }
    if (this.state === 'error') {
      this.stats.ignored += 1;
      return { ok: false, reason: 'the face stays sad on an error' };
    }
    const positive = POSITIVE.includes(message.name);
    if (positive && message.cause === 'error') {
      this.stats.rejected += 1;
      return { ok: false, reason: 'an error cannot carry a positive face' };
    }
    if (message.cause === 'verified_outcome') {
      this.heldExpression = message.name;
      this.heldUntilMs = nowMs + VERIFIED_FACE_HOLD_MS;
    } else {
      this.baseExpression = message.name;
    }
    return { ok: true };
  }

  onSettings(message) {
    this.enabled = message.enabled;
    if (message.reduced_motion !== undefined) this.reducedMotion = message.reduced_motion;
    if (message.quality !== undefined) this.quality = message.quality;
    if (!message.enabled) this.closeMouthNow();
    return { ok: true };
  }

  stale() {
    this.stats.droppedStale += 1;
    return { ok: false, reason: 'stale' };
  }

  closeMouthNow() {
    for (const key of Object.keys(this.mouth)) {
      this.mouth[key] = 0;
      this.mouthTarget[key] = 0;
    }
  }

  // --------------------------------------------------------------------- frame

  /** The face that should be showing right now. */
  activeExpression(nowMs) {
    if (this.state === 'approval') return 'neutral';
    if (this.state === 'error') return 'sad';
    if (this.heldExpression !== null) {
      if (nowMs < this.heldUntilMs) return this.heldExpression;
      this.heldExpression = null; // the result face fades back to the resting one
    }
    return this.baseExpression;
  }

  nextBlinkIn() {
    const listening = this.state === 'listening';
    const [lo, hi] = listening ? [1.5, 4] : [2.5, 6];
    return lo + this.random() * (hi - lo);
  }

  /** Advance by dt seconds at absolute time nowMs; returns the values to draw. */
  update(dt, nowMs) {
    this.clock = nowMs;
    const step = clamp(dt, 0, 0.1);

    // Mouth: only while speaking, closes if the host goes quiet.
    if (this.state !== 'speaking' || nowMs - this.lastMouthMs > MOUTH_TIMEOUT_MS) {
      for (const key of Object.keys(this.mouthTarget)) this.mouthTarget[key] = 0;
    }
    for (const key of Object.keys(this.mouth)) {
      const goal = this.mouthTarget[key];
      const tau = goal > this.mouth[key] ? MOUTH_ATTACK : MOUTH_RELEASE;
      this.mouth[key] += (goal - this.mouth[key]) * (1 - Math.exp(-step / tau));
      if (this.mouth[key] < 0.001) this.mouth[key] = 0;
    }

    // Expressions blend over ~200 ms; reduced motion switches at once.
    const active = this.activeExpression(nowMs);
    for (const name of Object.keys(this.weights)) {
      const goal = name === active ? 1 : 0;
      if (this.reducedMotion) {
        this.weights[name] = goal;
      } else {
        const delta = step / EXPRESSION_BLEND_SECONDS;
        this.weights[name] += clamp(goal - this.weights[name], -delta, delta);
      }
    }

    // Blinks.
    this.blinkTimer -= step;
    if (this.blinkProgress < 0 && this.blinkTimer <= 0) this.blinkProgress = 0;
    let blink = 0;
    if (this.blinkProgress >= 0) {
      this.blinkProgress += step / BLINK_SECONDS;
      blink = this.blinkProgress < 1 ? Math.sin(this.blinkProgress * Math.PI) : 0;
      if (this.blinkProgress >= 1) {
        this.blinkProgress = -1;
        this.blinkTimer = this.nextBlinkIn();
      }
    }

    // Pose: move toward the state's pose; idle sway and breathing are off in reduced motion.
    const goal = POSES[this.state];
    const k = this.reducedMotion ? 1 : 1 - Math.exp(-step / POSE_TAU);
    for (const key of Object.keys(goal)) this.pose[key] += (goal[key] - this.pose[key]) * k;
    const t = nowMs / 1000;
    const motion = this.reducedMotion ? 0 : 1;
    const speakingNod = this.state === 'speaking' ? (this.mouth.aa + this.mouth.oh + this.mouth.ou) * 0.04 : 0;
    const frame = {
      state: this.state,
      enabled: this.enabled,
      expression: { ...this.weights },
      blink,
      mouth: { ...this.mouth },
      head: {
        x: this.pose.headPitch + speakingNod * motion,
        y: this.pose.headYaw + Math.sin(t * 0.5) * this.pose.sway * 0.6 * motion,
        z: this.pose.headRoll + Math.sin(t * 0.37) * this.pose.sway * 0.4 * motion,
      },
      spine: { x: this.pose.spineLean + Math.sin(t * 1.3) * this.pose.breath * motion, y: 0, z: Math.sin(t * 0.5) * this.pose.sway * 0.5 * motion },
      chest: { x: Math.sin(t * 1.3) * this.pose.breath * motion, y: 0, z: 0 },
      lookUp: this.pose.lookUp,
    };
    return frame;
  }
}
