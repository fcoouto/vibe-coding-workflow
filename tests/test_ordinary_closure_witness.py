"""Boundary tests for the ordinary peer byte witness leaf."""
from contextlib import contextmanager
import errno
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from runtime import closure_witness, state


class OrdinaryClosureWitnessTests(unittest.TestCase):
    def peer_file(self, content=b"original"):
        temporary = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        path = directory / 'peer.sqlite'
        path.write_bytes(content)
        path.chmod(0o600)
        return path

    def witness(self, path, forbidden=(-1, -1)):
        return closure_witness.PeerWitness(path, closure_witness.Budget(time.monotonic()), forbidden)

    def assert_closed(self, witness):
        self.assertEqual(witness.files, {})
        self.assertIsNone(witness.stack)

    def assert_descriptors_closed(self, descriptors):
        for descriptor in descriptors:
            with self.assertRaises(OSError) as raised:
                os.fstat(descriptor)
            self.assertEqual(raised.exception.errno, errno.EBADF)

    @contextmanager
    def trace_names(self, before_scandir=None):
        original_open, original_scandir = os.open, os.scandir
        trace = dict(descriptors=[], arguments=[], visited=[])

        class RecordedEntries:
            def __init__(entries, original):
                entries.original = original

            def __enter__(entries):
                entries.original.__enter__()
                return entries

            def __exit__(entries, *args):
                return entries.original.__exit__(*args)

            def __iter__(entries):
                return entries

            def __next__(entries):
                entry = next(entries.original)
                trace['visited'].append(entry.name)
                return entry

            def close(entries):
                entries.original.close()

        def opened(*args, **kwargs):
            descriptor = original_open(*args, **kwargs)
            trace['descriptors'].append(descriptor)
            return descriptor

        def scanned(argument):
            trace['arguments'].append(argument)
            if before_scandir is not None:
                before_scandir(argument)
            return RecordedEntries(original_scandir(argument))

        try:
            with patch.object(closure_witness.os, 'open', new=opened), \
                    patch.object(closure_witness.os, 'scandir', new=scanned):
                yield trace
        finally:
            self.assert_descriptors_closed(trace['descriptors'])

    def test_four_passes_match_and_consume_exact_eof_liability_without_renewal(self):
        path = self.peer_file(b'four-pass')
        budget = closure_witness.Budget(time.monotonic())
        witness = closure_witness.PeerWitness(path, budget, (-1, -1))
        liability = 4 * (path.stat().st_size + 1)
        descriptors = []
        with witness:
            descriptors = [witness.directory, *(item['descriptor'] for item in witness.files.values())]
            facts = witness.read_pass(1)
            self.assertEqual(len(facts['files'][path.name]['sha256']), 64)
            for number in (2, 3, 4):
                self.assertEqual(witness.read_pass(number), facts)
                self.assertEqual(budget.reserved, liability)
            self.assertEqual(witness.reservation['limit'], liability)
            self.assertEqual(witness.reservation['spent'], liability)
            self.assertEqual(budget.requested, liability)
            self.assertEqual(budget.returned, 4 * path.stat().st_size)
            self.assertEqual(budget.read_calls, 8)
            with self.assertRaisesRegex(state.StateError, 'byte pass order'):
                witness.read_pass(5)
            self.assertEqual(budget.requested, liability)
        self.assert_closed(witness)
        self.assert_descriptors_closed(descriptors)

    def test_wrong_pass_order_does_not_advance_witness(self):
        path = self.peer_file()
        witness = self.witness(path)
        with witness:
            with self.assertRaisesRegex(state.StateError, 'byte pass order'):
                witness.read_pass(2)
            self.assertEqual(witness.passes, 0)
            self.assertEqual(witness.read_pass(1)['files'][path.name]['stat'][5], path.stat().st_size)
        self.assert_closed(witness)

    def test_forbidden_raw_b_inode_is_rejected_and_descriptors_are_cleaned(self):
        raw_b = self.peer_file(b'raw B identity')
        info = raw_b.stat()
        witness = self.witness(raw_b, (info.st_dev, info.st_ino))
        with self.assertRaisesRegex(state.StateError, 'aliases an authority'):
            witness.__enter__()
        self.assert_closed(witness)

    def test_same_byte_inode_replacement_is_rejected(self):
        path = self.peer_file()
        witness = self.witness(path)
        with witness:
            replacement = path.with_name('replacement.sqlite')
            replacement.write_bytes(path.read_bytes())
            replacement.chmod(0o600)
            os.replace(replacement, path)
            with self.assertRaisesRegex(state.StateError, 'peer ancestor changed|peer file identity changed'):
                witness.check_paths()
        self.assert_closed(witness)

    def test_names_rejects_directory_symlink_swap_without_visiting_foreign_entries(self):
        root = self.peer_file().parent
        directory, replacement, held = (root / name for name in ('original', 'replacement', 'held'))
        directory.mkdir(mode=0o700)
        replacement.mkdir(mode=0o700)
        (directory / 'safe-original-entry').touch(mode=0o600)
        foreign = 'foreign-replacement-entry-must-never-be-visited'
        (replacement / foreign).touch(mode=0o600)
        budget = closure_witness.Budget(time.monotonic())
        expected = budget.observe(directory)
        rejection = None

        def swapping_scandir(argument):
            self.assertEqual(len(trace['arguments']), 1, 'Only the actual target enumeration is wrapped')
            directory.rename(held)
            directory.symlink_to(replacement, target_is_directory=True)

        with self.trace_names(swapping_scandir) as trace:
            try:
                budget.names(directory, expected)
            except (state.StateError, OSError) as error:
                rejection = error
        self.scandir_visited, self.scandir_arguments = trace['visited'], trace['arguments']
        self.assertTrue(trace['descriptors'])
        self.assertEqual(len(self.scandir_arguments), 1)
        self.assertNotIn(foreign, self.scandir_visited,
            f'Real scandir visited replacement entries: {self.scandir_visited!r}; rejection={rejection!r}')
        self.assertIsNotNone(rejection, f'Directory substitution was accepted; visited={self.scandir_visited!r}')
        if isinstance(rejection, OSError):
            self.assertIn(rejection.errno, {errno.ELOOP, errno.ENOTDIR, errno.ENOENT, errno.ESTALE})

    def test_names_enumerates_unchanged_directory_with_charges_and_closes_descriptors(self):
        directory = self.peer_file().parent / 'original'
        directory.mkdir(mode=0o700)
        for name in ('second-safe-entry', 'first-safe-entry'):
            (directory / name).touch(mode=0o600)
        budget = closure_witness.Budget(time.monotonic())
        expected = budget.observe(directory)
        charged_before = budget.paths
        with self.trace_names() as trace:
            names = budget.names(directory, expected)
        self.assertEqual(names, ['first-safe-entry', 'second-safe-entry'])
        self.assertEqual(sorted(trace['visited']), names)
        self.assertEqual(len(trace['arguments']), 1)
        self.assertIsInstance(trace['arguments'][0], int, 'Enumeration must use the validated directory FD')
        self.assertTrue(trace['descriptors'])
        self.assertGreaterEqual(budget.paths - charged_before,
            len(trace['descriptors']) + len(trace['visited']) + 2)
        self.assertLessEqual(budget.paths, closure_witness.MAX_PATHS)

    def test_names_rejects_stale_expected_directory_before_enumerating_replacements(self):
        for substitution in ('symlink', 'directory'):
            with self.subTest(substitution=substitution):
                root = self.peer_file().parent
                directory, replacement, held = (root / name for name in ('original', 'replacement', 'held'))
                directory.mkdir(mode=0o700)
                replacement.mkdir(mode=0o700)
                (directory / 'safe-original-entry').touch(mode=0o600)
                foreign = 'foreign-stale-' + substitution
                (replacement / foreign).touch(mode=0o600)
                budget = closure_witness.Budget(time.monotonic())
                expected = budget.observe(directory)
                directory.rename(held)
                if substitution == 'symlink':
                    directory.symlink_to(replacement, target_is_directory=True)
                else:
                    replacement.rename(directory)
                with self.trace_names() as trace:
                    with self.assertRaises((state.StateError, OSError)) as raised:
                        budget.names(directory, expected)
                self.assertTrue(trace['descriptors'])
                self.assertNotIn(foreign, trace['visited'], f'Replacement entries visited: {trace["visited"]!r}')
                self.assertEqual(trace['arguments'], [], 'Stale expected identity reached real scandir')
                if isinstance(raised.exception, OSError):
                    self.assertIn(raised.exception.errno, {errno.ELOOP, errno.ENOTDIR, errno.ENOENT, errno.ESTALE})

    def test_retained_descriptors_close_on_failing_context_exit(self):
        path = self.peer_file()
        witness = self.witness(path)
        descriptors = []
        with self.assertRaisesRegex(RuntimeError, 'deliberate context failure'):
            with witness:
                descriptors = [witness.directory, *(item['descriptor'] for item in witness.files.values())]
                witness.read_pass(1)
                raise RuntimeError('deliberate context failure')
        self.assert_closed(witness)
        self.assert_descriptors_closed(descriptors)

    def test_in_place_growth_and_sidecar_appearance_are_rejected(self):
        for change in ('in-place', 'growth', '-journal', '-wal', '-shm'):
            with self.subTest(change=change):
                path = self.peer_file()
                witness = self.witness(path)
                with witness:
                    if change == 'in-place':
                        path.write_bytes(b'modified')
                        now = time.time_ns()
                        os.utime(path, ns=(now, now))
                    elif change == 'growth':
                        path.write_bytes(b'original-and-grown')
                        now = time.time_ns()
                        os.utime(path, ns=(now, now))
                    else:
                        # Opaque sidecar bytes exercise name rejection, not SQLite journal semantics.
                        sidecar = Path(str(path) + change)
                        sidecar.write_bytes(b'opaque sidecar')
                        sidecar.chmod(0o600)
                    with self.assertRaisesRegex(state.StateError, 'Ordinary closure'):
                        witness.check_paths()
                self.assert_closed(witness)

    def test_symlink_hardlink_and_public_file_are_rejected_with_cleanup(self):
        for kind in ('symlink', 'hardlink', 'public'):
            with self.subTest(kind=kind):
                path = self.peer_file()
                if kind == 'symlink':
                    target = path.with_name('target.sqlite')
                    path.rename(target)
                    path.symlink_to(target.name)
                elif kind == 'hardlink':
                    path.with_name('alias.sqlite').hardlink_to(path)
                else:
                    path.chmod(0o644)
                witness = self.witness(path)
                with self.assertRaisesRegex(state.StateError, 'physical type, privacy or links'):
                    witness.__enter__()
                self.assert_closed(witness)

    def test_byte_path_deadline_and_short_read_boundaries_fail_closed(self):
        budget = closure_witness.Budget(time.monotonic())
        with self.assertRaisesRegex(state.StateError, 'byte reservation exhausted'):
            budget.reserve(closure_witness.MAX_BYTES + 1)
        self.assertEqual(budget.reserved, 0)

        budget.paths = closure_witness.MAX_PATHS
        with self.assertRaisesRegex(state.StateError, 'physical operation budget exhausted'):
            budget.stat('/missing')

        expired = closure_witness.Budget(time.monotonic() - closure_witness.SECONDS - 1)
        with self.assertRaisesRegex(state.StateError, 'acceptance deadline exhausted'):
            expired.check()

        path = self.peer_file()
        witness = self.witness(path)
        with witness:
            with patch.object(closure_witness.os, 'pread', return_value=b''):
                with self.assertRaisesRegex(state.StateError, 'read is short'):
                    witness.read_pass(1)
            self.assertEqual(witness.passes, 0)
        self.assert_closed(witness)


if __name__ == '__main__':
    unittest.main()
