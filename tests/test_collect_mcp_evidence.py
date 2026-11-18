"""Local protocol fixtures only: these are not Ignition Gateway evidence."""
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'research/collect_mcp_evidence.py'


@contextlib.contextmanager
def server(scenario='paged', **options):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            calls.append({'method': 'GET', 'path': self.path, 'headers': dict(self.headers)})
            if scenario == 'openapi-denial':
                self.reply(403, {'echo': 'private-response-content'})
                return
            self.reply(200, {'openapi': '3.1.0', 'info': {'title': 'Fixture', 'version': '1'},
                             'servers': [{'url': 'http://10.22.33.44/internal'}],
                             'paths': {'/fixture-resource': {'get': {}}},
                             'components': {'schemas': {'Token': {'type': 'object'}},
                                            'securitySchemes': {'ApiKey': {
                                                'type': 'apiKey', 'in': 'header', 'name': 'X-Fixture-Rest'}}}})

        def reply(self, status, data, sse=False, **headers):
            self.send_response(status)
            self.send_header('Content-Type', 'text/event-stream' if sse else 'application/json')
            for key, value in headers.items():
                self.send_header(key.replace('_', '-'), value)
            self.end_headers()
            if sse:
                self.wfile.write(b': fixture heartbeat\n\n')
                self.wfile.write(b'data: {"jsonrpc":"2.0","method":"notifications/progress"}\n\n')
                self.wfile.write(('event: message\ndata: ' + json.dumps(data) + '\n\n').encode())
            elif data is not None:
                self.wfile.write(json.dumps(data).encode())

        def do_POST(self):
            message = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append({'method': 'POST', 'path': self.path,
                          'headers': dict(self.headers), 'message': message})
            method = message['method']
            if scenario == 'redirect':
                self.reply(302, None, Location=options['target'])
                return
            if scenario == 'denied':
                self.reply(403, {'echo': 'FixtureSecret alpha-12345 session-fixture-ABC'})
                return
            if method == 'initialize':
                self.reply(200, {'jsonrpc': '2.0', 'id': message['id'], 'result': {
                    'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}},
                    'serverInfo': {'name': 'localhost-lab', 'version': 'fixture-1',
                                   'password': ['private-array-password'],
                                   'apiKey': {'value': 'private-wrapped-api-key'}}}},
                    Mcp_Session_Id='session-fixture-ABC', Set_Cookie='fixture=private-cookie-value')
            elif method == 'notifications/initialized':
                self.reply(202, None)
            elif method == 'tools/list':
                cursor = message['params'].get('cursor')
                if scenario == 'malformed':
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(b'{not valid JSON private-response-content')
                    return
                if scenario == 'late-denial' and cursor is not None:
                    self.reply(403, {'echo': 'private-response-content'})
                    return
                tool = {'name': 'fixture_read' if cursor is None else 'fixture_inspect',
                        'description': 'http://10.22.33.44/internal alice-lab [default]Private/Valve '
                                       'FixtureSecret alpha-12345 session-fixture-ABC cursor-fixture-XYZ',
                        'inputSchema': {'type': 'object', 'properties': {
                            'password': {'type': 'string', 'default': 'unlisted-fixture-secret'},
                            'path': {'type': 'string', 'examples': ['[default]Private/Valve']}},
                            'required': ['path']}, 'annotations': {'readOnlyHint': True}}
                result = {'tools': [tool]}
                if cursor is None or scenario == 'loop':
                    result['nextCursor'] = 'cursor-fixture-XYZ'
                if scenario == 'invalid-cursor':
                    result['nextCursor'] = 9
                if scenario == 'empty-cursor' and cursor is None:
                    result['nextCursor'] = ''
                response = {'jsonrpc': '2.0', 'id': message['id'], 'result': result}
                if scenario == 'wrong-id':
                    response['id'] = 9999
                if scenario == 'rpc-error':
                    response = {'jsonrpc': '2.0', 'id': message['id'],
                                'error': {'code': -32603, 'message': 'private-response-content'}}
                self.reply(200, response, sse=cursor is not None)
            else:
                self.reply(400, {'error': 'fixture never accepts tool execution'})

    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        yield f'http://127.0.0.1:{httpd.server_port}/fixture/mcp', calls
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join()


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.headers = self.root / 'headers.json'
        self.headers.write_text(json.dumps({'X-Fixture-Authorization': 'FixtureSecret alpha-12345'}))
        self.metadata = self.root / 'metadata.json'
        self.metadata.write_text(json.dumps({'gateway_version': '2027.2.0-beta1',
                                            'isolated_test_gateway': True,
                                            'synthetic_data_only': True,
                                            'modules': [{'name': 'Fixture module', 'version': 'fixture-1'}]}))
        self.redactions = self.root / 'redactions.json'
        self.redactions.write_text(json.dumps(['alice-lab', '[default]Private/Valve', 'localhost-lab']))
        self.output = self.root / 'evidence.json'

    def run_cli(self, url, *extra, acknowledge=True):
        command = [sys.executable, str(SCRIPT), '--url', url,
                   '--headers-file', str(self.headers), '--metadata-file', str(self.metadata),
                   '--redactions-file', str(self.redactions), '--output', str(self.output)]
        if acknowledge:
            command.append('--isolated-test-gateway')
        return subprocess.run(command + list(extra), capture_output=True, text=True, timeout=15)

    def report(self):
        self.assertTrue(self.output.exists(), 'collector must save a structured evidence report')
        return json.loads(self.output.read_text())

    def assert_private(self, process):
        exported = process.stdout + process.stderr + (self.output.read_text() if self.output.exists() else '')
        for value in ['alpha-12345', 'session-fixture-ABC', 'cursor-fixture-XYZ', '127.0.0.1',
                      '10.22.33.44', 'alice-lab', '[default]Private/Valve', 'localhost-lab',
                      'private-cookie-value', 'unlisted-fixture-secret', 'private-response-content']:
            self.assertNotIn(value, exported)

    def test_collects_every_json_and_sse_page_without_calling_tools(self):
        with server() as (url, calls):
            result = self.run_cli(url)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = self.report()
        self.assertTrue(report['completed'])
        self.assertEqual([t['name'] for t in report['mcp']['tools']], ['fixture_read', 'fixture_inspect'])
        self.assertEqual(report['mcp']['page_count'], 2)
        self.assertTrue(report['mcp']['session_header_present'])
        self.assertEqual(report['mcp']['tools'][0]['inputSchema']['required'], ['path'])
        self.assertEqual(report['authentication']['supplied_header_names'], ['X-Fixture-Authorization'])
        self.assertEqual([x['message']['method'] for x in calls],
                         ['initialize', 'notifications/initialized', 'tools/list', 'tools/list'])
        self.assertEqual(calls[-1]['message']['params'], {'cursor': 'cursor-fixture-XYZ'})
        self.assertEqual(calls[-1]['headers'].get('Mcp-Session-Id'), 'session-fixture-ABC')
        self.assertEqual(calls[-1]['headers'].get('Mcp-Protocol-Version'), '2025-06-18')
        self.assertEqual(calls[-1]['headers'].get('X-Fixture-Authorization'), 'FixtureSecret alpha-12345')
        self.assertEqual(os.stat(self.output).st_mode & 0o777, 0o600)
        self.assert_private(result)

    def test_follows_an_empty_string_cursor_instead_of_silently_truncating(self):
        with server('empty-cursor') as (url, calls):
            result = self.run_cli(url)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[-1]['message']['params'], {'cursor': ''})
        self.assertEqual(self.report()['mcp']['page_count'], 2)

    def test_repeated_cursor_fails_and_marks_partial_evidence_incomplete(self):
        with server('loop') as (url, calls):
            result = self.run_cli(url)
        self.assertNotEqual(result.returncode, 0)
        report = self.report()
        self.assertFalse(report['completed'])
        self.assertFalse(report['mcp']['complete'])
        self.assertEqual(report['errors'][0]['kind'], 'repeated_cursor')
        self.assertEqual(len(calls), 4)
        self.assert_private(result)

    def test_later_page_denial_never_becomes_a_complete_tool_list(self):
        with server('late-denial') as (url, _):
            result = self.run_cli(url)
        self.assertNotEqual(result.returncode, 0)
        report = self.report()
        self.assertFalse(report['mcp']['complete'])
        self.assertEqual(report['errors'][0]['status'], 403)
        self.assert_private(result)

    def test_rejects_mismatched_response_id_and_invalid_cursor(self):
        for scenario, kind in [('wrong-id', 'invalid_rpc_response'), ('invalid-cursor', 'invalid_cursor'),
                               ('rpc-error', 'rpc_error')]:
            with self.subTest(scenario=scenario), server(scenario) as (url, _):
                if self.output.exists():
                    self.output.unlink()
                result = self.run_cli(url)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.report()['errors'][0]['kind'], kind)
                self.assert_private(result)

    def test_http_denial_records_status_without_body_or_secrets(self):
        with server('denied') as (url, calls):
            result = self.run_cli(url)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)
        report = self.report()
        self.assertEqual(report['errors'][0]['status'], 403)
        self.assertFalse(report['authentication']['initialize_accepted'])
        self.assert_private(result)

    def test_redirect_is_not_followed_even_with_credentials(self):
        with server() as (target, target_calls):
            with server('redirect', target=target) as (url, _):
                result = self.run_cli(url)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target_calls, [])
        self.assertEqual(self.report()['errors'][0]['status'], 302)
        self.assert_private(result)

    def test_requires_isolation_ack_before_any_network_operation(self):
        with server() as (url, calls):
            result = self.run_cli(url, acknowledge=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_metadata_must_confirm_isolation_and_synthetic_data(self):
        self.metadata.write_text(json.dumps({'gateway_version': '8.3.9',
                                            'isolated_test_gateway': False, 'synthetic_data_only': True}))
        with server() as (url, calls):
            result = self.run_cli(url)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_refuses_credential_urls_and_existing_output_without_network(self):
        for suffix in ['?token=private-url-secret', '#private-fragment']:
            with self.subTest(suffix=suffix), server() as (url, calls):
                result = self.run_cli(url + suffix)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])
                self.assertNotIn('private-url-secret', result.stdout + result.stderr)
        self.output.write_text('previous evidence')
        with server() as (url, calls):
            result = self.run_cli(url)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])
        self.assertEqual(self.output.read_text(), 'previous evidence')

    def test_openapi_uses_separate_explicit_headers_and_redacts_servers(self):
        rest_headers = self.root / 'rest-headers.json'
        rest_headers.write_text(json.dumps({'X-Fixture-Rest': 'rest-private-secret'}))
        with server() as (url, calls):
            openapi = url.replace('/fixture/mcp', '/fixture/openapi')
            result = self.run_cli(url, '--openapi-url', openapi, '--openapi-headers-file', str(rest_headers))
        self.assertEqual(result.returncode, 0, result.stderr)
        request = calls[-1]
        self.assertEqual(request['method'], 'GET')
        self.assertEqual(request['headers'].get('X-Fixture-Rest'), 'rest-private-secret')
        self.assertNotIn('X-Fixture-Authorization', request['headers'])
        self.assertTrue(self.report()['openapi']['complete'])
        self.assertIn('/fixture-resource', self.report()['openapi']['document']['paths'])
        self.assert_private(result)
        self.assertNotIn('rest-private-secret', self.output.read_text())

    def test_page_limit_prevents_an_unbounded_discovery(self):
        with server() as (url, calls):
            result = self.run_cli(url, '--max-pages', '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.report()['errors'][0]['kind'], 'page_limit_exceeded')
        self.assertEqual(len(calls), 3)
        self.assertFalse(self.report()['mcp']['complete'])

    def test_malformed_json_is_recorded_without_echoing_server_content(self):
        with server('malformed') as (url, _):
            result = self.run_cli(url)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.report()['errors'][0]['kind'], 'invalid_response_json')
        self.assert_private(result)

    def test_openapi_keeps_named_schema_and_authentication_definitions(self):
        with server() as (url, _):
            result = self.run_cli(url, '--openapi-url', url.replace('/fixture/mcp', '/fixture/openapi'))
        self.assertEqual(result.returncode, 0, result.stderr)
        definitions = self.report()['openapi']['document']['components']
        self.assertEqual(definitions['schemas']['Token'], {'type': 'object'})
        self.assertEqual(definitions['securitySchemes']['ApiKey'],
                         {'type': 'apiKey', 'in': 'header', 'name': 'X-Fixture-Rest'})

    def test_openapi_denial_does_not_erase_successful_mcp_collection(self):
        with server('openapi-denial') as (url, _):
            result = self.run_cli(url, '--openapi-url', url.replace('/fixture/mcp', '/fixture/openapi'))
        self.assertNotEqual(result.returncode, 0)
        report = self.report()
        self.assertFalse(report['completed'])
        self.assertTrue(report['mcp']['complete'])
        self.assertFalse(report['openapi']['complete'])
        self.assertEqual(report['errors'][0]['status'], 403)
        self.assert_private(result)

    def test_private_containers_are_redacted_without_destroying_schema_property_definitions(self):
        with server() as (url, _):
            result = self.run_cli(url)
        self.assertEqual(result.returncode, 0, result.stderr)
        exported = self.output.read_text()
        self.assertNotIn('private-array-password', exported)
        self.assertNotIn('private-wrapped-api-key', exported)
        schema = self.report()['mcp']['tools'][0]['inputSchema']
        self.assertEqual(schema['properties']['password']['type'], 'string')

    def test_schema_examples_keep_annotation_type_after_redaction(self):
        with server() as (url, _):
            result = self.run_cli(url)
        self.assertEqual(result.returncode, 0, result.stderr)
        examples = self.report()['mcp']['tools'][0]['inputSchema']['properties']['path']['examples']
        self.assertIsInstance(examples, list)
        self.assertNotIn('[default]Private/Valve', examples)

    def test_openapi_cannot_send_credentials_to_a_different_origin(self):
        with server() as (other, other_calls), server() as (url, calls):
            result = self.run_cli(url, '--openapi-url', other)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])
        self.assertEqual(other_calls, [])


if __name__ == '__main__':
    unittest.main()
