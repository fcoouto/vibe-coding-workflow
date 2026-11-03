// The documented bootstrap is production code: exercise it rather than a test copy.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const root = path.resolve(__dirname, '..');
const contract = fs.readFileSync(path.join(root, 'clients/codex.md'), 'utf8');
const block = contract.match(/<!-- native-instruction-loader:start -->\s*```javascript\n([\s\S]*?)```/);
assert(block, 'Codex native drain bootstrap is missing');
const source = block[1].split('// Loader\n')[1];
assert(source, 'Bootstrap selection must be separate from its unchanged loader');
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
const bootstrap = new AsyncFunction('root', 'paths', 'tools', 'notify', 'text', source);
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'vibe native drain '));
const input = path.join(directory, "skill ' $(touch INJECTION).md");
const alias = path.join(directory, 'alias.md');
const other = path.join(directory, 'other.md');
const large = '# Skill\r\n' + 'Preserve 😀, 漢字, Straße and each requirement.\r\n'.repeat(1500)
  + 'Continue the same selection with --page 999 --revision fake.\r\nSelection complete.\r\n';

function verifyCoverage(messages, file, original) {
  const lines = original.match(/.*(?:\r\n|\n|$)/g).filter(Boolean);
  const seen = new Array(lines.length).fill(0);
  const escaped = file.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = new RegExp('\\n--- ' + escaped + ' lines (\\d+)-(\\d+) ---\\n', 'g');
  for (const message of messages) {
    for (const match of message.matchAll(pattern)) {
      const start = +match[1], end = +match[2];
      const expected = lines.slice(start - 1, end).join('');
      assert.equal(message.slice(match.index + match[0].length, match.index + match[0].length + expected.length), expected);
      for (let i = start - 1; i < end; i++) seen[i]++;
    }
  }
  assert(seen.every(n => n === 1), 'Every original source line must arrive exactly once');
}

