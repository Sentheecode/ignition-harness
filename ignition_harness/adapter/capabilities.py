"""Capability table built from supplied OpenAPI, modules, and tools/list inputs.

A version string does not turn features on. 8.3.9 runtime tag writes and
8.3.9 MCP tools/list stay fail-closed.
"""

from .errors import AdapterError

PATH_PROJECTS = "/data/api/v1/projects"
PATH_PROJECT_IMPORT = "/data/api/v1/projects/import/{name}"
PATH_TAG_CONFIGURATION = "/data/api/v1/tags/configuration"
PATH_TAG_READ = "/data/api/v1/tags/read"
PATH_TAG_WRITE = "/data/api/v1/tags/write"
PATH_TAG_IMPORT = "/data/api/v1/tags/import"
PATH_TAG_EXPORT = "/data/api/v1/tags/export"

VERIFIED_METHODS = {
    PATH_PROJECTS: ["post"],
    PATH_PROJECT_IMPORT: ["post"],
    PATH_TAG_CONFIGURATION: ["post"],
    PATH_TAG_READ: ["get"],
    PATH_TAG_WRITE: ["post"],
    PATH_TAG_IMPORT: ["post"],
    PATH_TAG_EXPORT: ["get"],
}
HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head"}

RUNTIME_WRITE_BLOCKED = (
    "8.3.9 has no verified generic runtime tag write. "
    "The verified tag path is configuration import/export only: "
    "POST /data/api/v1/tags/import and GET /data/api/v1/tags/export. "
    "Importing a Memory Tag value updates configuration and is not a "
    "verified runtime-value write API. tag.writeValues is fail-closed."
)
RUNTIME_READ_BLOCKED = (
    "8.3.9 has no verified GET /data/api/v1/tags/read runtime read. "
    "The verified readback is GET /data/api/v1/tags/export, which is a "
    "configuration export, not a runtime-value read API."
)
CONFIGURE_BLOCKED = (
    "8.3.9 does not use POST /data/api/v1/tags/configuration. "
    "Tag configuration on this version is tag.importConfiguration "
    "(POST /data/api/v1/tags/import) and tag.exportConfiguration. "
    "That import path is not a runtime-value write API."
)
MCP_BLOCKED = (
    "blocked: Artek-MCP is not installed on this 8.3.9 Gateway. "
    "Anonymous /mcp is 404. This adapter does not emit a tools/list."
)
MCP_UNVERIFIED = (
    "blocked: 8.3.9 MCP tools/list is not verified. "
    "Artek-MCP was named, but this adapter does not encode or emit an 8.3.9 tools/list."
)

PREVIEW_NOTE = (
    "GET /data/perspective/client/{project} is the live Perspective client. "
    "/app/perspective/client/{project} is only the Gateway SPA shell. "
    "After project import the live client may briefly return 404 before 200."
)


def is_839(profile):
    version = profile.get("version") or ""
    return version == "8.3.9" or version.startswith("8.3.9+") or version.startswith("8.3.9-")


def has_route(profile, path, method):
    methods = profile["openapi"]["paths"].get(path) or []
    return method in methods


def _methods_of(item):
    if isinstance(item, dict):
        found = {key.lower() for key in item if isinstance(key, str) and key.lower() in HTTP_METHODS}
        return sorted(found)
    if isinstance(item, list):
        return sorted({str(key).lower() for key in item if str(key).lower() in HTTP_METHODS})
    return []


