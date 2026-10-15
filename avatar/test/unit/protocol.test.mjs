import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import Ajv from 'ajv/dist/2020.js';
import { validate } from '../../src/protocol.js';

const schemaPath = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', 'contracts', 'avatar-events.schema.json');
const schema = JSON.parse(readFileSync(schemaPath, 'utf8'));
const ajv = new Ajv({ strict: false });
const check = ajv.compile(schema);

const valid = [
  { type: 'avatar.state', state: 'idle', turn_epoch: 0 },
  { type: 'avatar.state', state: 'approval', turn_epoch: 7 },
  { type: 'avatar.mouth', t_ms: 0, rms: 0, turn_epoch: 1 },
  { type: 'avatar.mouth', t_ms: 120, rms: 0.6, turn_epoch: 1 },
  { type: 'avatar.mouth', t_ms: 120, viseme: 'oh', turn_epoch: 1 },
  { type: 'avatar.mouth', t_ms: 120, rms: 0.2, viseme: 'sil', turn_epoch: 1 },
  { type: 'avatar.expression', name: 'relaxed', cause: 'mood' },
  { type: 'avatar.expression', name: 'happy', cause: 'verified_outcome', action_id: 'act-12345678' },
  { type: 'avatar.expression', name: 'sad', cause: 'error' },
  { type: 'avatar.expression', name: 'neutral', cause: 'greeting' },
  { type: 'avatar.expression', name: 'neutral', cause: 'idle_variation' },
  { type: 'avatar.settings', enabled: true },
  { type: 'avatar.settings', enabled: false, reduced_motion: true, quality: 'low' },
];

const invalid = [
  null,
  [],
  'text',
  {},
  { type: 'avatar.unknown' },
  { type: 'avatar.state', state: 'dancing', turn_epoch: 0 },
  { type: 'avatar.state', state: 'idle' },
  { type: 'avatar.state', state: 'idle', turn_epoch: -1 },
  { type: 'avatar.state', state: 'idle', turn_epoch: 1.5 },
  { type: 'avatar.state', state: 'idle', turn_epoch: 0, extra: 1 },
  { type: 'avatar.mouth', t_ms: 0, turn_epoch: 0 },
  { type: 'avatar.mouth', t_ms: 0, rms: 1.2, turn_epoch: 0 },
  { type: 'avatar.mouth', t_ms: 0, rms: -0.1, turn_epoch: 0 },
  { type: 'avatar.mouth', t_ms: 0, viseme: 'zz', turn_epoch: 0 },
  { type: 'avatar.mouth', t_ms: -5, rms: 0.5, turn_epoch: 0 },
  { type: 'avatar.expression', name: 'angry', cause: 'mood' },
  { type: 'avatar.expression', name: 'happy', cause: 'flattery' },
  { type: 'avatar.expression', name: 'happy', cause: 'verified_outcome' },
  { type: 'avatar.expression', name: 'happy', cause: 'verified_outcome', action_id: 'short' },
  { type: 'avatar.settings' },
  { type: 'avatar.settings', enabled: 'yes' },
  { type: 'avatar.settings', enabled: true, quality: 'ultra' },
  { type: 'avatar.settings', enabled: true, reduced_motion: 1 },
];

test('every valid message passes the page validator and the JSON Schema', () => {
  for (const message of valid) {
    assert.equal(validate(message), null, JSON.stringify(message));
    assert.equal(check(message), true, JSON.stringify(message));
  }
});

test('every invalid message is refused by the page validator and by the JSON Schema', () => {
  for (const message of invalid) {
    assert.notEqual(validate(message), null, JSON.stringify(message));
    assert.equal(check(message), false, JSON.stringify(message));
  }
});

test('the schema is 2.1 and accepts the mood cause', () => {
  assert.match(schema.$id, /avatar-events\/2\.1$/);
  assert.equal(validate({ type: 'avatar.expression', name: 'relaxed', cause: 'mood' }), null);
});

test('avatar.ready and avatar.error are page-to-host only: the page refuses them from the host', () => {
  assert.notEqual(validate({ type: 'avatar.ready' }), null);
  assert.notEqual(validate({ type: 'avatar.error', detail: 'x' }), null);
});
