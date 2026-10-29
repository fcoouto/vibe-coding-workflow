"""Langfuse's wire protocol is exercised locally with synthetic credentials."""

import base64
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


PUBLIC_KEY = 'pk-lf-synthetic-test'
SECRET_KEY = 'sk-lf-synthetic-test'


@contextmanager
def protocol_server():
    with tempfile.TemporaryDirectory(prefix='vibe-langfuse-https-') as temporary:
        directory = Path(temporary)
        config = directory / 'openssl.cnf'
        config.write_text('[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n'
                          '[dn]\nCN=localhost\n[ext]\nsubjectAltName=DNS:localhost,IP:127.0.0.1\n'
                          'basicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,digitalSignature,keyEncipherment\n')
        certificate, key = directory / 'certificate.pem', directory / 'key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
            '-keyout', str(key), '-out', str(certificate), '-days', '1', '-config', str(config)],
            check=True, capture_output=True, timeout=10)
        fixture = SimpleNamespace(requests=[], span=None, project_id='lf-project', projects_status=200,
            post_status=200, partial={}, read_status=200, read_delay=0, mismatch=False, redirect=False,
            private_response=False, raw_response=None, content_type='application/json', response_delay=0,
            resource_metadata={}, metadata_extra={}, on_projects=None)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, value):
                raw = fixture.raw_response if fixture.raw_response is not None else json.dumps(value).encode()
                time.sleep(fixture.response_delay)
                self.send_response(status)
                self.send_header('Content-Type', fixture.content_type)
                self.send_header('Content-Length', str(len(raw)))
                if fixture.redirect:
                    self.send_header('Location', 'https://unrelated.invalid/credentials')
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
                    pass

            def record(self, body=None):
                fixture.requests.append(dict(method=self.command, path=self.path,
                    headers=dict(self.headers), body=body))

            def do_GET(self):
                self.record()
                if fixture.redirect:
                    self.reply(302, {})
                elif self.path == '/api/public/projects':
                    if fixture.on_projects is not None:
                        fixture.on_projects()
                    self.reply(fixture.projects_status, {'data': [{'id': fixture.project_id,
                        'name': 'PRIVATE_NAME', 'organization': {'name': 'PRIVATE_ORGANIZATION'}}]})
                elif self.path.startswith('/api/public/v2/observations?'):
                    rows = []
                    if fixture.span and not fixture.read_delay:
                        span = fixture.span
                        rows = [dict(id='wrong' if fixture.mismatch else span['spanId'],
                            traceId=span['traceId'], projectId=fixture.project_id, type='SPAN',
                            name=span['name'], input='PRIVATE_INPUT' if fixture.private_response else None,
                            output=None, metadata={'vibe_synthetic': 'true', 'vibe_probe_id': span['spanId'],
                                'resourceAttributes': fixture.resource_metadata} | fixture.metadata_extra)]
                    fixture.read_delay = max(0, fixture.read_delay - 1)
                    self.reply(fixture.read_status, {'data': rows, 'meta': {'cursor': None}})
                else:
                    self.reply(404, {'error': 'PRIVATE_RESPONSE'})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.record(body)
                if self.path != '/api/public/otel/v1/traces':
                    self.reply(404, {'error': 'PRIVATE_RESPONSE'})
                    return
                fixture.span = body['resourceSpans'][0]['scopeSpans'][0]['spans'][0]
                fixture.resource_metadata = {attribute['key']: attribute['value']['stringValue']
                    for attribute in body['resourceSpans'][0]['resource']['attributes']}
                self.reply(fixture.post_status, {'partialSuccess': fixture.partial})

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.daemon_threads = True
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        fixture.url = 'https://127.0.0.1:' + str(server.server_port)
        fixture.environment = dict(LANGFUSE_PUBLIC_KEY=PUBLIC_KEY, LANGFUSE_SECRET_KEY=SECRET_KEY,
                                  SSL_CERT_FILE=str(certificate))
        try:
            with patch.dict(os.environ, fixture.environment):
                yield fixture
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


