"""Read-only MCP evidence collection for explicitly attested, isolated test Gateways.

No endpoint/authentication discovery, tool execution, login, retries or writes to a
Gateway. Authentication header names/values are supplied in private JSON files.
"""
import argparse
import datetime
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

MAX_BYTES = 8 * 1024 * 1024
REDACTED = '[redacted]'


class CollectionError(Exception):
    def __init__(self, kind, status=None, rpc_code=None):
        self.kind, self.status, self.rpc_code = kind, status, rpc_code

    def record(self, phase):
        result = {'phase': phase, 'kind': self.kind}
        if self.status is not None:
            result['status'] = self.status
        if self.rpc_code is not None:
            result['rpc_code'] = self.rpc_code
        return result


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default error can echo secrets from an invalid command line.
        raise CollectionError('invalid_arguments')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_json(path):
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise CollectionError('input_too_large')
        return json.loads(raw)
    except (OSError, ValueError, UnicodeError):
        raise CollectionError('invalid_private_input') from None


def validate_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or
                parsed.username is not None or parsed.password is not None or
                parsed.query or parsed.fragment or any(ord(c) <= 32 for c in url)):
            raise ValueError
        return parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == 'https' else 80)
    except (ValueError, AttributeError):
        raise CollectionError('invalid_endpoint') from None


def read_headers(path):
    headers = read_json(path) if path else {}
    reserved = {'host', 'content-length', 'transfer-encoding', 'connection',
                'content-type', 'accept', 'mcp-session-id', 'mcp-protocol-version'}
    if not isinstance(headers, dict):
        raise CollectionError('invalid_headers')
    seen = set()
    for name, value in headers.items():
        if (not isinstance(name, str) or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name) or
                name.lower() in reserved or name.lower() in seen or not isinstance(value, str) or
                not value or any(ord(c) < 32 or ord(c) > 126 for c in value)):
            raise CollectionError('invalid_headers')
        seen.add(name.lower())
    return headers


class Redactor:
    """Best-effort structural sanitizing; operator review remains required."""
    private_keys = {'password', 'passwd', 'secret', 'token', 'apitoken', 'apikey',
                    'authorization', 'cookie', 'setcookie', 'sessionid', 'mcpsessionid',
                    'accesstoken', 'refreshtoken', 'csrftoken', 'nextcursor', 'cursor'}

    def __init__(self, literals, *header_sets):
        self.literals = set(literals)
        for headers in header_sets:
            for value in headers.values():
                self.add(value)
                if ' ' in value:
                    self.add(value.split(' ', 1)[1])
                if ':' in value:
                    self.add(value.split(':', 1)[1])
                for cookie in value.split(';'):
                    if '=' in cookie:
                        self.add(cookie.split('=', 1)[1].strip())

    def add(self, value):
        if value:
            self.literals.add(value)

    def text(self, value):
        for literal in sorted(self.literals, key=len, reverse=True):
            value = value.replace(literal, REDACTED)
        value = re.sub(r'https?://[^\s<>"\']+', '[redacted-url]', value, flags=re.I)
        value = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '[redacted-ip]', value)
        # Cover IPv6 without treating JSON-Schema anchors as addresses.
        def ipv6(match):
            try:
                ipaddress.IPv6Address(match.group())
                return '[redacted-ip]'
            except ValueError:
                return match.group()
        value = re.sub(r'(?<![\w:])[0-9a-fA-F:]*:[0-9a-fA-F:]+(?![\w:])', ipv6, value)
        value = re.sub(r'\b[\w.-]+\.(?:internal|local|lan|corp)\b', '[redacted-host]', value, flags=re.I)
        value = re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b', REDACTED, value)
        value = re.sub(r'(?i)\b(?:bearer|password|passwd|api[_-]?key|token)\s*[=: ]\s*[^\s,;"\']+',
                       REDACTED, value)
        return value

    def clean(self, value, schema_fields=False, component_maps=False):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.clean(item) for item in value]
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                normalized = re.sub(r'[^a-z]', '', key.lower())
                # Keep field definitions (e.g. properties.password.type), not secrets.
                if not schema_fields and normalized in self.private_keys:
                    item = REDACTED
                elif not schema_fields and key in ('default', 'example', 'examples'):
                    item = (['[redacted-schema-value]'] * len(item)
                            if key == 'examples' and isinstance(item, list)
                            else '[redacted-schema-value]')
                result[self.text(key)] = self.clean(
                    item, schema_fields=(not schema_fields and key in
                                         ('properties', 'patternProperties', '$defs', 'definitions', 'dependentSchemas') or
                                         component_maps and key in ('schemas', 'securitySchemes', 'parameters',
                                                                    'headers', 'responses', 'requestBodies',
                                                                    'links', 'callbacks', 'pathItems')),
                    component_maps=(key == 'components' and not schema_fields))
            return result
        return value


