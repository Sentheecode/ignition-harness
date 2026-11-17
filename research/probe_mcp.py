"""Read-only Streamable HTTP MCP discovery probe (Python standard library).

Does initialize, initialized notification, and paginated tools/list only.
Optional request headers are read from a private JSON file and never recorded.
"""
import argparse
import datetime
import json
from pathlib import Path
import urllib.error
import urllib.request


class Probe:
    def __init__(self, url, headers):
        self.url = url
        self.headers = dict(headers)
        self.session_id = None
        self.sequence = 0

    def request(self, method, params=None, notification=False):
        message = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            message['params'] = params
        if not notification:
            self.sequence += 1
            message['id'] = self.sequence
        headers = dict(self.headers)
        headers.update({'Content-Type': 'application/json',
                        'Accept': 'application/json, text/event-stream'})
        if self.session_id:
            headers['Mcp-Session-Id'] = self.session_id
        request = urllib.request.Request(self.url, json.dumps(message).encode(), headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.headers.get('Mcp-Session-Id'):
                self.session_id = response.headers['Mcp-Session-Id']
            if notification:
                return None
            if 'text/event-stream' in response.headers.get('Content-Type', ''):
                data = []
                for raw in response:
                    line = raw.decode('utf-8').rstrip('\r\n')
                    if line.startswith('data:'):
                        data.append(line[5:].lstrip())
                    elif not line and data:
                        payload = json.loads('\n'.join(data))
                        data = []
                        if payload.get('id') == message['id']:
                            return payload
                raise ValueError('SSE ended without a matching JSON-RPC response')
            return json.load(response)

    def result(self, method, params=None):
        response = self.request(method, params)
        if 'error' in response:
            raise ValueError(f'{method}: JSON-RPC error code {response["error"].get("code")}')
        return response['result']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--headers-file', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    headers = json.loads(args.headers_file.read_text()) if args.headers_file else {}
    probe = Probe(args.url, headers)
    initial = probe.result('initialize', {
        'protocolVersion': '2025-06-18', 'capabilities': {},
        'clientInfo': {'name': 'ignition-harness-research', 'version': '0.0.1'},
    })
    probe.headers['MCP-Protocol-Version'] = initial['protocolVersion']
    probe.request('notifications/initialized', notification=True)
    tools = []
    cursor = None
    seen = set()
    for _ in range(100):
        page = probe.result('tools/list', {'cursor': cursor} if cursor else {})
        tools.extend(page.get('tools', []))
        cursor = page.get('nextCursor')
        if not cursor:
            break
        if cursor in seen:
            raise ValueError('Repeated tools/list cursor')
        seen.add(cursor)
    else:
        raise ValueError('tools/list exceeded 100 pages')
    evidence = {'observed_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'endpoint': args.url, 'initialize': initial,
                'session_header_present': probe.session_id is not None,
                'tool_count': len(tools), 'tools': tools,
                'scope': 'protocol discovery only; no tools executed'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
    print(f'Initialization succeeded; discovered {len(tools)} tools; no tools executed')


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as error:
        raise SystemExit(f'HTTP {error.code}; response body and authentication headers omitted')
