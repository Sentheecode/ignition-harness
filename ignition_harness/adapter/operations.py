"""Plan and optionally execute domain operations against verified Gateway routes."""

import hashlib
import json
from pathlib import Path
import re

from .capabilities import (
    PATH_PROJECT_IMPORT,
    PATH_PROJECTS,
    PATH_TAG_CONFIGURATION,
    PATH_TAG_EXPORT,
    PATH_TAG_IMPORT,
    PATH_TAG_READ,
    PATH_TAG_WRITE,
    PREVIEW_NOTE,
    discover_capabilities,
    has_route,
    is_839,
    load_identity,
    load_profile,
    mcp_status,
    operation_catalog,
)
from .errors import AdapterError
from .http import MAX_BYTES, MCP_PROTOCOL, McpLister, Transport, build_url, parse_headers, validate_url
from .redact import Redactor
from .zipmerge import merge_project_zip

PROJECT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,127}$")
TAG_PATH = re.compile(r"^\[[^\[\]]+\].+")
PROVIDER = re.compile(r"^[A-Za-z0-9_-]+$")
FOLDER_PATH = re.compile(r"^[A-Za-z0-9_./-]+$")

OPERATIONS = (
    "gateway.discoverCapabilities",
    "project.create",
    "project.importZip",
    "tag.configure",
    "tag.readValues",
    "tag.writeValues",
    "tag.importConfiguration",
    "tag.exportConfiguration",
    "mcp.listTools",
    "preview.clientUrl",
)


def _flags(**extra):
    result = {
        "schema_version": 1,
        "designer_login": False,
        "secrets_persisted": False,
        "header_values_included": False,
        "login_performed": False,
        "called": False,
    }
    result.update(extra)
    return result


def _args(args):
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise AdapterError("invalid_arguments")
    return args


def _unknown(args, allowed):
    if set(args) - set(allowed):
        raise AdapterError("invalid_arguments")


def _json_value(value):
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise AdapterError("invalid_arguments")
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, str) or isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float) and value == value and value not in {float("inf"), float("-inf")}:
        return value
    raise AdapterError("invalid_arguments")


def _scalar(value):
    if isinstance(value, (dict, list)):
        raise AdapterError("invalid_arguments")
    return _json_value(value)


def _tag_path(value):
    if not isinstance(value, str) or TAG_PATH.fullmatch(value) is None:
        raise AdapterError("invalid_arguments")
    return value


def _project(value):
    if not isinstance(value, str) or PROJECT_NAME.fullmatch(value) is None:
        raise AdapterError("invalid_arguments")
    return value


def _closed(operation, gate):
    result = _flags(
        operation=operation,
        transport="none",
        calls=[],
        completed=False,
        tools=None,
        tool_names=None,
    )
    result.update(gate)
    return result


def _read_bytes(path, limit):
    try:
        raw = Path(path).read_bytes()
    except OSError:
        raise AdapterError("invalid_arguments") from None
    if len(raw) > limit:
        raise AdapterError("input_too_large")
    return raw


def _prepare_zip(args):
    args = _args(args)
    _unknown(args, {"name", "zip_path", "additions_dir", "overwrite"})
    name = _project(args.get("name"))
    if args.get("overwrite", True) is not True:
        return _flags(
            operation="project.importZip",
            status="unavailable",
            transport="none",
            calls=[],
            completed=False,
            reason_code="overwrite_not_verified",
            explanation="Only project import with overwrite=true is verified.",
        ), None
    if not isinstance(args.get("zip_path"), str) or not args["zip_path"]:
        raise AdapterError("invalid_arguments")
    additions = args.get("additions_dir")
    if additions is not None and not isinstance(additions, str):
        raise AdapterError("invalid_arguments")
    merged = merge_project_zip(_read_bytes(args["zip_path"], 32 * 1024 * 1024), additions)
    call = {
        "method": "POST",
        "path": "/data/api/v1/projects/import/" + name,
        "query": [["overwrite", "true"]],
        "content_type": "application/zip",
        "accept": "application/json",
        "body_kind": "zip",
        "body": {
            "kind": "zip",
            "sha256": merged["sha256"],
            "byte_length": merged["byte_length"],
            "preserved": merged["preserved"],
            "merged_additions": merged["merged_additions"],
            "skipped_protected_additions": merged["skipped_protected_additions"],
        },
    }
    return _flags(
        operation="project.importZip",
        status="ready",
        transport="http",
        calls=[call],
        completed=False,
        preserves=["project.json", "global-props"],
        preview_note=PREVIEW_NOTE,
    ), merged["bytes"]