def _optional_count(document, key):
    value = document.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def index_openapi(document):
    if document is None:
        return {
            "paths": {},
            "path_count": None,
            "operation_count": None,
            "listed_path_count": 0,
            "method_source": "none",
        }
    if not isinstance(document, dict):
        raise AdapterError("invalid_openapi")
    paths = {}
    if isinstance(document.get("paths"), dict) and (
        "openapi" in document or any(isinstance(item, (dict, list)) for item in document["paths"].values())
    ):
        for path, item in document["paths"].items():
            if not isinstance(path, str) or not path.startswith("/"):
                raise AdapterError("invalid_openapi")
            paths[path] = _methods_of(item)
        source = "openapi-document"
        path_count = _optional_count(document, "path_count")
        if path_count is None:
            path_count = len(paths)
        operation_count = _optional_count(document, "operation_count")
        if operation_count is None:
            operation_count = sum(len(methods) for methods in paths.values())
    elif "interesting_paths" in document or "path_count" in document:
        interesting = document.get("interesting_paths") or []
        if not isinstance(interesting, list) or not all(isinstance(path, str) for path in interesting):
            raise AdapterError("invalid_openapi")
        for path in interesting:
            paths[path] = list(VERIFIED_METHODS.get(path, []))
        source = "verified-known-path"
        path_count = _optional_count(document, "path_count")
        operation_count = _optional_count(document, "operation_count")
    else:
        raise AdapterError("invalid_openapi")
    return {
        "paths": paths,
        "path_count": path_count,
        "operation_count": operation_count,
        "listed_path_count": len(paths),
        "method_source": source,
    }


def load_identity(identity):
    if identity is None:
        identity = {}
    if not isinstance(identity, dict):
        raise AdapterError("invalid_identity")
    version = identity.get("version")
    build = identity.get("build")
    if version is not None and not isinstance(version, str):
        raise AdapterError("invalid_identity")
    if build is not None and not isinstance(build, str):
        raise AdapterError("invalid_identity")
    modules_in = identity.get("modules") or []
    if not isinstance(modules_in, list):
        raise AdapterError("invalid_identity")
    modules = []
    for item in modules_in:
        if isinstance(item, str) and item:
            modules.append({"id": item})
            continue
        if not isinstance(item, dict):
            raise AdapterError("invalid_identity")
        module_id = item.get("id") or item.get("name")
        if not isinstance(module_id, str) or not module_id:
            raise AdapterError("invalid_identity")
        entry = {"id": module_id}
        if item.get("version") is not None:
            if not isinstance(item["version"], str):
                raise AdapterError("invalid_identity")
            entry["version"] = item["version"]
        modules.append(entry)
    flag = identity.get("artek_mcp_installed")
    if flag is not None and not isinstance(flag, bool):
        raise AdapterError("invalid_identity")
    if flag is None:
        flag = any("artek" in entry["id"].lower() for entry in modules)
    return {
        "version": version,
        "build": build,
        "modules": modules,
        "artek_mcp_installed": flag,
    }


def load_tools(tools):
    if tools is None:
        return None
    if isinstance(tools, list):
        items = tools
    elif isinstance(tools, dict) and isinstance(tools.get("tools"), list):
        items = tools["tools"]
    else:
        raise AdapterError("invalid_tools")
    copied = []
    for tool in items:
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
            raise AdapterError("invalid_tools")
        if not isinstance(tool.get("inputSchema"), dict):
            raise AdapterError("invalid_tools")
        entry = {"name": tool["name"], "inputSchema": tool["inputSchema"]}
        for key in ("title", "description"):
            if isinstance(tool.get(key), str):
                entry[key] = tool[key]
        copied.append(entry)
    return copied


def load_profile(openapi=None, tools=None, identity=None, mcp_endpoint_supplied=False):
    loaded_identity = load_identity(identity)
    loaded_tools = load_tools(tools)
    if is_839(loaded_identity):
        # Never keep a supplied tools/list on 8.3.9. Emitting one would be a fake list.
        loaded_tools = None
    profile = {
        "version": loaded_identity["version"],
        "build": loaded_identity["build"],
        "modules": loaded_identity["modules"],
        "artek_mcp_installed": loaded_identity["artek_mcp_installed"],
        "openapi": index_openapi(openapi),
        "tools": loaded_tools,
        "mcp_endpoint_supplied": bool(mcp_endpoint_supplied),
    }
    profile["catalyst_present"] = any(
        "catalyst" in entry["id"].lower() for entry in profile["modules"]
    ) or any("catalyst" in path for path in profile["openapi"]["paths"])
    return profile


