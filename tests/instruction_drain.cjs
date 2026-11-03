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
const bootstrap = new AsyncFunction('root', 'paths', 'external', 'tools', 'notify', 'text', source);
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
  const messages = [], receipts = [], commands = [];
  let readers = 0, damaged = false;
  const tools = {exec_command: async ({cmd}) => {
    commands.push(cmd);
    const helper = cmd.includes('--helper');
    if (!helper) readers++;
    if (mode === 'cancel' && readers === 2 && !helper) throw Error('cancelled');
    if (mode === 'pending' && readers === 2 && !helper) return {session_id: 42, output: 'still running'};
    const child = spawnSync('/bin/sh', ['-c', cmd], {cwd: directory, encoding: 'utf8', timeout: 10000});
    if (child.error) throw child.error;
    const result = {exit_code: child.status, output: child.stdout + child.stderr};
    if (helper && mode === 'helper') result.output = result.output.slice(0, 90);
    if (result.exit_code === 0 && !helper) {
      const packet = JSON.parse(result.output);
      if (mode === 'empty') {
        packet.text = ''; packet.characters = 0;
        result.output = JSON.stringify(packet);
      }
      if ((mode === 'clip-first' && readers === 1) ||
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
    messages.push(value);
    if (messages.length === 1 && mode === 'stale') fs.appendFileSync(input, 'Changed source.\n');
    if (messages.length === 1 && mode === 'target') {
      fs.unlinkSync(alias); fs.symlinkSync(other, alias);
    }
    if (mode === 'emit-error') throw Error('notification failed');
  };
  let failure;
  try { await bootstrap(root, [selected], true, tools, notify, value => receipts.push(value)); }
  catch (error) { failure = error; }
  assert(!fs.existsSync(path.join(directory, 'INJECTION')), 'Instruction paths must remain shell data');
  const failed = ['stale', 'target', 'cancel', 'pending', 'metadata', 'revision', 'helper', 'always-clip', 'emit-error', 'empty'].includes(mode);
  if (failed) {
    assert(failure, mode + ' must fail');
    assert.equal(receipts.length, 0, mode + ' must not report completion');
    if (mode === 'always-clip') assert.equal(readers, 2, 'One bounded small-page fallback, not a retry loop');
  } else {
    assert.ifError(failure);
    assert.equal(receipts.length, 1);
    assert.equal(receipts[0].complete, true);
    verifyCoverage(messages, selected, original);
    assert.equal(commands.filter(c => c.includes('--helper')).length, mode === 'small' ? 0 : 1);
    if (mode === 'small') assert.equal(readers, 1);
    if (mode.startsWith('clip-')) {
      assert(damaged);
      assert(commands.some(c => !c.includes('--helper') && !c.includes('--batch')), 'Recover using bounded single pages');
    }
  }
}

(async () => {
  try {
    for (const mode of ['small', 'large', 'clip-first', 'clip-later', 'always-clip', 'stale', 'target',
                        'cancel', 'pending', 'metadata', 'revision', 'helper', 'emit-error', 'empty']) {
      await run(mode, ['small', 'empty'].includes(mode) ? '# Small\r\nPreserve 😀 and every rule.\r\n' : large);
    }
    console.log('14 native drain cases passed');
  } finally { fs.rmSync(directory, {recursive: true, force: true}); }
})().catch(error => { console.error(error); process.exitCode = 1; });
