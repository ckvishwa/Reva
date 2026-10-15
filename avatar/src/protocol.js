// Host -> page messages (contracts/avatar-events.schema.json, version 2.1).
//
// The page accepts nothing else. Every message is checked here before it reaches the controller, so
// a malformed or hostile message from the host can never drive the avatar into a state it should not
// be in. test/unit/protocol.test.mjs checks this validator against the JSON Schema itself.

export const STATES = ['idle', 'listening', 'thinking', 'speaking', 'approval', 'error'];
export const EXPRESSIONS = ['neutral', 'happy', 'sad', 'relaxed', 'surprised'];
export const CAUSES = ['verified_outcome', 'greeting', 'error', 'idle_variation', 'mood'];
export const VISEMES = ['sil', 'aa', 'ih', 'ou', 'ee', 'oh'];
export const QUALITIES = ['low', 'medium', 'high'];

const isInt = (v) => Number.isInteger(v) && v >= 0;
const isString = (v, min, max) => typeof v === 'string' && v.length >= min && v.length <= max;

function onlyKeys(message, allowed) {
  return Object.keys(message).every((key) => allowed.includes(key));
}

/** Returns null when the message is valid, otherwise a short fixed reason. */
export function validate(message) {
  if (message === null || typeof message !== 'object' || Array.isArray(message)) return 'not an object';
  switch (message.type) {
    case 'avatar.state':
      if (!onlyKeys(message, ['type', 'state', 'turn_epoch'])) return 'unknown field';
      if (!STATES.includes(message.state)) return 'bad state';
      if (!isInt(message.turn_epoch)) return 'bad turn_epoch';
      return null;
    case 'avatar.mouth':
      if (!onlyKeys(message, ['type', 't_ms', 'rms', 'viseme', 'turn_epoch'])) return 'unknown field';
      if (!isInt(message.t_ms) || !isInt(message.turn_epoch)) return 'bad time or turn_epoch';
      if (message.rms === undefined && message.viseme === undefined) return 'needs rms or viseme';
      if (message.rms !== undefined && !(typeof message.rms === 'number' && message.rms >= 0 && message.rms <= 1)) {
        return 'bad rms';
      }
      if (message.viseme !== undefined && !VISEMES.includes(message.viseme)) return 'bad viseme';
      return null;
    case 'avatar.expression':
      if (!onlyKeys(message, ['type', 'name', 'cause', 'action_id'])) return 'unknown field';
      if (!EXPRESSIONS.includes(message.name)) return 'bad expression';
      if (!CAUSES.includes(message.cause)) return 'bad cause';
      if (message.action_id !== undefined && !isString(message.action_id, 8, 64)) return 'bad action_id';
      if (message.cause === 'verified_outcome' && message.action_id === undefined) {
        return 'verified_outcome needs action_id';
      }
      return null;
    case 'avatar.settings':
      if (!onlyKeys(message, ['type', 'enabled', 'reduced_motion', 'quality'])) return 'unknown field';
      if (typeof message.enabled !== 'boolean') return 'bad enabled';
      if (message.reduced_motion !== undefined && typeof message.reduced_motion !== 'boolean') {
        return 'bad reduced_motion';
      }
      if (message.quality !== undefined && !QUALITIES.includes(message.quality)) return 'bad quality';
      return null;
    default:
      return 'unknown type';
  }
}