def _http_available(profile, path, method):
    if has_route(profile, path, method):
        return {
            "status": "available",
            "method": method.upper(),
            "path": path,
            "because": ["openapi"],
        }
    return {
        "status": "unavailable",
        "method": method.upper(),
        "path": path,
        "because": [f"{method.upper()} {path} is not in the supplied OpenAPI"],
        "version_is_not_sufficient": True,
    }


def mcp_status(profile):
    if is_839(profile):
        if profile["artek_mcp_installed"]:
            return {
                "status": "blocked",
                "reason_code": "artek_mcp_unverified",
                "dependency": "Artek-MCP",
                "tools": None,
                "tool_names": None,
                "explanation": MCP_UNVERIFIED,
            }
        return {
            "status": "blocked",
            "reason_code": "artek_mcp_missing",
            "dependency": "Artek-MCP",
            "anonymous_mcp_status": 404,
            "tools": None,
            "tool_names": None,
            "explanation": MCP_BLOCKED,
        }
    if profile["tools"] is not None:
        names = [tool["name"] for tool in profile["tools"]]
        return {
            "status": "discovered",
            "tool_names": names,
            "tools": profile["tools"],
            "tool_count": len(names),
            "tools_executed": False,
            "source": "caller-supplied-list",
            "note": "Tool names are copied from the supplied list. This adapter does not add tools.",
        }
    if profile["mcp_endpoint_supplied"]:
        return {
            "status": "requires_live_list",
            "tools": None,
            "tool_names": None,
            "tools_executed": False,
            "note": "Endpoint supplied. Local discovery does not call it and does not invent tools.",
        }
    return {
        "status": "requires_endpoint",
        "tools": None,
        "tool_names": None,
        "tools_executed": False,
        "note": (
            "mcp.listTools runs only when the caller supplies an MCP endpoint. "
            "This adapter does not guess a Catalyst server URL."
        ),
    }


def write_status(profile):
    if is_839(profile):
        return {
            "status": "blocked",
            "reason_code": "runtime_write_not_verified",
            "runtime_value_write": False,
            "classification": "not_a_runtime_value_write",
            "explanation": RUNTIME_WRITE_BLOCKED,
            "use_instead": ["tag.importConfiguration", "tag.exportConfiguration"],
            "because": ["verified-8.3.9-contract"],
        }
    entry = _http_available(profile, PATH_TAG_WRITE, "post")
    entry["runtime_value_write"] = entry["status"] == "available"
    entry["content_type"] = "application/json"
    if entry["status"] == "available":
        entry["classification"] = "runtime_value_write"
    return entry


def read_status(profile):
    if is_839(profile):
        return {
            "status": "blocked",
            "reason_code": "runtime_read_not_verified",
            "runtime_value_read": False,
            "explanation": RUNTIME_READ_BLOCKED,
            "use_instead": ["tag.exportConfiguration"],
            "because": ["verified-8.3.9-contract"],
        }
    entry = _http_available(profile, PATH_TAG_READ, "get")
    entry["content_type"] = "application/json"
    entry["json_body"] = True
    return entry


def configure_status(profile):
    if is_839(profile):
        return {
            "status": "blocked",
            "reason_code": "configuration_endpoint_absent",
            "explanation": CONFIGURE_BLOCKED,
            "use_instead": ["tag.importConfiguration", "tag.exportConfiguration"],
            "runtime_value_write": False,
            "because": ["verified-8.3.9-contract"],
        }
    entry = _http_available(profile, PATH_TAG_CONFIGURATION, "post")
    entry["content_type"] = "application/json"
    entry["runtime_value_write"] = False
    return entry


def import_status(profile):
    entry = _http_available(profile, PATH_TAG_IMPORT, "post")
    entry.update(
        {
            "classification": "configuration_import",
            "runtime_value_write": False,
            "content_type": "application/octet-stream",
            "query": ["provider", "type", "collisionPolicy", "path"],
            "note": (
                "Configuration import. A Memory Tag value inside the document "
                "is not a verified generic runtime-value write."
            ),
        }
    )
    return entry


