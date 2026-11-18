"""Only the four Catalyst tool contracts captured at PR #3's pinned tip."""
import json
from pathlib import Path
from .core import AdapterError, BETA, Status, credentials, decode_json, opaque_header_token
from .rest import _paths

_SCHEMAS = json.loads(Path(__file__).with_name('catalyst_contract.json').read_text())['input_schemas']
VERIFIED_TOOLS = frozenset(_SCHEMAS)
PROTOCOL = '2025-06-18'


class Catalyst:
    def __init__(self, http, target, identities, endpoint, headers):
        self._http, self._target, self._states = http, target, identities
        self._path = target.endpoint_path(endpoint) if endpoint else None
        self._headers = credentials(headers)
        self._session_id, self._protocol, self._sequence = None, None, 0
        self._initialized, self._catalog = False, None
        if target.version != BETA:
            self._states.mcp = Status.BLOCKED

    def _supported(self):
        if self._target.version != BETA:
            raise AdapterError('839_mcp_blocked_missing_artek_evidence')
        if self._path is None:
            raise AdapterError('explicit_verified_mcp_endpoint_required')

    def _invalidate(self, state):
        self._initialized, self._catalog = False, None
        self._session_id, self._protocol = None, None
        self._states.mcp = state

    def _rpc(self, method, params=None, *, notification=False):
        self._supported()
        message = {'jsonrpc':'2.0','method':method}
        if params is not None:
            message['params'] = params
        if not notification:
            self._sequence += 1
            message['id'] = self._sequence
        headers = dict(self._headers)
        if self._session_id:
            headers['Mcp-Session-Id'] = self._session_id
        if self._protocol:
            headers['MCP-Protocol-Version'] = self._protocol
        try:
            raw, response_headers = self._http.request(
                'POST', self._path, headers, json_body=message,
                rpc_id=None if notification else message['id'],
                accept='application/json, text/event-stream')
        except AdapterError as error:
            self._invalidate(Status.EXPIRED if error.status == 404 and self._session_id is not None else
                             Status.DENIED if error.status in (401,403) else Status.FAILED)
            raise
        try:
            session = self._candidate_session(response_headers)
            if notification:
                self._notification_body(raw)
                result = None
            else:
                result = self._rpc_result(raw, message['id'])
        except AdapterError:
            # A 200 body that is not a valid protocol message must not keep READY
            # or install the session header that arrived with it.
            self._invalidate(Status.FAILED)
            raise
        if session is not None:
            self._session_id = session
        if notification:
            return None
        kind, value = result
        if kind == 'rpc_error':
            raise AdapterError('rpc_error')
        return value

    @staticmethod
    def _candidate_session(headers):
        if 'mcp-session-id' not in headers:
            return None
        session = headers.get('mcp-session-id')
        if not opaque_header_token(session):
            raise AdapterError('invalid_session_header')
        return session

    @staticmethod
    def _notification_body(raw):
        # Notifications do not require a JSON-RPC result. An empty body is enough.
        # A JSON-RPC error body is still a failure and must not be ignored.
        if not raw or not raw.strip():
            return
        payload = decode_json(raw)
        if isinstance(payload, dict) and 'error' in payload:
            raise AdapterError('rpc_error')

    @staticmethod
    def _rpc_result(raw, rpc_id):
        result = decode_json(raw)
        if (not isinstance(result, dict) or result.get('jsonrpc') != '2.0' or
                type(result.get('id')) is not int or result['id'] != rpc_id or
                ('error' in result) == ('result' in result)):
            raise AdapterError('invalid_rpc_response')
        if 'error' in result:
            return ('rpc_error', result)
        if not isinstance(result['result'], dict):
            raise AdapterError('invalid_rpc_result')
        return ('ok', result['result'])

    def initialize(self):
        self._supported()
        self._invalidate(Status.DISCONNECTED)
        try:
            initial = self._rpc('initialize', {'protocolVersion':PROTOCOL, 'capabilities':{},
                'clientInfo':{'name':'ignition-harness-research-adapter','version':'0.1.0'}})
            if initial.get('protocolVersion') != PROTOCOL:
                raise AdapterError('unsupported_negotiated_protocol')
            self._protocol = initial['protocolVersion']
            self._rpc('notifications/initialized', notification=True)
        except AdapterError:
            if self._states.mcp == Status.DISCONNECTED:
                self._invalidate(Status.FAILED)
            raise
        self._initialized = True
        self._states.mcp = Status.READY
        return initial

    def list_tools(self, *, max_pages=100):
        self._supported()
        self._catalog = None
        if not self._initialized or type(max_pages) is not int or not 1 <= max_pages <= 100:
            raise AdapterError('mcp_initialization_or_valid_page_limit_required')
        tools, seen, cursor = [], set(), None
        for _ in range(max_pages):
            page = self._rpc('tools/list', {'cursor':cursor} if cursor is not None else {})
            items = page.get('tools')
            if not isinstance(items, list) or not all(isinstance(t,dict) and isinstance(t.get('name'),str)
                                                      and isinstance(t.get('inputSchema'),dict) for t in items):
                raise AdapterError('invalid_tool_catalog')
            tools.extend(items)
            cursor = page.get('nextCursor')
            if cursor is None:
                names = [t['name'] for t in tools]
                if len(names) != len(set(names)):
                    raise AdapterError('duplicate_tool_names')
                self._catalog = {t['name']:t for t in tools}
                return tools
            if not isinstance(cursor, str) or cursor in seen:
                raise AdapterError('invalid_or_repeated_tool_cursor')
            seen.add(cursor)
        raise AdapterError('tool_page_limit_exceeded')

    def call(self, name, arguments):
        self._supported()
        if (not self._initialized or self._catalog is None or name not in VERIFIED_TOOLS or
                name not in self._catalog):
            raise AdapterError('tool_not_verified_and_discovered')
        if self._catalog[name]['inputSchema'] != _SCHEMAS[name]:
            raise AdapterError('tool_schema_not_verified')
        self._validate(name, arguments)
        result = self._rpc('tools/call', {'name':name,'arguments':arguments})
        if result.get('isError') is True:
            raise AdapterError('tool_execution_failed')
        return result

    @staticmethod
    def _validate(name, arguments):
        if not isinstance(arguments, dict):
            raise AdapterError('invalid_tool_arguments')
        allowed = {'providers':set(), 'realtime':{'paths'}, 'diagnostics':{'path'},
                   'query':{'path','filters','continuationPoint'}}[name]
        if set(arguments) - allowed:
            raise AdapterError('unverified_tool_arguments')
        if name == 'realtime':
            _paths(arguments.get('paths'))
        if name in ('query','diagnostics') and (not isinstance(arguments.get('path'),str) or not arguments['path']):
            raise AdapterError('tool_path_required')
        if name == 'query':
            filters = arguments.get('filters', {})
            if not isinstance(filters,dict) or set(filters)-{'quality','maxResults'}:
                raise AdapterError('invalid_query_filters')
            if 'quality' in filters and filters['quality'] not in ('Good','Uncertain','Bad','Error'):
                raise AdapterError('invalid_query_quality')
            if 'maxResults' in filters and (type(filters['maxResults']) is not int or not 1 <= filters['maxResults'] <= 500):
                raise AdapterError('invalid_query_limit')
            if 'continuationPoint' in arguments and not isinstance(arguments['continuationPoint'],str):
                raise AdapterError('invalid_query_continuation')

    def providers(self):
        return self.call('providers', {})

    def realtime(self, paths):
        return self.call('realtime', {'paths':paths})

    def diagnostics(self, path):
        return self.call('diagnostics', {'path':path})

    def query(self, path, *, quality=None, max_results=500, continuation_point=None):
        filters = {'maxResults':max_results}
        if quality is not None:
            filters['quality'] = quality
        arguments = {'path':path,'filters':filters}
        if continuation_point is not None:
            arguments['continuationPoint'] = continuation_point
        return self.call('query', arguments)
