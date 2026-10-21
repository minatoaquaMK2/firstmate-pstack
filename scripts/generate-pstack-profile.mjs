#!/usr/bin/env node
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { createHash } from 'node:crypto';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const directory = path.join(root, 'adapters/pstack-codex');
const lock = JSON.parse(await readFile(path.join(directory, 'pstack.lock.json'), 'utf8'));
const check = process.argv.includes('--check');
for (const [name, expected] of Object.entries(lock.files)) {
  const target = path.join(directory, name);
  if (!check && name.startsWith('upstream/')) {
    const source = name.slice('upstream/'.length);
    const response = await fetch(`https://raw.githubusercontent.com/cursor/plugins/${lock.commit}/${source}`);
    if (!response.ok) throw new Error(`Cannot fetch ${source}: ${response.status}`);
    const data = Buffer.from(await response.arrayBuffer());
    if (createHash('sha256').update(data).digest('hex') !== expected) throw new Error(`Upstream hash mismatch: ${source}`);
    await mkdir(path.dirname(target), { recursive: true });
    await writeFile(target, data);
  }
  const actual = createHash('sha256').update(await readFile(target)).digest('hex');
  if (actual !== expected) throw new Error(`Profile differs from lock: ${name}`);
}
console.log(`pstack ${lock.version} profile verified at ${lock.commit}`);