class Transport:
    def __init__(self, url, headers, trace, redactor, timeout):
        self.url, self.headers, self.trace = url, headers, trace
        self.redactor, self.timeout = redactor, timeout
        self.session_id, self.protocol, self.sequence = None, None, 0
        # Do not forward secrets on redirects or inherit ambient proxy settings.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def exchange(self, url, method, headers, phase, body=None):
        request = urllib.request.Request(url, body, headers, method=method)
        try:
            response = self.opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as error:
            self.trace.append({'phase': phase, 'status': error.code,
                               'www_authenticate_present': 'WWW-Authenticate' in error.headers})
            error.close()
            raise CollectionError('http_error', status=error.code) from None
        except (OSError, ValueError, urllib.error.URLError):
            raise CollectionError('network_error') from None
        media = response.headers.get_content_type()
        self.trace.append({'phase': phase, 'status': response.status,
                           'content_type': media if media in ('application/json', 'text/event-stream') else 'other',
                           'session_header_present': 'Mcp-Session-Id' in response.headers})
        return response, media

    def rpc(self, method, params=None, notification=False):
        message = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            message['params'] = params
        if not notification:
            self.sequence += 1
            message['id'] = self.sequence
        headers = dict(self.headers, **{'Content-Type': 'application/json',
                                       'Accept': 'application/json, text/event-stream'})
        if self.session_id:
            headers['Mcp-Session-Id'] = self.session_id
        if self.protocol:
            headers['MCP-Protocol-Version'] = self.protocol
        response, media = self.exchange(self.url, 'POST', headers, method, json.dumps(message).encode())
        with response:
            session = response.headers.get('Mcp-Session-Id')
            if session:
                self.session_id = session
                self.redactor.add(session)
            if notification:
                return None
            if media == 'text/event-stream':
                payload = self.read_sse(response, message['id'])
            elif media == 'application/json':
                raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise CollectionError('response_too_large')
                payload = json.loads(raw)
            else:
                raise CollectionError('unexpected_content_type')
        if (not isinstance(payload, dict) or payload.get('jsonrpc') != '2.0' or
                type(payload.get('id')) is not int or payload['id'] != message['id'] or
                ('error' in payload) == ('result' in payload)):
            raise CollectionError('invalid_rpc_response')
        if 'error' in payload:
            error = payload['error']
            code = error.get('code') if isinstance(error, dict) else None
            raise CollectionError('rpc_error', rpc_code=code if type(code) is int else None)
        if not isinstance(payload['result'], dict):
            raise CollectionError('invalid_rpc_response')
        return payload['result']

    @staticmethod
    def read_sse(response, request_id):
        data, total = [], 0
        while True:
            raw = response.readline(MAX_BYTES + 1 - total)
            total += len(raw)
            if total >= MAX_BYTES:
                raise CollectionError('response_too_large')
            line = raw.decode('utf-8').rstrip('\r\n')
            if line.startswith('data:'):
                data.append(line[5:].removeprefix(' '))
            elif (not line or not raw) and data:
                payload = json.loads('\n'.join(data))
                data = []
                if isinstance(payload, dict) and payload.get('id') == request_id:
                    return payload
            if not raw:
                raise CollectionError('sse_without_response')

    def openapi(self, url, headers):
        response, media = self.exchange(url, 'GET', dict(headers, Accept='application/json'), 'openapi')
        with response:
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise CollectionError('response_too_large')
            if media != 'application/json':
                raise CollectionError('unexpected_content_type')
            document = json.loads(raw)
        if (not isinstance(document, dict) or not isinstance(document.get('openapi'), str) or
                not isinstance(document.get('paths'), dict)):
            raise CollectionError('invalid_openapi')
        return document


