"""Exercise the provisioning helper with a copied script and a synthetic writer."""
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import unittest

HELPER = Path(__file__).resolve().parents[1] / 'scripts' / 'usage_key_setup.mjs'
NODE = shutil.which('node')
SECRET = b'sk-proj-synthetic-fixture'
REFERENCE = 'vcw_' + '1' * 32
ENCRYPT = """
const { constants, createPublicKey, publicEncrypt } = require('node:crypto');
const { readFileSync } = require('node:fs');
const key = createPublicKey({key: JSON.parse(process.argv[1]), format: 'jwk'});
const encrypted = publicEncrypt({key, padding: constants.RSA_PKCS1_OAEP_PADDING, oaepHash: 'sha256'},
                                readFileSync(0));
console.log(JSON.stringify({version: 1, ciphertext: encrypted.toString('base64url')}));
"""


@unittest.skipUnless(NODE, 'Node required')
class UsageKeySetupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / 'scripts').mkdir()
        (root / 'runtime').mkdir()
        self.script = root / 'scripts' / HELPER.name
        self.assertTrue(HELPER.is_file(), 'provisioning helper is missing')
        shutil.copyfile(HELPER, self.script)
        self.writer = root / 'runtime' / 'usage_credentials.py'
        self.marker = root / 'called'
        self.writer.write_text(
            'import json, sys\nfrom pathlib import Path\n'
            'assert sys.argv[1:] == ["org-synthetic", "proj_synthetic"]\n'
            f'assert sys.stdin.buffer.read() == {SECRET!r}\n'
            f'Path({str(self.marker)!r}).touch(exist_ok=False)\n'
            f'print(json.dumps({{"credential_ref": {REFERENCE!r}}}))\n'
        )

    def start(self):
        proc = subprocess.Popen([NODE, str(self.script), 'org-synthetic', 'proj_synthetic', sys.executable],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=dict(os.environ, PATH=''))
        self.addCleanup(self.stop, proc)
        self.assertTrue(select.select([proc.stdout], [], [], 15)[0], 'public JWK timed out')
        public_line = proc.stdout.readline()
        public = json.loads(public_line)
        self.assertEqual(set(public), {'recipient_public_key_jwk'})
        jwk = public['recipient_public_key_jwk']
        self.assertEqual(set(jwk), {'kty', 'n', 'e'})
        self.assertEqual(jwk['kty'], 'RSA')
        self.assertNotIn(SECRET, public_line)
        return proc, jwk

    @staticmethod
    def stop(proc):
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=5)

    def encrypted(self, jwk):
        return subprocess.run([NODE, '-e', ENCRYPT, json.dumps(jwk)], input=SECRET,
                              capture_output=True, check=True, timeout=10).stdout

    def test_ciphertext_reaches_only_fixed_writer_via_stdin(self):
        proc, jwk = self.start()
        out, err = proc.communicate(self.encrypted(jwk), timeout=15)
        self.assertEqual(proc.returncode, 0, err)
        self.assertEqual(json.loads(out), {'credential_ref': REFERENCE})
        self.assertTrue(self.marker.exists())
        self.assertNotIn(SECRET, out + err)

    def test_cancel_or_invalid_payload_does_not_start_writer(self):
        for payload in (b'', b'{"version":2,"ciphertext":"abc"}\n', b'x' * 4097 + b'\n'):
            with self.subTest(payload=payload[:32]):
                proc, _ = self.start()
                out, err = proc.communicate(payload, timeout=15)
                self.assertNotEqual(proc.returncode, 0)
                self.assertEqual(out, b'')
                self.assertNotIn(SECRET, err)
                self.assertFalse(self.marker.exists())

    def test_writer_failure_does_not_forward_writer_output(self):
        self.writer.write_text(
            'import sys\nsecret = sys.stdin.buffer.read()\n'
            'sys.stdout.buffer.write(secret)\nsys.stderr.buffer.write(secret)\nsys.exit(1)\n'
        )
        proc, jwk = self.start()
        out, err = proc.communicate(self.encrypted(jwk), timeout=15)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(out, b'')
        self.assertEqual(err, b'credential_storage_failed\n')

    def test_invalid_identity_produces_no_public_key(self):
        proc = subprocess.run([NODE, str(self.script), 'org\nsynthetic', 'proj_synthetic', sys.executable],
                              input=b'', capture_output=True, timeout=10)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, b'')
