// Shared by the browser tests and scripts/poses.mjs: a tiny static server for dist/ and an Edge launch.
// Edge ships with Windows (and the windows-latest CI image), so no browser download is needed.

import { chromium } from 'playwright-core';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { dirname, extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

export const dist = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'dist');
const types = { '.html': 'text/html', '.js': 'text/javascript', '.vrm': 'model/gltf-binary' };

export async function startServer() {
  const requests = [];
  const server = createServer(async (req, res) => {
    const pathname = decodeURIComponent(req.url.split('?')[0]);
    requests.push(pathname);
    const file = normalize(join(dist, pathname === '/' ? 'index.html' : pathname));
    if (!file.startsWith(dist)) {
      res.writeHead(403);
      res.end();
      return;
    }
    try {
      const body = await readFile(file);
      res.writeHead(200, { 'content-type': types[extname(file)] ?? 'application/octet-stream' });
      res.end(body);
    } catch {
      res.writeHead(404);
      res.end();
    }
  }).listen(0, '127.0.0.1');
  await new Promise((resolve) => server.once('listening', resolve));
  const port = server.address().port;
  return { origin: `http://127.0.0.1:${port}`, port, requests, close: () => new Promise((resolve) => server.close(resolve)) };
}

// Software-rendered WebGL on a shared CI runner can be many times slower than on a desk: the first
// full-page load took over 30 s there (Playwright's default navigation limit). A wait that gives up
// early reports a slow machine as a broken avatar, so every wait here has the same generous bound.
export const SLOW_RUNNER_MS = 120000;

export async function launch() {
  return chromium.launch({
    channel: 'msedge',
    headless: true,
    args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
  });
}

/** Opens the page with the host-outbox shim and waits for avatar.ready (or avatar.error). */
export async function openAvatar(browser, origin, { query = '?debug=1', viewport = { width: 480, height: 640 } } = {}) {
  const page = await browser.newPage({ viewport });
  page.setDefaultTimeout(SLOW_RUNNER_MS);
  page.setDefaultNavigationTimeout(SLOW_RUNNER_MS);
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.addInitScript(() => {
    window.__revaHostOutbox = [];
  });
  await page.goto(`${origin}/index.html${query}`);
  await page.waitForFunction(() => window.__revaHostOutbox.length > 0, null, { timeout: SLOW_RUNNER_MS });
  const outbox = await page.evaluate(() => window.__revaHostOutbox);
  return { page, outbox, pageErrors };
}

export const send = (page, message) => page.evaluate((m) => window.revaAvatar.handle(m), message);
export const debugFrame = (page) => page.evaluate(() => window.__revaAvatarDebug.frame);
export const renders = (page) => page.evaluate(() => window.__revaAvatarDebug.renders);