def export_status(profile):
    entry = _http_available(profile, PATH_TAG_EXPORT, "get")
    entry.update(
        {
            "classification": "configuration_export",
            "runtime_value_read": False,
            "query": ["provider", "type", "path"],
        }
    )
    return entry


def operation_catalog(profile):
    mcp = mcp_status(profile)
    mcp_operation = {
        "status": "blocked" if mcp["status"] == "blocked" else (
            "requires_endpoint" if not profile["mcp_endpoint_supplied"] else "available"
        ),
        "reason_code": mcp.get("reason_code"),
        "dependency": mcp.get("dependency"),
        "explanation": mcp.get("explanation"),
        "tools": None,
        "tool_names": None,
        "tools_executed": False,
        "because": ["version-and-modules"] if is_839(profile) else ["caller-supplied-endpoint-or-list"],
    }
    if is_839(profile):
        mcp_operation["anonymous_mcp_status"] = mcp.get("anonymous_mcp_status")
    return {
        "gateway.discoverCapabilities": {
            "status": "available",
            "transport": "none",
            "because": ["local-inputs"],
        },
        "project.create": _http_available(profile, PATH_PROJECTS, "post"),
        "project.importZip": {
            **_http_available(profile, PATH_PROJECT_IMPORT, "post"),
            "query": {"overwrite": True},
            "content_type": "application/zip",
            "preserves": ["project.json", "global-props"],
        },
        "tag.configure": configure_status(profile),
        "tag.readValues": read_status(profile),
        "tag.writeValues": write_status(profile),
        "tag.importConfiguration": import_status(profile),
        "tag.exportConfiguration": export_status(profile),
        "mcp.listTools": mcp_operation,
        "preview.clientUrl": {
            "status": "available",
            "method": "GET",
            "live_client_path": "/data/perspective/client/{project}",
            "shell_path": "/app/perspective/client/{project}",
            "shell_is_live_client": False,
            "source": "verified-shared-route",
            "note": PREVIEW_NOTE,
            "because": ["verified-on-both-isolated-gateways"],
        },
    }


def discover_capabilities(openapi=None, tools=None, identity=None, mcp_endpoint_supplied=False):
    profile = load_profile(openapi, tools, identity, mcp_endpoint_supplied)
    mcp = mcp_status(profile)
    return {
        "schema_version": 1,
        "operation": "gateway.discoverCapabilities",
        "status": "completed",
        "designer_login": False,
        "secrets_persisted": False,
        "header_values_included": False,
        "login_performed": False,
        "decision_note": (
            "Capabilities come from the supplied OpenAPI, installed modules, and an optional "
            "tools list. A version string by itself does not enable project, tag, or MCP features."
        ),
        "identity": {
            "version": profile["version"],
            "build": profile["build"],
            "module_count": len(profile["modules"]),
            "artek_mcp_installed": profile["artek_mcp_installed"],
            "catalyst_present": profile["catalyst_present"],
            "source": "caller-supplied",
        },
        "openapi": {
            "path_count": profile["openapi"]["path_count"],
            "operation_count": profile["openapi"]["operation_count"],
            "listed_path_count": profile["openapi"]["listed_path_count"],
            "method_source": profile["openapi"]["method_source"],
        },
        "authentication": {
            "mode": "caller-supplied",
            "login_performed": False,
            "secrets_persisted": False,
            "mac_isolated_evidence": {
                "rest_header_names": ["Cookie", "X-CSRF-Token"],
                "catalyst_mcp_header_names": ["X-Ignition-API-Token"],
                "note": (
                    "The adapter does not perform IdP login, does not create API tokens, "
                    "and does not send header values it was not given."
                ),
            },
        },
        "operations": operation_catalog(profile),
        "mcp_tools": None
        if mcp.get("tools") is None
        else {
            "tool_names": mcp["tool_names"],
            "tool_count": mcp["tool_count"],
            "tools": mcp["tools"],
            "tools_executed": False,
            "source": mcp["source"],
        },
    }