def _import_query(args):
    provider = args.get("provider", "default")
    if not isinstance(provider, str) or PROVIDER.fullmatch(provider) is None:
        raise AdapterError("invalid_arguments")
    if args.get("type", "json") != "json":
        raise AdapterError("invalid_arguments")
    policy = args.get("collisionPolicy")
    if policy not in {"Abort", "MergeOverwrite"}:
        raise AdapterError("invalid_arguments")
    query = [["provider", provider], ["type", "json"], ["collisionPolicy", policy]]
    if "path" in args and args["path"] is not None:
        folder = args["path"]
        if (
            not isinstance(folder, str)
            or FOLDER_PATH.fullmatch(folder) is None
            or ".." in folder.split("/")
        ):
            raise AdapterError("invalid_arguments")
        query.append(["path", folder])
    elif policy == "MergeOverwrite":
        raise AdapterError("invalid_arguments")
    return query


def _prepare_tag_import(args):
    args = _args(args)
    _unknown(args, {"provider", "type", "collisionPolicy", "path", "document", "document_path"})
    if ("document" in args) == ("document_path" in args):
        raise AdapterError("invalid_arguments")
    query = _import_query(args)
    if "document" in args:
        if not isinstance(args["document"], (dict, list)):
            raise AdapterError("invalid_arguments")
        document = _json_value(args["document"])
        raw = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        body = {"kind": "octet-stream", "json": document, "byte_length": len(raw)}
    else:
        if not isinstance(args.get("document_path"), str):
            raise AdapterError("invalid_arguments")
        raw = _read_bytes(args["document_path"], MAX_BYTES)
        try:
            parsed = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError):
            raise AdapterError("invalid_arguments") from None
        if not isinstance(parsed, (dict, list)):
            raise AdapterError("invalid_arguments")
        body = {
            "kind": "octet-stream",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "byte_length": len(raw),
        }
    call = {
        "method": "POST",
        "path": PATH_TAG_IMPORT,
        "query": query,
        "content_type": "application/octet-stream",
        "accept": "application/json",
        "body_kind": "octet-stream",
        "body": body,
    }
    return _flags(
        operation="tag.importConfiguration",
        status="ready",
        transport="http",
        classification="configuration_import",
        runtime_value_write=False,
        calls=[call],
        completed=False,
        explanation=(
            "Configuration import. The document is sent as application/octet-stream. "
            "A Memory Tag value in that document is not a verified runtime-value write."
        ),
    ), raw


