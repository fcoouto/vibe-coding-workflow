"""Pure OpenCode configuration controls; no enrollment or worker execution."""
import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/openrouter_workers.py'
spec = importlib.util.spec_from_file_location('openrouter_tool_profile', SCRIPT)
workers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workers)


class ToolProfileTests(unittest.TestCase):
    def setUp(self):
        self.brief = dict(files=['src/example.py'], steps=4, model='vendor/model',
                          provider='fixture-provider', effort='high')

    def test_disables_automatic_formatters(self):
        self.assertIs(workers.configuration(self.brief).get('formatter'), False)

    def test_disables_automatic_language_servers(self):
        self.assertIs(workers.configuration(self.brief).get('lsp'), False)

    def test_preserves_read_only_permissions_and_route_options(self):
        for output_tokens in (None, 8192):
            with self.subTest(output_tokens=output_tokens):
                brief = dict(self.brief)
                if output_tokens is not None:
                    brief['validated_output_tokens'] = output_tokens
                config = workers.configuration(brief)
                self.assertEqual(config['permission'], {
                    '*': 'deny', 'read': {'*': 'deny', 'src/example.py': 'allow'},
                    'glob': 'allow', 'grep': 'allow'})
                self.assertEqual(config['agent']['pilot']['mode'], 'primary')
                self.assertEqual(config['agent']['pilot']['steps'], 4)
                self.assertEqual(config['plugin'], [])
                self.assertEqual(config['mcp'], {})
                self.assertEqual(config['instructions'], [])
                self.assertEqual(config['share'], 'disabled')
                self.assertIs(config['autoupdate'], False)
                self.assertEqual(config['provider'], {'openrouter': {'models': {
                    'vendor/model': {'options': {
                        'maxOutputTokens': 2048 if output_tokens is None else 8192,
                        'reasoning': {'effort': 'high'},
                        'provider': {'only': ['fixture-provider'], 'allow_fallbacks': False}}}}}})


if __name__ == '__main__':
    unittest.main()
