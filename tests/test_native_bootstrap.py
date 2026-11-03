"""Owned fake transports prove software behavior, never actual client qualification."""

import copy
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from runtime import changes, doctor, setup_observation as source, startup
from scripts.onboard_coordinator import CoordinatorOperationOwner
from tests.fixture_canonical_birth import CanonicalBirthFixture


class PublicCanaryPatchTests(unittest.TestCase):
    def descriptor(self,patch=None):
        return dict(canary='/approved/project/public-canary.txt',before_sha256=hashlib.sha256(b'before\n').hexdigest(),
            patch=patch or '*** Begin Patch\n*** Update File: public-canary.txt\n@@\n-before\n+after\n*** End Patch')

    def test_multiline_single_update_matches_original_public_canary(self):
        source._public_canary_patch(self.descriptor(),Path('/approved/project'),readback='before\n')

    def test_other_files_moves_traversal_and_control_characters_are_rejected(self):
        valid=self.descriptor()['patch']
        invalid=[valid.replace('public-canary.txt','other.txt'),valid.replace('public-canary.txt','../public-canary.txt'),
            valid.replace('@@','*** Move to: moved.txt\n@@'),valid.replace('*** End Patch','*** Add File: other.txt\n+x\n*** End Patch'),
            valid.replace('*** End Patch','*** Delete File: other.txt\n*** End Patch'),valid.replace('+after','+after\x00')]
        for patch_text in invalid:
            with self.subTest(patch=patch_text),self.assertRaises(startup.StartupError):
                source._public_canary_patch(self.descriptor(patch_text),Path('/approved/project'),readback='before\n')

    def test_stale_empty_and_unchanged_hunks_are_rejected(self):
        for patch_text in [self.descriptor()['patch'].replace('-before','-stale'),
                self.descriptor()['patch'].replace('+after','+before'),'*** Begin Patch\n*** End Patch']:
            with self.subTest(patch=patch_text),self.assertRaises(startup.StartupError):
                source._public_canary_patch(self.descriptor(patch_text),Path('/approved/project'),readback='before\n')


class PackageScanTests(unittest.TestCase):
    def package(self):
        temporary=tempfile.TemporaryDirectory(prefix='qualification-package-scan-');self.addCleanup(temporary.cleanup)
        root=Path(temporary.name).resolve();sources=[Path('runtime/a.py'),Path('runtime/adapters/a.py'),Path('scripts/workflow.py')]
        for index,path in enumerate([*sources,Path('other.txt')]):
            (root/path).parent.mkdir(parents=True,exist_ok=True);(root/path).write_bytes(str(index).encode())
        return root,sources

    def test_bundle_scan_preserves_runtime_framing_without_double_reading(self):
        root,sources=self.package();budget=source._budget()
        with patch.object(source,'_read',wraps=source._read) as reads:
            bundle,runtime=source._package_scan(root,budget,runtime_sources=sources)
        self.assertEqual(reads.call_count,4)
        self.assertEqual(len({call.args[0] for call in reads.call_args_list}),4)
        expected=hashlib.sha256()
        for path in sources:expected.update(str(path).encode()+b'\0'+(root/path).read_bytes()+b'\0')
        self.assertEqual(runtime,expected.hexdigest())
        self.assertEqual(bundle,source.plugin_content_hash(root,source._budget()))
        self.assertEqual(budget['bytes'],4)

    def test_changed_runtime_source_changes_its_exact_identity(self):
        root,sources=self.package()
        before=source._package_scan(root,source._budget(),runtime_sources=sources)
        (root/sources[1]).write_bytes(b'changed')
        after=source._package_scan(root,source._budget(),runtime_sources=sources)
        self.assertNotEqual(before[0],after[0]);self.assertNotEqual(before[1],after[1])

    def test_missing_runtime_member_is_rejected_without_changing_plain_bundle_api(self):
        root,sources=self.package()
        with self.assertRaisesRegex(startup.StartupError,'scan order'):
            source._package_scan(root,source._budget(),runtime_sources=list(reversed(sources)))
        (root/sources[1]).unlink()
        with self.assertRaises(startup.StartupError):
            source._package_scan(root,source._budget(),runtime_sources=sources)
        self.assertTrue(source.plugin_content_hash(root,source._budget()).startswith('sha256:'))