def prepare(operation, args=None, *, openapi=None, tools=None, identity=None, mcp_url=None):
    """Return (public plan, optional request bytes). Bytes are never part of the public plan."""
    if operation not in OPERATIONS:
        raise AdapterError("invalid_operation")
    if operation == "mcp.listTools" and is_839(load_identity(identity)):
        profile = load_profile(openapi, tools, identity, mcp_endpoint_supplied=False)
        return _closed("mcp.listTools", mcp_status(profile)), None

    mcp_path = None
    if mcp_url:
        mcp_path = validate_url(mcp_url).path or "/"
    profile = load_profile(
        openapi,
        tools,
        identity,
        mcp_endpoint_supplied=mcp_url is not None,
    )
    if operation == "gateway.discoverCapabilities":
        report = discover_capabilities(openapi, tools, identity, mcp_url is not None)
        report["status"] = "ready"
        report["transport"] = "none"
        report["calls"] = []
        report["called"] = False
        return report, None

    catalog = operation_catalog(profile)[operation]
    if catalog["status"] != "available":
        return _closed(operation, catalog), None

    if operation == "project.create":
        args = _args(args)
        _unknown(args, {"name"})
        name = _project(args.get("name"))
        return _flags(
            operation=operation,
            status="ready",
            transport="http",
            calls=[
                {
                    "method": "POST",
                    "path": PATH_PROJECTS,
                    "query": [],
                    "content_type": "application/json",
                    "accept": "application/json",
                    "body_kind": "json",
                    "body": {"name": name},
                }
            ],
            completed=False,
        ), None

    if operation == "project.importZip":
        if not has_route(profile, PATH_PROJECT_IMPORT, "post"):
            return _closed(operation, catalog), None
        return _prepare_zip(args)

    if operation == "tag.configure":
        args = _args(args)
        _unknown(args, {"tags"})
        tags = args.get("tags")
        if not isinstance(tags, list) or not tags:
            raise AdapterError("invalid_arguments")
        body = []
        for item in tags:
            if not isinstance(item, dict):
                raise AdapterError("invalid_arguments")
            _tag_path(item.get("path"))
            body.append(_json_value(item))
        return _flags(
            operation=operation,
            status="ready",
            transport="http",
            runtime_value_write=False,
            calls=[
                {
                    "method": "POST",
                    "path": PATH_TAG_CONFIGURATION,
                    "query": [],
                    "content_type": "application/json",
                    "accept": "application/json",
                    "body_kind": "json",
                    "body": body,
                }
            ],
            completed=False,
        ), None

    if operation == "tag.readValues":
        args = _args(args)
        _unknown(args, {"paths"})
        paths = args.get("paths")
        if not isinstance(paths, list) or not paths:
            raise AdapterError("invalid_arguments")
        body = {"paths": [_tag_path(path) for path in paths]}
        return _flags(
            operation=operation,
            status="ready",
            transport="http",
            calls=[
                {
                    "method": "GET",
                    "path": PATH_TAG_READ,
                    "query": [],
                    "content_type": "application/json",
                    "accept": "application/json",
                    "body_kind": "json",
                    "body": body,
                }
            ],
            completed=False,
            body_encoding=(
                "GET with JSON body {paths}. Evidence records this route and a JSON body; "
                "the raw request document was not archived."
            ),
        ), None

    if operation == "tag.writeValues":
        args = _args(args)
        _unknown(args, {"writes"})
        writes = args.get("writes")
        if not isinstance(writes, list) or not writes:
            raise AdapterError("invalid_arguments")
        body = []
        for item in writes:
            if not isinstance(item, dict):
                raise AdapterError("invalid_arguments")
            _unknown(item, {"path", "value"})
            body.append({"path": _tag_path(item.get("path")), "value": _scalar(item.get("value"))})
        return _flags(
            operation=operation,
            status="ready",
            transport="http",
            classification="runtime_value_write",
            runtime_value_write=True,
            calls=[
                {
                    "method": "POST",
                    "path": PATH_TAG_WRITE,
                    "query": [],
                    "content_type": "application/json",
                    "accept": "application/json",
                    "body_kind": "json",
                    "body": body,
                }
            ],
            completed=False,
            body_encoding=(
                "JSON array of {path, value}. Evidence records the route, path, value, and quality code; "
                "the raw request document was not archived."
            ),
        ), None

    if operation == "tag.importConfiguration":
        return _prepare_tag_import(args)

    if operation == "tag.exportConfiguration":
        args = _args(args)
        _unknown(args, {"provider", "type", "path"})
        provider = args.get("provider", "default")
        if not isinstance(provider, str) or PROVIDER.fullmatch(provider) is None:
            raise AdapterError("invalid_arguments")
        if args.get("type", "json") != "json":
            raise AdapterError("invalid_arguments")
        folder = args.get("path")
        if not isinstance(folder, str) or FOLDER_PATH.fullmatch(folder) is None or ".." in folder.split("/"):
            raise AdapterError("invalid_arguments")
        return _flags(
            operation=operation,
            status="ready",
            transport="http",
            classification="configuration_export",
            runtime_value_read=False,
            calls=[
                {
                    "method": "GET",
                    "path": PATH_TAG_EXPORT,
                    "query": [["provider", provider], ["type", "json"], ["path", folder]],
                    "content_type": None,
                    "accept": "application/json",
                    "body_kind": "empty",
                    "body": None,
                }
            ],
            completed=False,
        ), None

    if operation == "mcp.listTools":
        protocol = MCP_PROTOCOL
        max_pages = 100
        if args:
            args = _args(args)
            _unknown(args, {"protocol_version", "max_pages"})
            if "protocol_version" in args and args["protocol_version"] != MCP_PROTOCOL:
                raise AdapterError("invalid_protocol_version")
            if "max_pages" in args:
                max_pages = args["max_pages"]
                if isinstance(max_pages, bool) or not isinstance(max_pages, int) or not 1 <= max_pages <= 1000:
                    raise AdapterError("invalid_limits")
        if not mcp_path:
            raise AdapterError("endpoint_required")
        return _flags(
            operation=operation,
            status="ready",
            transport="mcp",
            tools_executed=False,
            tools=None,
            tool_names=None,
            calls=[
                {
                    "method": "POST",
                    "path": mcp_path,
                    "rpc_method": "initialize",
                    "protocol_version": protocol,
                    "body_kind": "mcp",
                },
                {
                    "method": "POST",
                    "path": mcp_path,
                    "rpc_method": "notifications/initialized",
                    "body_kind": "mcp",
                },
                {
                    "method": "POST",
                    "path": mcp_path,
                    "rpc_method": "tools/list",
                    "paginated": True,
                    "body_kind": "mcp",
                },
            ],
            completed=False,
            max_pages=max_pages,
            note="tools/list only. Built-in Catalyst tools are not executed, and no write tool is added.",
        ), None

    if operation == "preview.clientUrl":
        args = _args(args)
        _unknown(args, {"project"})
        project = _project(args.get("project"))
        live = "/data/perspective/client/" + project
        shell = "/app/perspective/client/" + project
        return _flags(
            operation=operation,
            status="ready",
            transport="http",
            live_client_path=live,
            shell_path=shell,
            shell_is_live_client=False,
            note=PREVIEW_NOTE,
            source="verified-shared-route",
            calls=[
                {
                    "method": "GET",
                    "path": live,
                    "query": [],
                    "content_type": None,
                    "accept": "text/html, */*;q=0.1",
                    "body_kind": "empty",
                    "body": None,
                }
            ],
            completed=False,
        ), None

    raise AdapterError("invalid_operation")


