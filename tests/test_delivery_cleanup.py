"""Conditional remote-ref deletion against real disposable Git repositories."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch


class ConditionalDeletionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.repo, self.remote = self.root / 'checkout', self.root / 'remote.git'
        self.git_executable = shutil.which('git')
        self.environment = os.environ | dict(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        self.git('init', '-q', '-b', 'main', str(self.repo))
        self.git('init', '-q', '--bare', '-b', 'main', str(self.remote))
        for key, value in (('user.name', 'Fixture'), ('user.email', 'fixture@example.invalid'), ('commit.gpgsign', 'false')):
            self.git('-C', str(self.repo), 'config', key, value)
        (self.repo / 'file').write_text('one\n')
        self.git('-C', str(self.repo), 'add', 'file')
        self.git('-C', str(self.repo), 'commit', '-qm', 'fixture')
        self.head = self.git('-C', str(self.repo), 'rev-parse', 'HEAD').strip().decode()
        self.git('-C', str(self.repo), 'branch', 'feature')
        self.git('-C', str(self.repo), 'push', '-q', str(self.remote), 'HEAD:refs/heads/feature')
        self.calls, self.race, self.lose_ack = [], None, False

    def git(self, *args):
        return subprocess.check_output([self.git_executable, *args], env=self.environment, stderr=subprocess.DEVNULL, timeout=5)

    def transport(self):
        from runtime.adapters.git_delivery import GitRemote

        def run(argv, **bounds):
            self.calls.append(argv)
            if 'push' in argv and self.race:
                callback, self.race = self.race, None
                callback()
            result = subprocess.run(argv, env=self.environment, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, timeout=bounds['timeout'], check=False)
            if 'push' in argv and self.lose_ack:
                self.lose_ack = False
                raise subprocess.TimeoutExpired(argv[0], bounds['timeout'])
            return result.returncode, result.stdout

        return GitRemote(executable=self.git_executable, root=str(self.repo), destination=str(self.remote), run=run)

    def refs(self):
        return self.git('-C', str(self.repo), 'for-each-ref', '--format=%(refname) %(objectname)', 'refs/heads')

    def test_exact_lease_deletes_only_the_remote_ref(self):
        transport = self.transport()
        local = self.refs()
        result = transport.delete('feature', self.head, inspection=transport.inspect())
        self.assertEqual(result['status'], 'deleted', result)
        self.assertEqual(self.refs(), local)
        self.assertTrue(self.repo.exists())
        push = next(argv for argv in self.calls if 'push' in argv)
        self.assertIn('--force-with-lease=refs/heads/feature:' + self.head, push)
        self.assertEqual(push[-1], ':refs/heads/feature')
        self.assertNotIn('--force', push)
        self.assertNotIn('--no-verify', push)

    def advance(self):
        (self.repo / 'file').write_text('two\n')
        self.git('-C', str(self.repo), 'commit', '-qam', 'advanced')
        self.new_head = self.git('-C', str(self.repo), 'rev-parse', 'HEAD').strip().decode()
        self.git('-C', str(self.repo), 'push', '-q', str(self.remote), 'HEAD:refs/heads/feature')

    def test_advanced_ref_is_retained_before_or_during_deletion(self):
        transport = self.transport()
        inspection = transport.inspect()
        self.race = self.advance
        result = transport.delete('feature', self.head, inspection=inspection)
        self.assertEqual(result['status'], 'retained', result)
        remote = self.git('ls-remote', str(self.remote), 'refs/heads/feature')
        self.assertTrue(remote.startswith(self.new_head.encode()))
        self.assertEqual(transport.delete('feature', self.head, inspection=transport.inspect())['status'], 'retained')

    def test_lost_acknowledgment_and_absence_are_observed_before_retry(self):
        transport = self.transport()
        self.lose_ack = True
        self.assertEqual(transport.delete('feature', self.head, inspection=transport.inspect())['status'], 'deleted')
        self.calls.clear()
        self.assertEqual(transport.delete('feature', self.head, inspection=transport.inspect())['status'], 'absent')
        self.assertFalse(any('push' in argv for argv in self.calls))

    def test_changed_inspected_configuration_retains_the_branch(self):
        transport = self.transport()
        inspection = transport.inspect()
        self.git('-C', str(self.repo), 'config', 'core.hooksPath', str(self.root / 'other-hooks'))
        self.assertEqual(transport.delete('feature', self.head, inspection=inspection)['status'], 'retained')
        self.assertFalse(any('push' in argv for argv in self.calls))

    def test_unavailable_remote_does_not_mean_absent(self):
        transport = self.transport()
        inspection = transport.inspect()
        shutil.rmtree(self.remote)
        self.assertEqual(transport.delete('feature', self.head, inspection=inspection)['status'], 'pending')
        self.assertFalse(any('push' in argv for argv in self.calls))

    def test_surviving_git_checkout_can_delete_without_the_original_worktree(self):
        from runtime.adapters.git_delivery import GitRemote
        original = self.transport()
        survivor = self.root / 'survivor'
        self.git('init', '-q', '-b', 'main', str(survivor))
        shutil.rmtree(self.repo)
        transport = GitRemote(executable=self.git_executable, root=str(survivor),
            destination=str(self.remote), run=original.run)
        result = transport.delete('feature', self.head, inspection=transport.inspect())
        self.assertEqual(result['status'], 'deleted', result)
        self.assertTrue((survivor / '.git').exists())
        self.assertFalse(self.repo.exists())

    def test_inspected_pre_push_hook_runs_without_being_bypassed(self):
        marker = self.root / 'hook-ran'
        hook = self.repo / '.git/hooks/pre-push'
        hook.write_text('#!/bin/sh\n: > "' + str(marker) + '"\nexit 1\n')
        hook.chmod(0o700)
        transport = self.transport()
        inspection = transport.inspect()
        self.assertIsNotNone(inspection['pre_push'])
        self.assertEqual(transport.delete('feature', self.head, inspection=inspection)['status'], 'pending')
        self.assertTrue(marker.exists())
        self.assertTrue(self.git('ls-remote', str(self.remote), 'refs/heads/feature').startswith(self.head.encode()))

    def test_remote_alias_cannot_redirect_the_approved_destination(self):
        from runtime.adapters.git_delivery import GitRemote
        transport = self.transport()
        self.git('-C', str(self.repo), 'remote', 'add', 'origin', str(self.remote))
        with self.assertRaises(ValueError):
            GitRemote(executable=self.git_executable, root=str(self.repo), destination='origin', run=transport.run)

    def test_unqualified_descriptor_platform_is_explicit(self):
        from runtime.adapters.git_delivery import GitRemote
        with patch('runtime.adapters.git_delivery.os.name', 'nt'), self.assertRaisesRegex(ValueError, 'qualified POSIX'):
            GitRemote(executable=self.git_executable, root=str(self.repo), destination=str(self.remote), run=lambda *a, **k: None)

    def test_hook_replacement_with_fifo_cannot_block_inspection(self):
        hook = self.repo / '.git/hooks/pre-push'
        hook.write_text('#!/bin/sh\nexit 0\n')
        script = textwrap.dedent('''
            import os
            import sys
            from pathlib import Path
            from unittest.mock import patch
            from runtime.adapters.git_delivery import GitRemote
            root, hook, executable = ROOT, HOOK, EXECUTABLE
            old_stat, old_open = Path.stat, os.open
            replaced = False
            def replace():
                global replaced
                if not replaced:
                    replaced = True
                    hook.unlink()
                    os.mkfifo(hook)
            def raced_stat(path, *args, **kwargs):
                result = old_stat(path, *args, **kwargs)
                if path == hook and sys._getframe(1).f_code.co_name == 'inspect': replace()
                return result
            def raced_open(path, flags, *args, **kwargs):
                if str(path) == str(hook): replace()
                return old_open(path, flags, *args, **kwargs)
            def run(argv, **bounds):
                if 'config' in argv: return 1, b''
                if '--git-path' in argv: return 0, str(hook).encode()
                return 0, ('\\n'.join([str(root), str(root/'.git'), str(root/'.git')])+'\\n').encode()
            transport = GitRemote(executable=executable, root=str(root), destination=DESTINATION, run=run)
            with patch.object(Path, 'stat', raced_stat), patch.object(os, 'open', raced_open):
                try: transport.inspect()
                except (ValueError, OSError): print('bounded refusal')
        ''').replace('ROOT', repr(self.repo)).replace('HOOK', repr(hook)).replace('EXECUTABLE', repr(self.git_executable)).replace('DESTINATION', repr(str(self.remote)))
        # Paths are represented as pathlib objects in the isolated race reproducer.
        script = 'from pathlib import PosixPath\n' + script
        try:
            result = subprocess.run([sys.executable, '-B', '-c', script], capture_output=True, timeout=3)
        except subprocess.TimeoutExpired:
            self.fail('Hook inspection blocked after FIFO replacement')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIn(b'bounded refusal', result.stdout)
