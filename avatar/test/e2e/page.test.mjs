import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import {
  SLOW_RUNNER_MS,
  debugFrame,
  dist,
  launch,
  openAvatar,
  renders,
  send,
  startServer,
} from './helpers.mjs';

const built = existsSync(`${dist}/placeholder.vrm`);
const skip = built ? false : 'avatar/dist has no model: run "npm run build" with Git LFS files pulled';

let server;
let browser;
before(async () => {
  if (!built) return;
  server = await startServer();
  browser = await launch();
});
after(async () => {
  await browser?.close();
  await server?.close();
});

test('the page loads offline from local files only and reports ready', { skip }, async () => {
  const blocked = [];
  const context = await browser.newContext();
  const page = await context.newPage();
  page.setDefaultTimeout(SLOW_RUNNER_MS);
  page.setDefaultNavigationTimeout(SLOW_RUNNER_MS);
  await page.route('**/*', (route) => {
    const url = route.request().url();
    if (url.startsWith(server.origin)) return route.continue();
    blocked.push(url);
    return route.abort();
  });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.addInitScript(() => {
    window.__revaHostOutbox = [];
  });
  await page.goto(`${server.origin}/index.html?debug=1`);
  await page.waitForFunction(() => window.__revaHostOutbox.length > 0, null, { timeout: SLOW_RUNNER_MS });

  assert.deepEqual(await page.evaluate(() => window.__revaHostOutbox), [{ type: 'avatar.ready' }]);
  assert.deepEqual(blocked, [], 'the page tried to reach outside the local files');
  assert.deepEqual(errors, []);
  await context.close();
});

test('the page only ever tells the host ready or error', { skip }, async () => {
  const { page, outbox } = await openAvatar(browser, server.origin);
  await send(page, { type: 'avatar.state', state: 'speaking', turn_epoch: 1 });
  await send(page, { type: 'avatar.mouth', t_ms: 0, rms: 0.5, turn_epoch: 1 });
  await page.waitForTimeout(300);

  const all = await page.evaluate(() => window.__revaHostOutbox);
  assert.ok(all.every((m) => m.type === 'avatar.ready' || m.type === 'avatar.error'));
  assert.equal(outbox[0].type, 'avatar.ready');
  await page.close();
});

test('the CSP stops the page loading or calling anything outside', { skip }, async () => {
  const { page } = await openAvatar(browser, server.origin);
  const result = await page.evaluate(async () => {
    const violations = [];
    document.addEventListener('securitypolicyviolation', (e) => violations.push(e.violatedDirective));
    let fetched = 'allowed';
    try {
      await fetch('https://example.com/');
    } catch {
      fetched = 'blocked';
    }
    const img = new Image();
    img.src = 'https://example.com/x.png';
    const script = document.createElement('script');
    script.src = 'https://example.com/x.js';
    document.head.appendChild(script);
    let inline = 'allowed';
    try {
      // eslint-disable-next-line no-new-func
      new Function('return 1')();
    } catch {
      inline = 'blocked';
    }
    await new Promise((r) => setTimeout(r, 300));
    return { fetched, violations, inline };
  });

  assert.equal(result.fetched, 'blocked');
  assert.ok(result.violations.some((v) => v.startsWith('connect-src')), JSON.stringify(result));
  assert.ok(result.violations.some((v) => v.startsWith('img-src')), JSON.stringify(result));
  assert.ok(result.violations.some((v) => v.startsWith('script-src')), JSON.stringify(result));
  await page.close();
});

test('the model name can only be a plain local .vrm file name', { skip }, async () => {
  for (const query of ['?debug=1&model=../secret.vrm', '?debug=1&model=http://example.com/x.vrm', '?debug=1&model=a/b.vrm']) {
    const before = server.requests.length;
    const { page, outbox } = await openAvatar(browser, server.origin, { query });
    const asked = server.requests.slice(before);

    assert.equal(outbox[0].type, 'avatar.ready', query);
    assert.ok(asked.includes('/placeholder.vrm'), `${query}: ${asked.join(',')}`);
    assert.ok(!asked.some((p) => p.includes('secret') || p.includes('example.com')), query);
    await page.close();
  }
});

