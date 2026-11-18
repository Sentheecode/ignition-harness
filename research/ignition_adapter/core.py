"""Bounded transport for explicitly attested research loopback Gateways only."""
from dataclasses import dataclass
from enum import Enum
import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request

MAX_BYTES = 32 * 1024 * 1024
BETA = '2027.2.0-beta1'


class AdapterError(Exception):
    def __init__(self, reason, status=None):
        self.reason, self.status = reason, status
        super().__init__(reason + (f' (HTTP {status})' if status is not None else ''))


class Status(str, Enum):
    UNKNOWN = 'unknown'
    UNAVAILABLE = 'unavailable'
    BLOCKED = 'blocked'
    DISCONNECTED = 'disconnected'
    READY = 'ready'
    EXPIRED = 'expired'
    DENIED = 'denied'
    FAILED = 'failed'


@dataclass
class IdentityStates:
    engineering: Status = Status.UNAVAILABLE
    gateway_web: Status = Status.UNKNOWN
    mcp: Status = Status.DISCONNECTED
    perspective: Status = Status.UNKNOWN


@dataclass(frozen=True)
class LabTarget:
    base_url: str
    version: str
    isolated_test_gateway: bool

    def __post_init__(self):
        try:
            url = urllib.parse.urlsplit(self.base_url)
            valid = (self.isolated_test_gateway is True and self.version in ('8.3.9', BETA) and
                     url.scheme in ('http', 'https') and url.hostname in ('localhost', '127.0.0.1', '::1') and
                     url.port is not None and url.port not in (8088, 8043, 8060) and
                     url.username is None and url.password is None and not url.query and not url.fragment and
                     url.path in ('', '/') and '@' not in url.netloc and '%' not in url.netloc and
                     '\\' not in self.base_url and not any(ord(c) <= 32 for c in self.base_url))
            if not valid:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise AdapterError('isolated_loopback_target_required') from None
        object.__setattr__(self, 'base_url', self.base_url.rstrip('/'))

    def endpoint_path(self, endpoint):
        try:
            base, url = urllib.parse.urlsplit(self.base_url), urllib.parse.urlsplit(endpoint)
            if ((base.scheme, base.hostname, base.port) != (url.scheme, url.hostname, url.port) or
                    url.username is not None or url.password is not None or url.query or url.fragment):
                raise ValueError
            return relative_path(url.path)
        except (ValueError, TypeError, AttributeError):
            raise AdapterError('same_target_endpoint_required') from None


def relative_path(path):
    """Reject traversal, encoded separators, and header injection in a request target."""
    if not isinstance(path, str) or not path.startswith('/') or path.startswith('//'):
        raise AdapterError('invalid_request_path')
    if '#' in path or '\\' in path or any(ord(char) <= 32 for char in path):
        raise AdapterError('invalid_request_path')
    route, separator, query = path.partition('?')
    if separator and (not query or query.startswith('?')):
        raise AdapterError('invalid_request_path')
    segments = route.split('/')
    if any(segment == '' or '%' in segment for segment in segments[1:]):
        raise AdapterError('invalid_request_path')
    for segment in segments[1:]:
        decoded = urllib.parse.unquote(segment)
        if decoded in ('.', '..') or '/' in decoded or '\\' in decoded:
            raise AdapterError('invalid_request_path')
    return path


def opaque_header_token(value):
    """Printable session token: no CTL, space, quote, or backslash, and not echoed in errors."""
    if not isinstance(value, str) or not 1 <= len(value) <= 200:
        return False
    return all(33 <= ord(char) <= 126 and char not in '"\\' for char in value)


def encode_json(body):
    if not isinstance(body, (dict, list)) or not body:
        raise AdapterError('invalid_json_request')
    try:
        encoded = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    except (TypeError, ValueError):
        raise AdapterError('invalid_json_request') from None
    if len(encoded) > MAX_BYTES:
        raise AdapterError('request_too_large_or_invalid')
    return encoded


def credentials(headers):
    reserved = {'host', 'content-length', 'transfer-encoding', 'connection',
                'accept', 'content-type', 'mcp-session-id', 'mcp-protocol-version'}
    if not isinstance(headers, dict):
        raise AdapterError('invalid_credentials')
    result = {}
    for key, value in headers.items():
        if (not isinstance(key, str) or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key) or
                key.lower() in reserved or key.lower() in {k.lower() for k in result} or
                not isinstance(value, str) or not value or any(ord(c) < 32 or ord(c) > 126 for c in value)):
            raise AdapterError('invalid_credentials')
        result[key] = value
    return result


def decode_json(raw):
    def reject_non_finite(_value):
        raise ValueError('non-finite')

    try:
        text = raw.decode('utf-8') if isinstance(raw, (bytes, bytearray)) else raw
        return json.loads(text, parse_constant=reject_non_finite)
    except (TypeError, ValueError, UnicodeError):
        raise AdapterError('invalid_json_response') from None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def http_error_302(self, req, fp, code, msg, headers):
        raise urllib.error.HTTPError(req.full_url, code, 'redirect_refused', headers, fp)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


class HTTP:
    def __init__(self, target):
        self.target = target
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def request(self, method, path, headers, *, data=None, json_body=None, rpc_id=None,
                accept='application/json'):
        relative_path(path)
        headers = dict(headers)
        if json_body is not None:
            data = encode_json(json_body)
            headers['Content-Type'] = 'application/json'
        headers['Accept'] = accept
        if data is not None and (not isinstance(data, bytes) or len(data) > MAX_BYTES):
            raise AdapterError('request_too_large_or_invalid')
        request = urllib.request.Request(self.target.base_url + path, data=data, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=15) as response:
                response_headers = {k.lower(): v for k, v in response.headers.items()}
                if rpc_id is not None and response.headers.get_content_type() == 'text/event-stream':
                    return self._sse(response, rpc_id), response_headers
                raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise AdapterError('response_too_large')
                return raw, response_headers
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            raise AdapterError('http_error', status) from None
        except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException):
            raise AdapterError('network_error') from None

    @staticmethod
    def _sse(response, rpc_id):
        lines, size = [], 0
        while True:
            raw = response.readline(MAX_BYTES + 1 - size)
            size += len(raw)
            if size >= MAX_BYTES:
                raise AdapterError('response_too_large')
            try:
                line = raw.decode('utf-8').rstrip('\r\n')
            except UnicodeError:
                raise AdapterError('invalid_sse') from None
            if line.startswith('data:'):
                lines.append(line[5:].removeprefix(' '))
            elif not line and lines:
                payload = decode_json('\n'.join(lines))
                lines = []
                if isinstance(payload, dict) and payload.get('id') == rpc_id:
                    return json.dumps(payload).encode()
            if not raw:
                if lines:
                    payload = decode_json('\n'.join(lines))
                    if isinstance(payload, dict) and payload.get('id') == rpc_id:
                        return json.dumps(payload).encode()
                raise AdapterError('sse_without_response')