class LangfuseTests(unittest.TestCase):
    def test_documented_fixed_resource_metadata_is_verified(self):
        from runtime import langfuse
        with protocol_server() as server:
            with patch.object(langfuse, 'READ_ATTEMPTS', 1):
                result = langfuse.synthetic_probe(server.url, 'lf-project', before_ingest=lambda: None)
            self.assertEqual(server.resource_metadata, {'service.name': 'vibe-coding-workflow'})
            self.assertTrue(result['verified'])

    def test_unexpected_resource_or_extra_metadata_is_never_verified(self):
        from runtime import langfuse
        with protocol_server() as server, patch.object(langfuse, 'READ_ATTEMPTS', 1):
            for extra in ({'resourceAttributes': {'service.name': 'PRIVATE_SERVICE'}},
                          {'resourceAttributes': {'service.name': 'vibe-coding-workflow', 'host.name': 'PRIVATE_HOST'}},
                          {'private_text': 'PRIVATE_CONTENT'}):
                server.metadata_extra = extra
                result = langfuse.synthetic_probe(server.url, 'lf-project', before_ingest=lambda: None)
                self.assertTrue(result['accepted'])
                self.assertFalse(result['verified'])
                self.assertNotIn('PRIVATE', json.dumps(result))

    def test_verifies_exact_project_without_returning_account_content(self):
        from runtime import langfuse
        with protocol_server() as server:
            self.assertIsNone(langfuse.verify_project(server.url, 'lf-project'))
            self.assertEqual(len(server.requests), 1)
            expected = 'Basic ' + base64.b64encode((PUBLIC_KEY + ':' + SECRET_KEY).encode()).decode()
            self.assertEqual(server.requests[0]['headers']['Authorization'], expected)

    def test_probe_posts_one_complete_metrics_only_span_and_reads_exact_record(self):
        from runtime import langfuse
        with protocol_server() as server:
            result = langfuse.synthetic_probe(server.url, 'lf-project', before_ingest=lambda: None)
            self.assertTrue(result['accepted'])
            self.assertTrue(result['verified'])
            self.assertEqual(result['source'], 'synthetic_smoke')
            self.assertFalse(result['native_collection_qualified'])
            posts = [request for request in server.requests if request['method'] == 'POST']
            self.assertEqual(len(posts), 1)
            self.assertEqual(posts[0]['headers']['X-Langfuse-Ingestion-Version'], '4')
            self.assertEqual(posts[0]['headers']['Content-Type'], 'application/json')
            span = server.span
            self.assertEqual(span['traceId'], result['trace_id'])
            self.assertEqual(span['spanId'], result['observation_id'])
            self.assertGreaterEqual(int(span['endTimeUnixNano']), int(span['startTimeUnixNano']))
            serialized = json.dumps(posts[0]['body'])
            for excluded in ('PRIVATE', PUBLIC_KEY, SECRET_KEY, 'lf-project', 'input', 'output', 'token', 'cost'):
                self.assertNotIn(excluded, serialized)
            self.assertIsNone(result['usage'])
            self.assertIsNone(result['charges'])

    def test_wrong_project_and_auth_failure_cannot_ingest(self):
        from runtime import langfuse
        with protocol_server() as server:
            with self.assertRaises(langfuse.LangfuseError):
                langfuse.synthetic_probe(server.url, 'different-project', before_ingest=lambda: None)
            server.projects_status = 401
            with self.assertRaises(langfuse.LangfuseError):
                langfuse.synthetic_probe(server.url, 'lf-project', before_ingest=lambda: None)
            self.assertFalse(any(request['method'] == 'POST' for request in server.requests))

    def test_invalid_destinations_fail_before_credentials_or_network(self):
        from runtime import langfuse
        for destination in ('http://localhost:3000', 'https://user:secret@example.com',
                            'https://example.com/?secret=x', 'https://example.com/#x',
                            'https://example.com/path', 'file:///tmp/secret'):
            with self.subTest(destination=destination), self.assertRaises(langfuse.LangfuseError):
                langfuse.verify_project(destination, 'lf-project')

    def test_redirect_is_rejected_without_following_it(self):
        from runtime import langfuse
        with protocol_server() as server:
            server.redirect = True
            with self.assertRaises(langfuse.LangfuseError):
                langfuse.verify_project(server.url, 'lf-project')
            self.assertEqual(len(server.requests), 1)

    def test_partial_ingestion_rejection_is_not_retried_or_verified(self):
        from runtime import langfuse
        with protocol_server() as server:
            server.partial = {'rejectedSpans': '1', 'errorMessage': 'PRIVATE_RESPONSE'}
            with self.assertRaises(langfuse.LangfuseError) as caught:
                langfuse.synthetic_probe(server.url, 'lf-project', before_ingest=lambda: None)
            self.assertNotIn('PRIVATE', str(caught.exception))
            self.assertEqual(sum(request['method'] == 'POST' for request in server.requests), 1)

    def test_readback_timeout_is_accepted_pending_without_duplicate_ingestion(self):
        from runtime import langfuse
        with protocol_server() as server:
            server.read_delay = 100
            result = langfuse.synthetic_probe(server.url, 'lf-project', before_ingest=lambda: None)
            self.assertTrue(result['accepted'])
            self.assertFalse(result['verified'])
            self.assertEqual(result['status'], 'pending')
            self.assertEqual(sum(request['method'] == 'POST' for request in server.requests), 1)
            self.assertLessEqual(sum('/v2/observations?' in request['path'] for request in server.requests), 5)

    def test_mismatched_or_contentful_readback_never_becomes_verified(self):
        from runtime import langfuse
        with protocol_server() as server:
            for flag in ('mismatch', 'private_response'):
                setattr(server, flag, True)
                result = langfuse.synthetic_probe(server.url, 'lf-project', before_ingest=lambda: None)
                self.assertTrue(result['accepted'])
                self.assertFalse(result['verified'])
                self.assertNotIn('PRIVATE', json.dumps(result))
                setattr(server, flag, False)

    def test_missing_or_partial_credentials_fail_before_network(self):
        from runtime import langfuse
        with patch('http.client.HTTPSConnection', side_effect=AssertionError('network')):
            for public, secret in (('', ''), (PUBLIC_KEY, ''), ('', SECRET_KEY), ('PRIVATE\n', SECRET_KEY)):
                with patch.dict(os.environ, dict(LANGFUSE_PUBLIC_KEY=public, LANGFUSE_SECRET_KEY=secret)):
                    with self.assertRaises(langfuse.LangfuseError) as caught:
                        langfuse.verify_project('https://cloud.langfuse.com', 'lf-project')
                    self.assertNotIn('PRIVATE', str(caught.exception))

    def test_malformed_oversized_or_non_json_response_is_sanitized(self):
        from runtime import langfuse
        with protocol_server() as server:
            for raw, content_type in ((b'{PRIVATE', 'application/json'), (b'\xff', 'application/json'),
                    (b'{"data":[],"data":[]}', 'application/json'),
                    (b'PRIVATE' * 23000, 'application/json'), (b'PRIVATE', 'text/html')):
                server.raw_response, server.content_type = raw, content_type
                with self.subTest(size=len(raw)), self.assertRaises(langfuse.LangfuseError) as caught:
                    langfuse.verify_project(server.url, 'lf-project')
                self.assertNotIn('PRIVATE', str(caught.exception))
            self.assertFalse(any(request['method'] == 'POST' for request in server.requests))

    def test_slow_response_is_bounded_and_does_not_ingest(self):
        from runtime import langfuse
        with protocol_server() as server, patch.object(langfuse, 'REQUEST_SECONDS', .05):
            server.response_delay = .2
            started = time.monotonic()
            with self.assertRaises(langfuse.LangfuseError):
                langfuse.synthetic_probe(server.url, 'lf-project', before_ingest=lambda: None)
            self.assertLess(time.monotonic() - started, 1)
            self.assertFalse(any(request['method'] == 'POST' for request in server.requests))

    def test_post_failure_and_failed_readback_never_retry_ingestion(self):
        from runtime import langfuse
        with protocol_server() as server:
            server.post_status = 503
            with self.assertRaises(langfuse.LangfuseError) as caught:
                langfuse.synthetic_probe(server.url, 'lf-project', before_ingest=lambda: None)
            self.assertEqual(str(caught.exception), 'ingestion_outcome_unknown')
            self.assertEqual(sum(request['method'] == 'POST' for request in server.requests), 1)
            server.post_status, server.read_status = 200, 503
            result = langfuse.synthetic_probe(server.url, 'lf-project', before_ingest=lambda: None)
            self.assertTrue(result['accepted'])
            self.assertFalse(result['verified'])
            self.assertEqual(result['status'], 'pending')
            self.assertEqual(sum(request['method'] == 'POST' for request in server.requests), 2)


if __name__ == '__main__':
    unittest.main()
