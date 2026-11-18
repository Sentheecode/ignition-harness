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
                     url.path in ('', '/') and not any(ord(c) <= 32 for c in self.base_url))
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
    if (not isinstance(path, str) or not path.startswith('/') or path.startswith('//') or
            '#' in path or any(ord(c) <= 32 for c in path)):
        raise AdapterError('invalid_request_path')
    return path


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
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError):
        raise AdapterError('invalid_json_response') from None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HTTP:
    def __init__(self, target):
        self.target = target
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def request(self, method, path, headers, *, data=None, json_body=None, rpc_id=None):
        relative_path(path)
        headers = dict(headers)
        if json_body is not None:
            try:
                data = json.dumps(json_body, allow_nan=False).encode()
            except (ValueError, TypeError):
                raise AdapterError('invalid_json_request') from None
            headers['Content-Type'] = 'application/json'
        if data is not None and (not isinstance(data, bytes) or len(data) > MAX_BYTES):
            raise AdapterError('request_too_large_or_invalid')
        headers.setdefault('Accept', 'application/json')
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
                raise AdapterError('sse_without_response')