test('the avatar mirrors states, drops stale epochs and moves the mouth only while speaking', { skip }, async () => {
  const { page } = await openAvatar(browser, server.origin);

  const until = (state) => page.waitForFunction((s) => window.__revaAvatarDebug.frame?.state === s, state, { timeout: SLOW_RUNNER_MS });
  await send(page, { type: 'avatar.state', state: 'listening', turn_epoch: 3 });
  const refused = await send(page, { type: 'avatar.mouth', t_ms: 0, rms: 1, turn_epoch: 3 });
  await until('listening');
  const listening = await debugFrame(page);
  assert.equal(refused.ok, false);
  assert.equal(listening.mouth.aa, 0);

  await send(page, { type: 'avatar.state', state: 'speaking', turn_epoch: 3 });
  await until('speaking');
  const end = Date.now() + SLOW_RUNNER_MS; // ends as soon as the mouth opens; only a failure waits
  let opened = 0;
  while (Date.now() < end && opened <= 0.3) {
    await send(page, { type: 'avatar.mouth', t_ms: 0, rms: 0.8, turn_epoch: 3 });
    await page.waitForTimeout(30);
    opened = (await debugFrame(page)).mouth.aa;
  }
  assert.ok(opened > 0.3, `mouth only reached ${opened}`);

  const stale = await send(page, { type: 'avatar.state', state: 'idle', turn_epoch: 2 });
  assert.equal(stale.reason, 'stale');
  assert.equal((await debugFrame(page)).state, 'speaking');

  await send(page, { type: 'avatar.state', state: 'listening', turn_epoch: 4 }); // interrupt
  await until('listening');
  assert.equal((await debugFrame(page)).mouth.aa, 0);
  await page.close();
});

test('hostile or malformed messages never throw and change nothing', { skip }, async () => {
  const { page, pageErrors } = await openAvatar(browser, server.origin);
  const results = await page.evaluate(() => [
    null,
    undefined,
    42,
    'x',
    [],
    {},
    { type: 'avatar.state', state: { toString: () => 'idle' }, turn_epoch: 0 },
    { type: '__proto__' },
    { type: 'avatar.expression', name: 'happy', cause: 'mood', __proto__: { polluted: true } },
  ].map((m) => {
    try {
      return window.revaAvatar.handle(m).ok;
    } catch (error) {
      return `threw: ${error.message}`;
    }
  }));

  assert.ok(results.slice(0, 8).every((r) => r === false), JSON.stringify(results));
  assert.equal(await page.evaluate(() => ({}).polluted), undefined);
  assert.deepEqual(pageErrors, []);
  await page.close();
});

test('drawing is capped at 60 fps, stops when the avatar is off and resumes when it is on', { skip }, async () => {
  const { page } = await openAvatar(browser, server.origin);
  await page.waitForTimeout(500);

  const start = await renders(page);
  await page.waitForTimeout(2000);
  const drawn = (await renders(page)) - start;
  assert.ok(drawn <= 2 * 60 + 4, `drew ${drawn} frames in 2 s`);
  // Software WebGL on a shared runner can draw fewer than two frames in two seconds, so "it is
  // drawing" waits for frames to arrive instead of counting them in a fixed window.
  await page.waitForFunction((from) => window.__revaAvatarDebug.renders >= from + 2, start, {
    timeout: SLOW_RUNNER_MS,
  });

  await send(page, { type: 'avatar.settings', enabled: false });
  await page.waitForTimeout(300);
  const frozen = await renders(page);
  await page.waitForTimeout(700);
  assert.equal(await renders(page), frozen, 'frames were drawn while the avatar was off');

  await send(page, { type: 'avatar.settings', enabled: true });
  await page.waitForFunction((from) => window.__revaAvatarDebug.renders > from, frozen, {
    timeout: SLOW_RUNNER_MS,
  }); // fails with a timeout if drawing never resumes
  await page.close();
});

test('low quality draws at 30 fps at most', { skip }, async () => {
  const { page } = await openAvatar(browser, server.origin);
  await send(page, { type: 'avatar.settings', enabled: true, quality: 'low' });
  await page.waitForTimeout(500);

  const start = await renders(page);
  await page.waitForTimeout(2000);

  assert.ok((await renders(page)) - start <= 2 * 30 + 4);
  await page.close();
});

test('the model has every face and mouth shape the persona needs', { skip }, async () => {
  const { page } = await openAvatar(browser, server.origin);
  const missing = await page.evaluate(() => {
    const manager = window.__revaAvatarDebug.rig.vrm.expressionManager;
    return ['neutral', 'happy', 'sad', 'relaxed', 'surprised', 'blink', 'aa', 'ih', 'ou', 'ee', 'oh'].filter(
      (name) => !manager.getExpression(name),
    );
  });

  assert.deepEqual(missing, []);
  await page.close();
});
