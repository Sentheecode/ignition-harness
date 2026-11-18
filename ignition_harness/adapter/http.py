"""HTTP and MCP transports that do not follow redirects or keep secrets."""

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from .errors import AdapterError
from .redact import Redactor

MAX_BYTES = 8 * 1024 * 1024
MCP_PROTOCOL = "2025-06-18"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


def validate_url(url):
    """Accept an absolute http(s) URL with no userinfo, query, or fragment."""
    if not isinstance(url, str) or not url or any(ord(char) <= 32 for char in url):
        raise AdapterError("invalid_endpoint")
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        raise AdapterError("invalid_endpoint") from None
    host = parts.hostname
    if (
        parts.scheme not in {"http", "https"}
        or not host
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or "@" in parts.netloc
    ):
        raise AdapterError("invalid_endpoint")
    return parts


def parse_headers(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise AdapterError("invalid_headers")
    reserved = {
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "content-type",
        "accept",
        "mcp-session-id",
        "mcp-protocol-version",
    }
    seen = set()
    headers = {}
    for name, item in value.items():
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name)
            or name.lower() in reserved
            or name.lower() in seen
            or not isinstance(item, str)
            or not item
            or any(ord(char) < 32 or ord(char) > 126 for char in item)
        ):
            raise AdapterError("invalid_headers")
        seen.add(name.lower())
        headers[name] = item
    return headers


def build_url(base, path, query=None):
    parts = validate_url(base)
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        raise AdapterError("invalid_path")
    encoded = ""
    if query:
        pairs = []
        for item in query:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise AdapterError("invalid_request")
            pairs.append((str(item[0]), str(item[1])))
        encoded = urllib.parse.urlencode(pairs)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, encoded, ""))


class Transport:
    def __init__(self, timeout, redactor=None):
        self.timeout = timeout
        self.redactor = redactor or Redactor()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            NoRedirect(),
        )

    def exchange(self, url, method, headers, body=None, accept="application/json"):
        validate_url(url.split("?", 1)[0] if "?" in url else url)
        # Query strings are added by build_url for verified routes. Re-validate the origin only.
        origin = url.split("?", 1)[0]
        validate_url(origin)
        sent = dict(headers)
        sent["Accept"] = accept
        if body is not None and "Content-Type" not in sent:
            raise AdapterError("invalid_request")
        request = urllib.request.Request(url, data=body, headers=sent, method=method)
        try:
            response = self.opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            kind = "redirect_refused" if status in {301, 302, 303, 307, 308} else "http_error"
            raise AdapterError(kind, status=status) from None
        except (OSError, urllib.error.URLError, ValueError):
            raise AdapterError("network_error") from None
        try:
            self._absorb_response_secrets(response.headers)
            media = response.headers.get_content_type()
            session = response.headers.get("Mcp-Session-Id")
            if session:
                self.redactor.add(session)
            raw = response.read(MAX_BYTES + 1)
        finally:
            response.close()
        if len(raw) > MAX_BYTES:
            raise AdapterError("response_too_large")
        return {
            "status": response.status,
            "content_type": media,
            "body": raw,
            "session_header_present": session is not None,
            "session": session,
        }

    def _absorb_response_secrets(self, headers):
        for name, value in headers.items():
            lowered = name.lower()
            if any(part in lowered for part in ("cookie", "session", "token", "authorization", "csrf")):
                self.redactor.add_header_values({name: value})


def _json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def parse_sse(raw, request_id):
    data = []
    for line in raw.decode("utf-8").splitlines():
        if line.startswith("data:"):
            data.append(line[5:].removeprefix(" ").rstrip("\r"))
        elif not line and data:
            payload = json.loads("\n".join(data))
            data = []
            if isinstance(payload, dict) and payload.get("id") == request_id:
                return payload
    raise AdapterError("sse_without_response")


def decode_rpc(media, raw, request_id):
    try:
        if media == "text/event-stream":
            payload = parse_sse(raw, request_id)
        elif media == "application/json":
            payload = json.loads(raw.decode("utf-8"))
        else:
            raise AdapterError("unexpected_content_type")
    except AdapterError:
        raise
    except (UnicodeError, json.JSONDecodeError, ValueError):
        raise AdapterError("invalid_response_json") from None
    if (
        not isinstance(payload, dict)
        or payload.get("jsonrpc") != "2.0"
        or payload.get("id") != request_id
        or ("error" in payload) == ("result" in payload)
    ):
        raise AdapterError("invalid_rpc_response")
    if "error" in payload:
        code = payload["error"].get("code") if isinstance(payload["error"], dict) else None
        raise AdapterError("rpc_error", status=code if isinstance(code, int) else None)
    if not isinstance(payload["result"], dict):
        raise AdapterError("invalid_rpc_response")
    return payload["result"]