class NativeBootstrapTests(unittest.TestCase):
    def test_public_probe_retains_actual_writable_mode_and_bounded_readback(self):
        fixture,identity,_,_,_=self.owner()
        canary=fixture.repo/'qualification-canary.txt';canary.write_text('original public canary\n');canary.chmod(0o640)
        fact=source._probe_fact(identity,str(canary))
        self.assertEqual(fact['readback'],'original public canary\n')
        self.assertEqual(fact['target']['fingerprint']['mode'],0o640)
        self.assertEqual(fact['target']['binding'],dict(device=canary.stat().st_dev,inode=canary.stat().st_ino))
        canary.chmod(0o440)
        with self.assertRaisesRegex(startup.StartupError,'actually writable'):
            source._probe_fact(identity,str(canary))

    def owner(self):
        birth=CanonicalBirthFixture('runTest');self.addCleanup(birth.doCleanups)
        fixture,request,decision,_=birth.prepare()
        record=request['manifest']['enrollment']['record'];key=next(iter(changes._scoped_entries(record)))
        identity=startup._canonical_plain(startup.canonical_scope_projection(startup.decode_project_record(record),
            repository_id=key[0],checkout_id=key[1],client=key[2]))
        home=fixture.base/'native-home';home.mkdir()
        reference=dict(reference='fixture:original-native-allocation',sha256='a'*64)
        attempt=dict(reference=reference,task=None,native_sessions=[],operations=['observe-cli-basic'],capability_keys=['startup-context'],
            limits=dict(deadline=time.time()+30,max_attempts=1,max_resource_units=1),stop_conditions=['Stop after this exact observation'],
            native_execution=dict(argv=[sys.executable,'-I','-B','-c','import time;time.sleep(30)'],cwd=str(fixture.repo),
                timeout_seconds=2,external_effects=[dict(path=str(home),kind='vendor-owned-state',recovery='manual')],
                serialization_reference=dict(reference='fixture:observed-exclusive-native-state',sha256='b'*64)))
        decision=copy.deepcopy(decision)
        decision['qualification_scope']=dict(decision_reference=decision['decision_reference'],target=dict(
            accepted_scope_digest=startup._canonical_digest(identity),repository_root=str(fixture.repo),git_common_dir=identity['git_common_dir'],disposable=True),
            attempts=[attempt])
        return fixture,identity,reference,home,CoordinatorOperationOwner(decision)

    def test_native_source_without_original_external_authority_cannot_launch(self):
        birth=CanonicalBirthFixture('runTest');self.addCleanup(birth.doCleanups)
        fixture,request,decision,_=birth.prepare()
        record=request['manifest']['enrollment']['record'];key=next(iter(changes._scoped_entries(record)))
        identity=startup._canonical_plain(startup.canonical_scope_projection(startup.decode_project_record(record),
            repository_id=key[0],checkout_id=key[1],client=key[2]))
        owner=CoordinatorOperationOwner(decision)
        reference=dict(reference='fixture:unapproved-native-observation',sha256='a'*64)
        with patch('runtime.doctor.NativeProcess',side_effect=AssertionError('Unapproved native process launched')):
            with self.assertRaises(startup.StartupError):
                owner.observe_native_source(identity,reference,lambda process,admission: None)

    def test_failed_native_observation_consumes_original_claim_and_reconciliation_cannot_replay(self):
        fixture,identity,reference,home,owner=self.owner();seen=[]
        def observe(process,admission):
            seen.append(process)
            self.assertIsNone(source.setup_probe_projection(admission,process=process))
            self.assertIsNone(source.setup_context_projection(admission,process=process))
            with self.assertRaises(startup.StartupError):source.setup_probe_projection({},process=process)
            raise doctor.ObservationError('fixture-private-native-failure')
        with patch.dict(os.environ,CODEX_HOME=str(home)),self.assertRaisesRegex(changes.Pending,'allocation remains consumed'):
            owner.observe_native_source(identity,reference,observe)
        journal=changes._load_journal(fixture.directory);row=journal['native_observations'][startup._canonical_digest(reference)]
        self.assertEqual(row['status'],'failed');self.assertFalse(row['stopped']);self.assertIsNotNone(seen[0].process.poll())
        claim=source._native_reference(fixture.directory,row)
        proof=dict(claim_id=row['claim_id'],pid=row['pid'],returncode=row['returncode'],stopped=True,descendants_stopped=True,
            evidence=[dict(reference='fixture:actual-original-direct-child-reaped',sha256='c'*64),
                dict(reference='fixture:independent-original-no-descendants',sha256='d'*64)])
        with patch('time.time',return_value=time.time()+60):
            self.assertEqual(startup._canonical_plain(owner.reconcile_native_source(reference,claim,proof)),claim)
        self.assertEqual(changes._load_journal(fixture.directory)['native_observations'][startup._canonical_digest(reference)]['status'],'failed')
        with patch.dict(os.environ,CODEX_HOME=str(home)),self.assertRaises(startup.StartupError):
            owner.observe_native_source(identity,reference,observe)
        self.assertEqual(len(seen),1)


if __name__=='__main__':
    unittest.main()