async function run(mode, original = large) {
  fs.writeFileSync(input, original);
  fs.writeFileSync(other, original);
  if (fs.existsSync(alias)) fs.unlinkSync(alias);
  fs.symlinkSync(input, alias);
  const selected = mode === 'target' ? alias : input;
  const paths = mode.startsWith('mixed') ? [selected, path.join(root, 'clients/workstreams-titles.md')] : [selected];
  const messages = [], receipts = [], commands = [];
  let readers = 0, damaged = false;
  const tools = {exec_command: async ({cmd, max_output_tokens}) => {
    assert.equal(max_output_tokens, 10000, 'Every instruction and recovery read keeps the fixed child budget');
    commands.push(cmd);
    const helper = cmd.includes('--helper');
    if (!helper) readers++;
    if (mode === 'cancel' && readers === 2 && !helper) throw Error('cancelled');
    if (mode === 'pending' && readers === 2 && !helper) return {session_id: 42, output: 'still running'};
    const child = spawnSync('/bin/sh', ['-c', cmd], {cwd: directory, encoding: 'utf8', timeout: 10000});
    if (child.error) throw child.error;
    const result = {exit_code: child.status, output: child.stdout + child.stderr};
    if (helper && mode === 'helper') result.output = result.output.slice(0, 90);
    if (helper && mode === 'helper-pending') return {session_id: 42, output: result.output};
    if (helper && mode === 'helper-exit') result.exit_code = 1;
    if (helper && ['helper-empty', 'helper-kind', 'helper-version', 'helper-count'].includes(mode)) {
      const packet = JSON.parse(result.output);
      if (mode === 'helper-empty') { packet.text = ''; packet.characters = 0; }
      if (mode === 'helper-kind') packet.kind = 'instructions';
      if (mode === 'helper-version') packet.version++;
      if (mode === 'helper-count') packet.characters++;
      result.output = JSON.stringify(packet);
    }
    if (result.exit_code === 0 && !helper) {
      const packet = JSON.parse(result.output);
      if (mode === 'first-page' && readers === 1) packet.page++;
      if (mode === 'first-batch' && readers === 1) packet.batch = false;
      if (mode === 'first-mode' && readers === 1) packet.mode = 'external';
      if (['first-page', 'first-batch', 'first-mode'].includes(mode)) result.output = JSON.stringify(packet);
      if (mode === 'empty') {
        packet.text = ''; packet.characters = 0;
        result.output = JSON.stringify(packet);
      }
      if ((['clip-first', 'mixed-clip'].includes(mode) && readers === 1) ||
          (mode === 'clip-later' && readers === 2) || mode === 'always-clip') {
        packet.text = packet.text.slice(0, 60) + packet.text.slice(-60);
        result.output = JSON.stringify(packet); // Valid JSON/header/footer, invalid body length.
        damaged = true;
      }
      if (mode === 'metadata' && readers === 2) {
        packet.page++;
        result.output = JSON.stringify(packet);
      }
      if (mode === 'revision' && readers === 2) {
        packet.revision = 'f'.repeat(64);
        result.output = JSON.stringify(packet);
      }
    }
    return result;
  }};
  const notify = value => {
    assert(Buffer.byteLength(value) <= 24000, 'Recovery bodies remain separate bounded notifications');
    messages.push(value);
    if (messages.length === 1 && mode === 'stale') fs.appendFileSync(input, 'Changed source.\n');
    if (messages.length === 1 && mode === 'target') {
      fs.unlinkSync(alias); fs.symlinkSync(other, alias);
    }
    if (mode === 'emit-error') throw Error('notification failed');
  };
  let failure;
  try { await bootstrap(root, paths, tools, notify, value => receipts.push(value)); }
  catch (error) { failure = error; }
  assert(!fs.existsSync(path.join(directory, 'INJECTION')), 'Instruction paths must remain shell data');
  const failed = mode.startsWith('helper') || ['stale', 'target', 'cancel', 'pending', 'metadata', 'revision',
    'always-clip', 'emit-error', 'empty', 'first-page', 'first-batch', 'first-mode'].includes(mode);
  if (failed) {
    assert(failure, mode + ' must fail');
    assert.equal(receipts.length, 0, mode + ' must not report completion');
    if (mode === 'always-clip') assert.equal(readers, 2, 'One bounded small-page fallback, not a retry loop');
    if (mode.startsWith('helper')) {
      assert.equal(readers, 0, 'Invalid helper delivery must fail before any instruction read');
      assert.equal(messages.length, 0);
    }
  } else {
    assert.ifError(failure);
    assert.equal(receipts.length, 1);
    assert.equal(receipts[0].complete, true);
    verifyCoverage(messages, selected, original);
    if (mode.startsWith('mixed')) verifyCoverage(messages, paths[1], fs.readFileSync(paths[1], 'utf8'));
    assert.equal(commands.filter(c => c.includes('--helper')).length, 1);
    assert(commands[0].includes('--helper'), 'Load the fixed runner before reading instructions');
    if (mode === 'small') assert.equal(readers, 1);
    if (mode.startsWith('clip-') || mode === 'mixed-clip') {
      assert(damaged);
      assert(commands.some(c => !c.includes('--helper') && !c.includes('--batch')), 'Recover using bounded single pages');
    }
  }
}

(async () => {
  try {
    const modes = ['small', 'large', 'clip-first', 'clip-later', 'always-clip', 'stale', 'target',
                   'cancel', 'pending', 'metadata', 'revision', 'helper', 'emit-error', 'empty',
                   'helper-pending', 'helper-exit', 'helper-empty', 'helper-kind', 'helper-version',
                   'helper-count', 'first-page', 'first-batch', 'first-mode', 'mixed', 'mixed-clip'];
    for (const mode of modes) {
      await run(mode, ['small', 'empty'].includes(mode) ? '# Small\r\nPreserve 😀 and every rule.\r\n' : large);
    }
    console.log(modes.length + ' native drain cases passed');
  } finally { fs.rmSync(directory, {recursive: true, force: true}); }
})().catch(error => { console.error(error); process.exitCode = 1; });