def main():
    parser = Parser(description=__doc__)
    parser.add_argument('--url', required=True, help='Exact endpoint copied from the isolated Gateway')
    parser.add_argument('--headers-file', type=Path, help='Private JSON object; no assumed vendor auth headers')
    parser.add_argument('--metadata-file', type=Path, required=True)
    parser.add_argument('--redactions-file', type=Path, help='Private JSON array of sensitive literals')
    parser.add_argument('--output', type=Path, required=True, help='New private file; existing files are never overwritten')
    parser.add_argument('--isolated-test-gateway', action='store_true', required=True)
    parser.add_argument('--protocol-version', default='2025-06-18')
    parser.add_argument('--max-pages', type=int, default=100)
    parser.add_argument('--timeout', type=float, default=15)
    parser.add_argument('--openapi-url', help='Optional exact same-origin OpenAPI URL; never guessed')
    parser.add_argument('--openapi-headers-file', type=Path, help='Separate private HTTP API credentials')
    args = parser.parse_args()
    origin = validate_url(args.url)
    if args.openapi_url and validate_url(args.openapi_url) != origin:
        raise CollectionError('openapi_origin_mismatch')
    if args.openapi_headers_file and not args.openapi_url:
        raise CollectionError('openapi_url_required')
    if not 1 <= args.max_pages <= 1000 or not 0 < args.timeout <= 60:
        raise CollectionError('invalid_limits')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', args.protocol_version):
        raise CollectionError('invalid_protocol_version')
    metadata = read_json(args.metadata_file)
    if (not isinstance(metadata, dict) or metadata.get('isolated_test_gateway') is not True or
            metadata.get('synthetic_data_only') is not True or
            metadata.get('gateway_version') not in ('8.3.9', '2027.2.0-beta1')):
        raise CollectionError('isolated_metadata_required')
    fields = {'gateway_version', 'gateway_build', 'edition', 'modules', 'license_state',
              'operating_system', 'architecture', 'model_provider_configured',
              'primitives_selection_note', 'isolated_test_gateway', 'synthetic_data_only'}
    metadata = {key: value for key, value in metadata.items() if key in fields}
    headers, api_headers = read_headers(args.headers_file), read_headers(args.openapi_headers_file)
    literals = read_json(args.redactions_file) if args.redactions_file else []
    if not isinstance(literals, list) or not all(isinstance(x, str) and x for x in literals):
        raise CollectionError('invalid_redactions')
    redactor = Redactor(literals, headers, api_headers)
    redactor.add(urllib.parse.urlsplit(args.url).hostname)
    try:
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        raise CollectionError('output_unavailable_or_exists') from None
    report = {'schema_version': 1, 'evidence_kind': 'operator-specified-endpoint-discovery',
              'observed_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'completed': False, 'environment': metadata,
              'environment_identity_source': 'operator attestation; not independently verified',
              'redaction': {'manual_review_required': True,
                            'schema_example_and_default_values_masked': True,
                            'note': 'Unknown sensitive values can remain; supply private literals and review before publishing.'},
              'endpoint': {'source': 'operator-supplied', 'location': REDACTED},
              'scope': {'tools_executed': False, 'gateway_configuration_writes': False,
                        'designer_login_attempted': False},
              'authentication': {'supplied_header_names': sorted(headers), 'initialize_accepted': False,
                                 'note': 'Acceptance does not prove credentials are required; compare an anonymous run.'},
              'mcp': {'complete': False, 'tools': [], 'pages': [], 'page_count': 0,
                      'session_header_present': False}, 'http': [], 'errors': []}
    transport = Transport(args.url, headers, report['http'], redactor, args.timeout)
    phase = 'initialize'
    try:
        initial = transport.rpc('initialize', {'protocolVersion': args.protocol_version, 'capabilities': {},
                                'clientInfo': {'name': 'ignition-harness-evidence', 'version': '0.1.0'}})
        report['mcp']['initialize'] = initial
        report['authentication']['initialize_accepted'] = True
        if initial.get('protocolVersion') != args.protocol_version:
            raise CollectionError('unsupported_negotiated_protocol')
        transport.protocol = initial['protocolVersion']
        phase = 'notifications/initialized'
        transport.rpc(phase, notification=True)
        phase = 'tools/list'
        cursor, seen = None, set()
        for index in range(1, args.max_pages + 1):
            page = transport.rpc(phase, {'cursor': cursor} if cursor is not None else {})
            tools = page.get('tools')
            if not isinstance(tools, list) or not all(isinstance(t, dict) and isinstance(t.get('name'), str)
                                                      and isinstance(t.get('inputSchema'), dict) for t in tools):
                raise CollectionError('invalid_tool_list')
            next_cursor = page.get('nextCursor')
            if next_cursor is not None and not isinstance(next_cursor, str):
                raise CollectionError('invalid_cursor')
            redactor.add(next_cursor)
            report['mcp']['tools'].extend(tools)
            report['mcp']['pages'].append({'index': index, 'tool_count': len(tools),
                                           'next_cursor_present': next_cursor is not None})
            report['mcp']['page_count'] = index
            if next_cursor is None:
                report['mcp']['complete'] = True
                break
            if next_cursor in seen:
                raise CollectionError('repeated_cursor')
            seen.add(next_cursor)
            cursor = next_cursor
        else:
            raise CollectionError('page_limit_exceeded')
        if args.openapi_url:
            phase = 'openapi'
            report['openapi'] = {'complete': False, 'supplied_header_names': sorted(api_headers)}
            report['openapi']['document'] = transport.openapi(args.openapi_url, api_headers)
            report['openapi']['complete'] = True
        report['completed'] = True
    except CollectionError as error:
        report['errors'].append(error.record(phase))
    except (ValueError, UnicodeError):
        report['errors'].append({'phase': phase, 'kind': 'invalid_response_json'})
    except (OSError, urllib.error.URLError):
        report['errors'].append({'phase': phase, 'kind': 'network_error'})
    except KeyboardInterrupt:
        report['errors'].append({'phase': phase, 'kind': 'interrupted'})
    except Exception:
        # Never print an exception containing URLs, headers or server content.
        report['errors'].append({'phase': phase, 'kind': 'unexpected_failure'})
    report['mcp']['session_header_present'] = transport.session_id is not None
    report['mcp']['tool_count'] = len(report['mcp']['tools'])
    with os.fdopen(fd, 'w') as output:
        json.dump(redactor.clean(report), output, ensure_ascii=False, indent=2)
        output.write('\n')
    print(json.dumps({'completed': report['completed'], 'page_count': report['mcp']['page_count'],
                      'tool_count': report['mcp']['tool_count'], 'tools_executed': False}))
    return 0 if report['completed'] else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except CollectionError as error:
        print('Collection rejected: ' + error.kind, file=sys.stderr)
        raise SystemExit(2) from None
    except Exception:
        print('Collection failed; private details omitted', file=sys.stderr)
        raise SystemExit(2) from None
