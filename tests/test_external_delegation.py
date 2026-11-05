"""Offline shared selection and real packet provenance."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from runtime import external_delegation as external


def permission(service='openai-api', mode='proposal', model='model', provider='openai', effort='high'):
    return dict(version=1, approval_ref='user-consent-1', classes=['investigation'],
        sources=['src'], exclusions=['src/private'], automatic=True, funding_ref='existing-funding-choice',
        valid_until=None, destinations=[dict(service=service, mode=mode, model=model, provider=provider, effort=effort)])


class ExternalTests(unittest.TestCase):
    def test_local_preference_never_spills_and_explicit_choice_wins(self):
        routes = [dict(route='openai-api', enabled=True, automatic=True, suitable=True)]
        for condition in ('ready', 'busy', 'failed', 'suspended', 'verification_unavailable'):
            with self.subTest(condition=condition):
                self.assertEqual(external.select(None, True, routes)['route'], 'local-preference')
        self.assertEqual(external.select('openai-api', True, routes)['route'], 'openai-api')
        routes[0]['enabled'] = False
        self.assertEqual(external.select('openai-api', False, routes)['route'], 'native')
        self.assertEqual(external.select('openai-api', False, routes, api_only=True)['route'], 'paused')

    def test_ambiguous_routes_and_connection_only_do_not_authorize_selection(self):
        routes = [dict(route=route, enabled=True, automatic=True, suitable=True)
                  for route in ('openai-api', 'openrouter')]
        self.assertEqual(external.select(None, False, routes)['route'], 'native')
        self.assertEqual(external.select(None, False, routes, 'openrouter')['route'], 'openrouter')
        routes = [dict(routes[0], automatic=False)]
        self.assertEqual(external.select(None, False, routes)['route'], 'native')

    def test_filesystem_case_aliases_cannot_bypass_source_or_derived_exclusions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / 'src/private').mkdir(parents=True)
            (root / 'src/private/secret.py').write_text('excluded bytes')
            alias = root / 'src/PRIVATE/secret.py'
            if not alias.exists():
                self.skipTest('filesystem does not provide this case alias')
            for part in (dict(kind='source', path='src/PRIVATE/secret.py'),
                         dict(kind='text', text='derived content', sources=['src/PRIVATE/secret.py'])):
                with self.subTest(part=part), self.assertRaisesRegex(ValueError, 'source_denied'):
                    external.prepare(root, permission(), [part])
            consent = dict(permission(), exclusions=['src/PRIVATE'])
            with self.assertRaisesRegex(ValueError, 'source_denied'):
                external.prepare(root, consent, [dict(kind='source', path='src/private/secret.py')])

    def test_linked_permission_areas_reject_source_and_derived_parts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / 'outside').mkdir()
            (root / 'outside/data.txt').write_text('outside permitted src')
            (root / 'src').symlink_to('.', target_is_directory=True)
            (root / 'ignored-exclusion').symlink_to('missing', target_is_directory=True)
            permissions = (
                permission(),
                dict(permission(), sources=['outside', 'src'], exclusions=[]),
                dict(permission(), sources=['outside'], exclusions=['ignored-exclusion']),
            )
            parts = (dict(kind='source', path='outside/data.txt'),
                     dict(kind='text', text='derived content', sources=['outside/data.txt']))
            for consent in permissions:
                for part in parts:
                    with self.subTest(consent=consent, part=part), self.assertRaisesRegex(ValueError, 'unsafe_source_area'):
                        external.prepare(root, consent, [part])

    def test_distinct_case_sensitive_directories_keep_distinct_permission(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / 'src/private').mkdir(parents=True)
            alias = root / 'src/PRIVATE'
            if alias.exists():
                self.skipTest('filesystem aliases these directory names')
            alias.mkdir()
            (alias / 'public.py').write_text('permitted bytes')
            packet = external.prepare(root, permission(), [dict(kind='source', path='src/PRIVATE/public.py')])
            self.assertIn('permitted bytes', packet['text'])

    def test_packet_is_constructed_from_scoped_source_and_rechecked(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / 'src').mkdir()
            path = root / 'src/code.py'
            path.write_text('first\nsecond\n')
            consent = permission()
            packet = external.prepare(root, consent, [dict(kind='source', path='src/code.py', start=2, end=2)])
            self.assertIn('second\n', packet['text'])
            self.assertNotIn('first', packet['text'])
            binding = dict(packet['binding'], automatic=True, local_preferred=False)
            options = dict(service='openai-api', mode='proposal', model='model', provider='openai',
                           effort='high', class_name='investigation', now=100)
            self.assertEqual(external.check(root, consent, binding, **options)['text'], packet['text'])
            with self.assertRaisesRegex(ValueError, 'destination'):
                external.check(root, consent, binding, **(options | dict(provider='other')))
            revoked = dict(consent, approval_ref='replacement')
            with self.assertRaisesRegex(ValueError, 'permission_changed'):
                external.check(root, revoked, binding, **options)
            path.write_text('edited\n')
            with self.assertRaisesRegex(ValueError, 'source_changed'):
                external.check(root, consent, binding, **options)
            refreshed = external.prepare(root, consent, [dict(kind='source', path='src/code.py')])
            self.assertIn('edited', refreshed['text'])
            (root / 'src/private').mkdir()
            (root / 'src/private/secret').write_text('excluded')
            for part in (dict(kind='source', path='src/private/secret'),
                         dict(kind='text', text='derived secret', sources=['src/private/secret']),
                         dict(kind='unknown', text='unclassified')):
                with self.subTest(part=part), self.assertRaises(ValueError):
                    external.prepare(root, consent, [part])
