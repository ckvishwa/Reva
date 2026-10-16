// Page entry. Host -> page: messages only (WebView2 PostWebMessageAsJson, or window.revaAvatar.handle
// from Android). Page -> host: avatar.ready and avatar.error, nothing else. No network: every file
// is local and the page's CSP forbids connecting anywhere else.

import * as THREE from 'three';
import { AvatarController } from './controller.js';
import { advanceSchedule, paused, pixelRatioFor, QUALITY, shouldRender } from './scheduler.js';
import { loadVrm, VrmRig } from './vrmRig.js';

const params = new URLSearchParams(location.search);
const debug = params.get('debug') === '1';
const modelName = /^[a-z0-9._-]+\.vrm$/i.test(params.get('model') ?? '') ? params.get('model') : 'placeholder.vrm';

const toHost = (message) => {
  try {
    if (window.chrome?.webview) window.chrome.webview.postMessage(message);
    else if (window.RevaAvatarHost?.postMessage) window.RevaAvatarHost.postMessage(JSON.stringify(message));
    else if (window.__revaHostOutbox) window.__revaHostOutbox.push(message); // tests
  } catch {
    // the host went away; nothing to tell
  }
};

const controller = new AvatarController({
  reducedMotion: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false,
});

function receive(message) {
  const result = controller.handle(message, performance.now());
  if (debug) window.__revaAvatarDebug.last = result;
  if (result.ok && message.type === 'avatar.settings') applyQuality();
  return result;
}

window.revaAvatar = { handle: receive };
if (window.chrome?.webview) window.chrome.webview.addEventListener('message', (event) => receive(event.data));

const canvas = document.getElementById('stage');
const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: QUALITY.medium.antialias, powerPreference: 'low-power' });
renderer.setClearColor(0x000000, 0);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(22, 1, 0.1, 20);
camera.position.set(0, 1.38, 1.9);
camera.lookAt(0, 1.3, 0);
scene.add(new THREE.AmbientLight(0xffffff, 1.2));
const key = new THREE.DirectionalLight(0xffffff, 2.0);
key.position.set(0.8, 1.6, 1.6);
scene.add(key);

function applyQuality() {
  renderer.setPixelRatio(pixelRatioFor(controller.quality, window.devicePixelRatio));
  resize();
}

function resize() {
  const width = Math.max(1, canvas.clientWidth);
  const height = Math.max(1, canvas.clientHeight);
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);
// A WebView can be laid out after the page loads (Android); watch the canvas itself, not only the window.
if (typeof ResizeObserver !== 'undefined') new ResizeObserver(resize).observe(canvas);

let rig = null;
let last = performance.now();
let lastRender = 0;
let frames = 0;
if (debug) window.__revaAvatarDebug = { controller, frames: 0, renders: 0, last: null };

function tick(now) {
  requestAnimationFrame(tick);
  if (!rig || paused({ hidden: document.hidden, enabled: controller.enabled })) {
    last = now;
    return;
  }
  if (!shouldRender(now, lastRender, controller.quality)) return;
  const dt = (now - last) / 1000;
  last = now;
  lastRender = advanceSchedule(now, lastRender, controller.quality);
  const frame = controller.update(dt, now);
  rig.apply(frame, Math.min(dt, 0.1));
  renderer.render(scene, camera);
  frames += 1;
  if (debug) {
    window.__revaAvatarDebug.renders = frames;
    window.__revaAvatarDebug.frame = frame;
  }
}

async function start() {
  applyQuality();
  try {
    const vrm = await loadVrm(`./${modelName}`);
    scene.add(vrm.scene);
    rig = new VrmRig(vrm);
    if (debug) window.__revaAvatarDebug.rig = rig;
    requestAnimationFrame(tick);
    toHost({ type: 'avatar.ready' });
  } catch (error) {
    // A short, fixed-shape message: no paths, no stack.
    toHost({ type: 'avatar.error', detail: String(error?.message ?? 'load failed').slice(0, 200) });
  }
}

start();