class McpLister:
    """initialize, initialized, and paginated tools/list. Never calls a tool."""

    def __init__(self, url, headers, timeout, redactor, protocol=MCP_PROTOCOL, max_pages=100):
        self.url = url
        self.headers = dict(headers)
        self.timeout = timeout
        self.redactor = redactor
        self.protocol = protocol
        self.max_pages = max_pages
        self.transport = Transport(timeout, redactor)
        self.session = None
        self.sequence = 0
        self.exchanges = []

    def _post(self, message, phase):
        headers = dict(self.headers)
        headers["Content-Type"] = "application/json"
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        if phase != "initialize":
            headers["MCP-Protocol-Version"] = self.protocol
        try:
            result = self.transport.exchange(
                self.url,
                "POST",
                headers,
                _json_bytes(message),
                accept="application/json, text/event-stream",
            )
        except AdapterError as error:
            self.exchanges.append(
                {
                    "phase": phase,
                    "method": "POST",
                    "path": urllib.parse.urlsplit(self.url).path,
                    "status": error.status,
                    "followed_redirect": False,
                    "kind": error.kind,
                }
            )
            raise
        if result["session"]:
            self.session = result["session"]
        path = urllib.parse.urlsplit(self.url).path
        self.exchanges.append(
            {
                "phase": phase,
                "method": "POST",
                "path": path,
                "status": result["status"],
                "content_type": result["content_type"]
                if result["content_type"] in {"application/json", "text/event-stream"}
                else "other",
                "session_header_present": result["session_header_present"],
                "followed_redirect": False,
            }
        )
        return result

    def list_tools(self):
        validate_url(self.url)
        self.sequence += 1
        initial_id = self.sequence
        opened = self._post(
            {
                "jsonrpc": "2.0",
                "id": initial_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": self.protocol,
                    "capabilities": {},
                    "clientInfo": {"name": "ignition-harness-adapter", "version": "0.1.0"},
                },
            },
            "initialize",
        )
        initial = decode_rpc(opened["content_type"], opened["body"], initial_id)
        if initial.get("protocolVersion") != self.protocol:
            raise AdapterError("unsupported_negotiated_protocol")
        self._post(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            "notifications/initialized",
        )
        tools = []
        cursor = None
        seen = set()
        pages = []
        complete = False
        for index in range(1, self.max_pages + 1):
            self.sequence += 1
            request_id = self.sequence
            params = {"cursor": cursor} if cursor is not None else {}
            page_response = self._post(
                {"jsonrpc": "2.0", "id": request_id, "method": "tools/list", "params": params},
                "tools/list",
            )
            page = decode_rpc(page_response["content_type"], page_response["body"], request_id)
            listed = page.get("tools")
            if not isinstance(listed, list) or not all(
                isinstance(tool, dict)
                and isinstance(tool.get("name"), str)
                and isinstance(tool.get("inputSchema"), dict)
                for tool in listed
            ):
                raise AdapterError("invalid_tool_list")
            next_cursor = page.get("nextCursor")
            if next_cursor is not None and not isinstance(next_cursor, str):
                raise AdapterError("invalid_cursor")
            self.redactor.add(next_cursor)
            tools.extend(listed)
            pages.append({"index": index, "tool_count": len(listed), "next_cursor_present": next_cursor is not None})
            if next_cursor is None:
                complete = True
                break
            if next_cursor in seen:
                raise AdapterError("repeated_cursor")
            seen.add(next_cursor)
            cursor = next_cursor
        else:
            raise AdapterError("page_limit_exceeded")
        return {
            "protocol_version": self.protocol,
            "tools": tools,
            "tool_names": [tool["name"] for tool in tools],
            "pages": pages,
            "page_count": len(pages),
            "complete": complete,
            "tools_executed": False,
            "session_header_present": self.session is not None,
            "exchanges": self.exchanges,
            "server_info_name_present": isinstance(initial.get("serverInfo"), dict),
        }
