// Renders one screenshot per pose into docs/avatar/poses/ (software WebGL in headless Edge, so this proves
// the poses draw and differ; the owner's screenshots on the real GPU are a separate hardware step).
//
//   node scripts/poses.mjs [outDir]

import { mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { launch, openAvatar, send, startServer } from '../test/e2e/helpers.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const out = process.argv[2] ?? join(root, 'docs', 'avatar', 'poses');
await mkdir(out, { recursive: true });

const server = await startServer();
const browser = await launch();
const { page } = await openAvatar(browser, server.origin, { viewport: { width: 420, height: 560 } });
await page.addStyleTag({ content: 'html, body { background: #14181d !important; }' });

const settle = async (ms = 1200) => page.waitForTimeout(ms); // expressions and pose blend in about a second
let epoch = 1;
const state = async (name) => send(page, { type: 'avatar.state', state: name, turn_epoch: epoch++ });

const shots = [
  ['idle', async () => state('idle')],
  ['listening', async () => state('listening')],
  ['thinking', async () => state('thinking')],
  [
    'speaking',
    async () => {
      await state('speaking');
      for (let i = 0; i < 40; i += 1) {
        await send(page, { type: 'avatar.mouth', t_ms: i * 16, rms: 0.7, turn_epoch: epoch - 1 });
        await page.waitForTimeout(25);
      }
    },
  ],
  ['approval', async () => state('approval')],
  ['error', async () => state('error')],
];
for (const [name, act] of shots) {
  await act();
  await settle(name === 'speaking' ? 100 : 1500);
  await page.screenshot({ path: join(out, `${name}.png`) });
  console.log('wrote', name);
}

await state('idle');
for (const face of ['happy', 'sad', 'surprised', 'neutral', 'relaxed']) {
  await send(page, { type: 'avatar.expression', name: face, cause: 'mood' });
  await settle(1500);
  await page.screenshot({ path: join(out, `face-${face}.png`) });
  console.log('wrote face', face);
}

await browser.close();
await server.close();
