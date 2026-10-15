// Bundles the page into avatar/dist/: avatar.js (three.js and three-vrm inside, no CDN), index.html and
// the model. The model comes from assets/avatar/ (Git LFS). A Git LFS pointer is not a model, so the
// build fails unless --allow-missing-model is given (unit tests and CI jobs without LFS).

import { build } from 'esbuild';
import { copyFile, mkdir, readFile, rm, stat } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const dist = join(root, 'dist');
const allowMissing = process.argv.includes('--allow-missing-model');
const models = ['placeholder.vrm', 'reva-1.0.vrm'];

await rm(dist, { recursive: true, force: true });
await mkdir(dist, { recursive: true });

await build({
  entryPoints: [join(root, 'src', 'main.js')],
  outfile: join(dist, 'avatar.js'),
  bundle: true,
  format: 'iife',
  target: 'es2020',
  minify: true,
  legalComments: 'none',
  logLevel: 'warning',
});
await copyFile(join(root, 'src', 'index.html'), join(dist, 'index.html'));

for (const name of models) {
  const source = join(root, '..', 'assets', 'avatar', name);
  try {
    const info = await stat(source);
    const head = (await readFile(source, { encoding: 'latin1' })).slice(0, 40);
    if (info.size < 1000 || head.startsWith('version https://git-lfs')) throw new Error('Git LFS pointer');
    await copyFile(source, join(dist, name));
    console.log(`model ${name}: ${(info.size / 1e6).toFixed(1)} MB`);
  } catch (error) {
    if (name === 'placeholder.vrm' && !allowMissing) {
      console.error(`assets/avatar/${name} is missing or is a Git LFS pointer (${error.message}). Run "git lfs pull".`);
      process.exit(1);
    }
  }
}
console.log('built avatar/dist');