def plan(operation, args=None, *, openapi=None, tools=None, identity=None, mcp_url=None):
    public, _payload = prepare(
        operation,
        args,
        openapi=openapi,
        tools=tools,
        identity=identity,
        mcp_url=mcp_url,
    )
    return public


def _run_http(public, payload, base_url, headers, timeout, redactor):
    call = public["calls"][0]
    if call["body_kind"] == "json":
        body = json.dumps(call["body"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    elif call["body_kind"] == "octet-stream":
        body = payload
    elif call["body_kind"] == "zip":
        body = payload
    elif call["body_kind"] == "empty":
        body = None
    else:
        raise AdapterError("invalid_request")
    sent = dict(headers)
    if call.get("content_type"):
        sent["Content-Type"] = call["content_type"]
    transport = Transport(timeout, redactor)
    url = build_url(base_url, call["path"], call.get("query") or None)
    try:
        response = transport.exchange(
            url,
            call["method"],
            sent,
            body,
            accept=call.get("accept") or "application/json",
        )
    except AdapterError as error:
        public["called"] = True
        public["status"] = "http_error"
        public["kind"] = error.kind
        public["http_status"] = error.status
        public["completed"] = False
        public["followed_redirect"] = False
        public["exchanges"] = [
            {
                "method": call["method"],
                "path": call["path"],
                "status": error.status,
                "followed_redirect": False,
                "kind": error.kind,
            }
        ]
        if public["operation"] == "preview.clientUrl" and error.status == 404:
            public["client_may_404_briefly_after_import"] = True
            public["note"] = PREVIEW_NOTE
        return public
    public["called"] = True
    public["http_status"] = response["status"]
    public["followed_redirect"] = False
    public["exchanges"] = [
        {
            "method": call["method"],
            "path": call["path"],
            "status": response["status"],
            "content_type": response["content_type"],
            "followed_redirect": False,
        }
    ]
    if public["operation"] == "preview.clientUrl":
        public["body_stored"] = False
        public["status"] = "completed"
        public["completed"] = True
        return public
    if response["content_type"] != "application/json":
        public["status"] = "failed"
        public["kind"] = "unexpected_content_type"
        public["completed"] = False
        public["response"] = None
        return public
    try:
        parsed = json.loads(response["body"].decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        public["status"] = "failed"
        public["kind"] = "invalid_response_json"
        public["completed"] = False
        public["response"] = None
        return public
    public["response"] = parsed
    public["status"] = "completed"
    public["completed"] = True
    return public


def _run_mcp(public, mcp_url, headers, timeout, redactor):
    max_pages = public.get("max_pages") or 100
    lister = McpLister(mcp_url, headers, timeout, redactor, max_pages=max_pages)
    try:
        listed = lister.list_tools()
    except AdapterError as error:
        public["called"] = True
        public["status"] = "http_error" if error.status else "failed"
        public["kind"] = error.kind
        public["http_status"] = error.status
        public["completed"] = False
        public["mcp_complete"] = False
        public["tools"] = None
        public["tool_names"] = None
        public["tools_executed"] = False
        public["followed_redirect"] = False
        public["exchanges"] = lister.exchanges
        return public
    public.update(
        status="completed",
        completed=True,
        called=True,
        tools_executed=False,
        mcp_complete=listed["complete"],
        tools=listed["tools"],
        tool_names=listed["tool_names"],
        tool_count=len(listed["tool_names"]),
        page_count=listed["page_count"],
        pages=listed["pages"],
        protocol_version=listed["protocol_version"],
        session_header_present=listed["session_header_present"],
        exchanges=listed["exchanges"],
        followed_redirect=False,
    )
    return public


def execute(
    operation,
    args=None,
    *,
    openapi=None,
    tools=None,
    identity=None,
    base_url=None,
    mcp_url=None,
    headers=None,
    timeout=15,
    redactions=None,
    isolated=False,
):
    if isolated is not True:
        raise AdapterError("isolated_ack_required")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < float(timeout) <= 60:
        raise AdapterError("invalid_limits")
    if redactions is None:
        literals = []
    elif not isinstance(redactions, list) or not all(isinstance(item, str) and item for item in redactions):
        raise AdapterError("invalid_redactions")
    else:
        literals = redactions
    if operation == "mcp.listTools" and is_839(load_identity(identity)):
        public, _payload = prepare(operation, args, openapi=openapi, tools=tools, identity=identity)
        public["called"] = False
        return Redactor(literals).clean(public)

    headers = parse_headers(headers)
    redactor = Redactor(literals)
    redactor.add_header_values(headers)
    if mcp_url:
        validate_url(mcp_url)
    if base_url:
        validate_url(base_url)
    public, payload = prepare(
        operation,
        args,
        openapi=openapi,
        tools=tools,
        identity=identity,
        mcp_url=mcp_url,
    )
    if public.get("status") != "ready":
        public["called"] = False
        public["completed"] = False
        return redactor.clean(public)
    if public["transport"] == "http":
        if not base_url:
            raise AdapterError("endpoint_required")
        public = _run_http(public, payload, base_url, headers, timeout, redactor)
    elif public["transport"] == "mcp":
        if not mcp_url:
            raise AdapterError("endpoint_required")
        public = _run_mcp(public, mcp_url, headers, timeout, redactor)
    else:
        public["status"] = "completed"
        public["completed"] = True
        public["called"] = False
    return redactor.clean(public)
