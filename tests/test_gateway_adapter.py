"""Local fixture tests for the thin Gateway adapter. These servers are not Ignition."""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from ignition_harness.adapter import discover_capabilities, execute, plan
from ignition_harness.adapter.errors import AdapterError
from ignition_harness.adapter.tag_schema import check_tag_request, load_tag_request_schema
from ignition_harness.adapter.zipmerge import merge_project_zip

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/mac-mini-isolated"
MODULE = ROOT / "ignition_harness"
SECRET = "FixtureSecret-alpha-12345"
COOKIE = "private-cookie-value"
SESSION = "session-fixture-ABC"
CURSOR = "cursor-fixture-XYZ"

BETA = {
    "version": "2027.2.0-beta1",
    "build": "b2026110221",
    "modules": [{"id": "com.inductiveautomation.catalyst.agent"}],
    "artek_mcp_installed": False,
}
STABLE = {
    "version": "8.3.9",
    "modules": [{"id": "com.inductiveautomation.perspective"}],
    "artek_mcp_installed": False,
}
TAG = "[default]HarnessLab/Temperature"


def load(name):
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


OPENAPI_2027 = load("2027.2.0-beta1-openapi.summary.json")
OPENAPI_839 = load("8.3.9-openapi.summary.json")
TOOLS_2027 = load("2027.2.0-beta1-mcp-tools.redacted.json")


@contextlib.contextmanager
def serve(scenario="gateway", code=302, location=None):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def _handle(self, method):
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length) if length else b""
            calls.append(
                {
                    "method": method,
                    "path": self.path,
                    "headers": {key.lower(): value for key, value in self.headers.items()},
                    "body": body,
                }
            )
            if scenario == "redirect":
                self._reply(code, b"", location=location or "http://127.0.0.1/not-followed")
                return
            if scenario == "echo":
                leaked = self.headers.get("X-Fixture-Token", "")
                self._reply(
                    200,
                    {"echo": body.decode("utf-8", "replace"), "token": leaked, "cookie": COOKIE},
                    set_cookie="fixture=" + COOKIE,
                )
                return
            if scenario == "preview404" and self.path.startswith("/data/perspective/client/"):
                self._reply(404, {"message": "missing"})
                return
            if self.path.startswith("/fixture/mcp"):
                self._mcp(body)
                return
            parsed = urlsplit(self.path)
            if parsed.path == "/data/api/v1/tags/write":
                self._reply(200, {"results": [{"code": 192}]})
            elif parsed.path == "/data/api/v1/tags/read":
                self._reply(
                    200,
                    {"results": [{"value": 42.5, "quality": {"code": 192}, "timestamp": "2026-11-18T03:00:56Z"}]},
                )
            elif parsed.path == "/data/api/v1/tags/configuration":
                self._reply(200, {"successCount": 1, "failureCount": 0, "failures": []})
            elif parsed.path == "/data/api/v1/tags/import":
                self._reply(200, {"successCount": 2, "failureCount": 0, "failures": []})
            elif parsed.path == "/data/api/v1/tags/export":
                self._reply(
                    200,
                    {
                        "name": "HarnessLab",
                        "tagType": "Folder",
                        "tags": [{"name": "Temperature", "value": 21.5, "tagType": "AtomicTag"}],
                    },
                )
            elif parsed.path == "/data/api/v1/projects":
                self._reply(200, {"success": True, "changes": [{"name": "HarnessLab"}]})
            elif parsed.path.startswith("/data/api/v1/projects/import/"):
                self._reply(200, {"success": True})
            elif parsed.path.startswith("/data/perspective/client/"):
                self._reply(200, b"<html>client</html>", content_type="text/html")
            else:
                self._reply(500, {"unexpected": parsed.path})

        def _mcp(self, body):
            if scenario == "mcp-malformed":
                self._reply(200, b"{not-json", content_type="application/json")
                return
            message = json.loads(body)
            method = message["method"]
            if method == "initialize":
                self._reply(
                    200,
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "result": {
                            "protocolVersion": "2025-06-18",
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": "fixture", "version": "1"},
                        },
                    },
                    mcp_session_id=SESSION,
                )
            elif method == "notifications/initialized":
                self._reply(202, b"", content_type="application/json")
            elif method == "tools/list":
                cursor = (message.get("params") or {}).get("cursor")
                names = ["diagnostics", "realtime"] if cursor is None else ["query", "providers"]
                if scenario != "mcp-paged":
                    names = ["diagnostics", "realtime", "query", "providers"]
                tools = []
                for name in names:
                    source = next(tool for tool in TOOLS_2027["tools"] if tool["name"] == name)
                    tool = dict(source)
                    if cursor is not None:
                        tool["description"] = source.get("description", "") + " " + CURSOR
                    tools.append(tool)
                result = {"tools": tools}
                if scenario == "mcp-paged" and cursor is None:
                    result["nextCursor"] = CURSOR
                if scenario == "mcp-loop":
                    result["nextCursor"] = CURSOR
                payload = {"jsonrpc": "2.0", "id": message["id"], "result": result}
                if scenario == "mcp-sse":
                    raw = b"data: " + json.dumps(payload).encode() + b"\n\n"
                    self._reply(200, raw, content_type="text/event-stream")
                else:
                    self._reply(200, payload)
            else:
                self._reply(400, {"rejected": method})

        def _reply(self, status, body, content_type="application/json", **headers):
            if body is None:
                data = b""
            elif isinstance(body, bytes):
                data = body
            else:
                data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            for key, value in headers.items():
                self.send_header(key.replace("_", "-"), value)
            self.end_headers()
            if data:
                self.wfile.write(data)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", calls
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=5)


def query_of(path):
    return parse_qs(urlsplit(path).query, keep_blank_values=True)


class AdapterTests(unittest.TestCase):
    def test_2027_write_and_read_use_verified_rest_routes(self):
        with serve() as (base, calls):
            written = execute(
                "tag.writeValues",
                {"writes": [{"path": TAG, "value": 42.5}]},
                openapi=OPENAPI_2027,
                identity=BETA,
                base_url=base,
                headers={"X-Fixture-Token": SECRET},
                isolated=True,
            )
            read = execute(
                "tag.readValues",
                {"paths": [TAG]},
                openapi=OPENAPI_2027,
                identity=BETA,
                base_url=base,
                headers={"X-Fixture-Token": SECRET},
                isolated=True,
            )
        self.assertEqual(written["status"], "completed", written)
        self.assertEqual(read["status"], "completed", read)
        self.assertEqual(calls[0]["method"], "POST")
        self.assertEqual(urlsplit(calls[0]["path"]).path, "/data/api/v1/tags/write")
        self.assertEqual(json.loads(calls[0]["body"]), {"tagPaths": [TAG], "values": [42.5]})
        self.assertEqual(calls[0]["headers"]["content-type"], "application/json")
        self.assertTrue(written["request_schema"]["checked"])
        self.assertEqual(calls[1]["method"], "GET")
        self.assertEqual(urlsplit(calls[1]["path"]).path, "/data/api/v1/tags/read")
        self.assertEqual(json.loads(calls[1]["body"]), {"tags": [TAG]})
        self.assertTrue(read["request_schema"]["checked"])
        self.assertEqual(written["response"]["results"][0]["code"], 192)
        self.assertEqual(read["response"]["results"][0]["quality"]["code"], 192)
        self.assertEqual(read["response"]["results"][0]["value"], 42.5)
        self.assertNotIn("authorization", calls[0]["headers"])
        self.assertNotIn(SECRET, json.dumps(written))
        self.assertTrue(all("/fixture/mcp" not in call["path"] for call in calls))
        self.assertFalse(written["designer_login"])
        self.assertTrue(written["runtime_value_write"])

    def test_tag_bodies_match_the_isolated_openapi_excerpt(self):
        schema = load_tag_request_schema()
        self.assertEqual(schema["read"]["required"], ["tags"])
        self.assertEqual(schema["write"]["required"], ["tagPaths", "values"])
        self.assertEqual(schema["read"]["type"], "object")
        self.assertEqual(schema["write"]["type"], "object")
        read_body = {"tags": [TAG]}
        write_body = {"tagPaths": [TAG, "[default]HarnessLab/Other"], "values": [42.5, 21.5]}
        self.assertEqual(check_tag_request("read", read_body), read_body)
        self.assertEqual(check_tag_request("write", write_body), write_body)
        for kind, body in (
            ("read", {"paths": [TAG]}),
            ("write", [{"path": TAG, "value": 42.5}]),
            ("write", {"path": TAG, "value": 42.5}),
            ("read", {"tags": [TAG], "paths": [TAG]}),
            ("write", {"tagPaths": [TAG]}),
        ):
            with self.subTest(kind=kind, body=body):
                with self.assertRaises(AdapterError) as caught:
                    check_tag_request(kind, body)
                self.assertEqual(caught.exception.kind, "request_schema_mismatch")
        planned = plan(
            "tag.writeValues",
            {"writes": [
                {"path": TAG, "value": 42.5},
                {"path": "[default]HarnessLab/Other", "value": 21.5},
            ]},
            openapi=OPENAPI_2027,
            identity=BETA,
        )
        self.assertEqual(
            planned["calls"][0]["body"],
            {"tagPaths": [TAG, "[default]HarnessLab/Other"], "values": [42.5, 21.5]},
        )

    def test_839_import_and_export_are_configuration_routes(self):
        document = {
            "name": "HarnessLab",
            "tagType": "Folder",
            "tags": [
                {
                    "name": "Temperature",
                    "tagType": "AtomicTag",
                    "valueSource": "memory",
                    "dataType": "Float8",
                    "value": 42.5,
                    "defaultValue": 42.5,
                }
            ],
        }
        with serve() as (base, calls):
            created = execute(
                "tag.importConfiguration",
                {"collisionPolicy": "Abort", "document": document},
                openapi=OPENAPI_839,
                identity=STABLE,
                base_url=base,
                isolated=True,
            )
            restored = execute(
                "tag.importConfiguration",
                {
                    "collisionPolicy": "MergeOverwrite",
                    "path": "HarnessLab",
                    "document": {"name": "Temperature", "value": 21.5, "tagType": "AtomicTag"},
                },
                openapi=OPENAPI_839,
                identity=STABLE,
                base_url=base,
                isolated=True,
            )
            exported = execute(
                "tag.exportConfiguration",
                {"path": "HarnessLab"},
                openapi=OPENAPI_839,
                identity=STABLE,
                base_url=base,
                isolated=True,
            )
            blocked = execute(
                "tag.writeValues",
                {"writes": [{"path": TAG, "value": 42.5}]},
                openapi=OPENAPI_839,
                identity=STABLE,
                base_url=base,
                isolated=True,
            )
        self.assertEqual(created["classification"], "configuration_import")
        self.assertFalse(created["runtime_value_write"])
        self.assertEqual(created["response"]["successCount"], 2)
        created_query = query_of(calls[0]["path"])
        self.assertEqual(created_query["provider"], ["default"])
        self.assertEqual(created_query["type"], ["json"])
        self.assertEqual(created_query["collisionPolicy"], ["Abort"])
        self.assertNotIn("path", created_query)
        self.assertEqual(calls[0]["headers"]["content-type"], "application/octet-stream")
        self.assertEqual(json.loads(calls[0]["body"]), document)
        self.assertEqual(query_of(calls[1]["path"])["collisionPolicy"], ["MergeOverwrite"])
        self.assertEqual(query_of(calls[1]["path"])["path"], ["HarnessLab"])
        self.assertEqual(urlsplit(calls[2]["path"]).path, "/data/api/v1/tags/export")
        self.assertEqual(query_of(calls[2]["path"])["path"], ["HarnessLab"])
        self.assertEqual(exported["classification"], "configuration_export")
        self.assertFalse(exported["runtime_value_read"])
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["reason_code"], "runtime_write_not_verified")
        self.assertIn("/data/api/v1/tags/import", blocked["explanation"])
        self.assertIn("/data/api/v1/tags/export", blocked["explanation"])
        self.assertIn("not a verified", blocked["explanation"])
        self.assertEqual(blocked["calls"], [])
        self.assertFalse(blocked["called"])
        self.assertEqual(len(calls), 3)

    def test_839_mcp_is_blocked_and_does_not_emit_tools(self):
        with serve() as (base, calls):
            result = execute(
                "mcp.listTools",
                {},
                openapi=OPENAPI_839,
                tools=TOOLS_2027,
                identity=STABLE,
                mcp_url=base + "/mcp",
                headers={"X-Fixture-Token": SECRET},
                isolated=True,
            )
        self.assertEqual(calls, [])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason_code"], "artek_mcp_missing")
        self.assertEqual(result["dependency"], "Artek-MCP")
        self.assertIn("Artek-MCP", result["explanation"])
        self.assertIn("404", result["explanation"])
        self.assertIsNone(result["tools"])
        self.assertIsNone(result["tool_names"])
        text = json.dumps(result)
        for name in ("diagnostics", "realtime", "query", "providers"):
            self.assertNotIn(name, text)
        self.assertNotIn(SECRET, text)

    def test_capability_table_comes_from_inputs_not_the_version_string(self):
        beta = discover_capabilities(OPENAPI_2027, TOOLS_2027, BETA)
        stable = discover_capabilities(OPENAPI_839, TOOLS_2027, STABLE)
        version_only = discover_capabilities(identity=BETA)
        forged = discover_capabilities(
            {"openapi": "3.1.0", "paths": {"/data/api/v1/tags/write": {"post": {}}}},
            identity=STABLE,
        )
        write_only = discover_capabilities(
            {"openapi": "3.1.0", "paths": {"/data/api/v1/tags/write": {"post": {}}}, "path_count": 1},
            identity={"version": "2027.2.0-beta1", "build": "other-build"},
        )
        self.assertEqual(beta["openapi"]["path_count"], 696)
        self.assertEqual(beta["openapi"]["operation_count"], 809)
        self.assertEqual(stable["openapi"]["path_count"], 580)
        self.assertEqual(stable["openapi"]["operation_count"], 679)
        self.assertNotEqual(beta["openapi"]["path_count"], 455)
        self.assertNotEqual(stable["openapi"]["path_count"], 389)
        self.assertEqual(beta["operations"]["tag.writeValues"]["status"], "available")
        self.assertEqual(beta["operations"]["tag.writeValues"]["path"], "/data/api/v1/tags/write")
        self.assertEqual(
            beta["mcp_tools"]["tool_names"],
            ["diagnostics", "realtime", "query", "providers"],
        )
        tools = {tool["name"]: tool for tool in beta["mcp_tools"]["tools"]}
        self.assertEqual(set(tools), {"diagnostics", "realtime", "query", "providers"})
        self.assertEqual(tools["diagnostics"]["inputSchema"]["required"], ["path"])
        self.assertEqual(tools["realtime"]["inputSchema"]["required"], ["paths"])
        self.assertEqual(tools["query"]["inputSchema"]["required"], ["path"])
        self.assertIn("quality", tools["query"]["inputSchema"]["properties"]["filters"]["properties"])
        self.assertIn("maxResults", tools["query"]["inputSchema"]["properties"]["filters"]["properties"])
        self.assertIn("continuationPoint", tools["query"]["inputSchema"]["properties"])
        self.assertEqual(tools["providers"]["inputSchema"]["required"], [])
        self.assertNotIn("18088", json.dumps(beta))
        self.assertEqual(stable["operations"]["tag.writeValues"]["status"], "blocked")
        self.assertEqual(stable["operations"]["tag.configure"]["status"], "blocked")
        self.assertEqual(stable["operations"]["tag.importConfiguration"]["status"], "available")
        self.assertEqual(stable["operations"]["tag.importConfiguration"]["classification"], "configuration_import")
        self.assertEqual(stable["operations"]["mcp.listTools"]["status"], "blocked")
        self.assertIsNone(stable["mcp_tools"])
        self.assertEqual(stable["operations"]["preview.clientUrl"]["shell_is_live_client"], False)
        self.assertIsNone(version_only["openapi"]["path_count"])
        self.assertEqual(version_only["operations"]["tag.writeValues"]["status"], "unavailable")
        self.assertEqual(version_only["operations"]["project.create"]["status"], "unavailable")
        self.assertIsNone(version_only["mcp_tools"])
        self.assertEqual(forged["operations"]["tag.writeValues"]["status"], "blocked")
        self.assertEqual(write_only["operations"]["tag.writeValues"]["status"], "available")
        self.assertEqual(write_only["operations"]["project.create"]["status"], "unavailable")
        partial = discover_capabilities(
            tools={"tools": [TOOLS_2027["tools"][0]]},
            identity=BETA,
        )
        self.assertEqual(partial["mcp_tools"]["tool_names"], ["diagnostics"])

    def test_project_import_preserves_native_identity_files(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("project.json", b'{"title":"native"}')
            archive.writestr("global-props", b"native-props")
            archive.writestr("com.inductiveautomation.vision/global-props/resource.json", b"native-resource")
            archive.writestr("view.txt", b"old")
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            additions = Path(temporary) / "additions"
            (additions / "com.inductiveautomation.vision/global-props").mkdir(parents=True)
            (additions / "project.json").write_bytes(b'{"title":"replacement"}')
            (additions / "global-props").write_bytes(b"replacement")
            (additions / "com.inductiveautomation.vision/global-props/resource.json").write_bytes(b"replacement")
            (additions / "view.txt").write_bytes(b"new-view")
            merged = merge_project_zip(buffer.getvalue(), additions)
            with serve() as (base, calls):
                base_zip = Path(temporary) / "base.zip"
                base_zip.write_bytes(buffer.getvalue())
                result = execute(
                    "project.importZip",
                    {"name": "HarnessLab", "zip_path": str(base_zip), "additions_dir": str(additions)},
                    openapi=OPENAPI_839,
                    identity=STABLE,
                    base_url=base,
                    isolated=True,
                )
        self.assertIn("project.json", merged["preserved"])
        self.assertIn("project.json", merged["skipped_protected_additions"])
        posted = zipfile.ZipFile(io.BytesIO(calls[0]["body"]))
        self.assertEqual(posted.read("project.json"), b'{"title":"native"}')
        self.assertEqual(posted.read("global-props"), b"native-props")
        self.assertEqual(
            posted.read("com.inductiveautomation.vision/global-props/resource.json"),
            b"native-resource",
        )
        self.assertEqual(posted.read("view.txt"), b"new-view")
        self.assertEqual(urlsplit(calls[0]["path"]).path, "/data/api/v1/projects/import/HarnessLab")
        self.assertEqual(query_of(calls[0]["path"])["overwrite"], ["true"])
        self.assertEqual(calls[0]["headers"]["content-type"], "application/zip")
        self.assertEqual(result["status"], "completed")
        self.assertIn("project.json", result["calls"][0]["body"]["preserved"])

    def test_preview_uses_the_live_client_path(self):
        planned = plan("preview.clientUrl", {"project": "HarnessLab"})
        self.assertEqual(planned["live_client_path"], "/data/perspective/client/HarnessLab")
        self.assertEqual(planned["shell_path"], "/app/perspective/client/HarnessLab")
        self.assertFalse(planned["shell_is_live_client"])
        self.assertEqual(planned["calls"][0]["path"], "/data/perspective/client/HarnessLab")
        with serve() as (base, calls):
            live = execute(
                "preview.clientUrl",
                {"project": "HarnessLab"},
                base_url=base,
                isolated=True,
            )
        self.assertEqual(calls[0]["path"], "/data/perspective/client/HarnessLab")
        self.assertEqual(live["status"], "completed")
        self.assertFalse(live["body_stored"])
        with serve("preview404") as (base, calls):
            missing = execute(
                "preview.clientUrl",
                {"project": "HarnessLab"},
                base_url=base,
                isolated=True,
            )
        self.assertEqual(len(calls), 1)
        self.assertEqual(missing["http_status"], 404)
        self.assertTrue(missing["client_may_404_briefly_after_import"])
        self.assertFalse(missing["followed_redirect"])

    def test_mcp_list_uses_the_supplied_endpoint_and_does_not_call_tools(self):
        with serve("mcp-paged") as (base, calls):
            result = execute(
                "mcp.listTools",
                {},
                identity=BETA,
                mcp_url=base + "/fixture/mcp",
                headers={"X-Fixture-Token": SECRET},
                isolated=True,
            )
        methods = [json.loads(call["body"])["method"] for call in calls]
        self.assertEqual(methods, ["initialize", "notifications/initialized", "tools/list", "tools/list"])
        self.assertEqual(calls[2]["headers"].get("mcp-session-id"), SESSION)
        self.assertEqual(calls[3]["headers"].get("mcp-protocol-version"), "2025-06-18")
        self.assertEqual(json.loads(calls[3]["body"])["params"], {"cursor": CURSOR})
        self.assertEqual(result["tool_names"], ["diagnostics", "realtime", "query", "providers"])
        self.assertFalse(result["tools_executed"])
        self.assertTrue(result["mcp_complete"])
        exported = json.dumps(result)
        self.assertNotIn(SECRET, exported)
        self.assertNotIn(SESSION, exported)
        self.assertNotIn(CURSOR, exported)
        self.assertNotIn("tag_write", exported)

    def test_mcp_accepts_an_sse_page(self):
        with serve("mcp-sse") as (base, _calls):
            result = execute(
                "mcp.listTools",
                {},
                identity=BETA,
                mcp_url=base + "/fixture/mcp",
                isolated=True,
            )
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["tool_names"], ["diagnostics", "realtime", "query", "providers"])

    def test_redirect_is_not_followed_with_credentials(self):
        for code in (301, 302, 303, 307, 308):
            with self.subTest(code=code):
                with serve() as (target, target_calls):
                    with serve("redirect", code=code, location=target) as (base, calls):
                        result = execute(
                            "tag.writeValues",
                            {"writes": [{"path": TAG, "value": 42.5}]},
                            openapi=OPENAPI_2027,
                            identity=BETA,
                            base_url=base,
                            headers={"X-Fixture-Token": SECRET},
                            isolated=True,
                        )
                self.assertEqual(target_calls, [])
                self.assertEqual(len(calls), 1)
                self.assertEqual(result["http_status"], code)
                self.assertEqual(result["kind"], "redirect_refused")
                self.assertFalse(result["followed_redirect"])
                self.assertNotIn(SECRET, json.dumps(result))
                self.assertNotIn(target, json.dumps(result))

    def test_secrets_in_a_success_body_are_redacted(self):
        with serve("echo") as (base, calls):
            result = execute(
                "project.create",
                {"name": "HarnessLab"},
                openapi=OPENAPI_2027,
                identity=BETA,
                base_url=base,
                headers={"X-Fixture-Token": SECRET},
                redactions=["HarnessLab"],
                isolated=True,
            )
        self.assertEqual(calls[0]["headers"].get("x-fixture-token"), SECRET)
        exported = json.dumps(result)
        self.assertNotIn(SECRET, exported)
        self.assertNotIn(COOKIE, exported)
        self.assertNotIn("HarnessLab", exported)
        self.assertFalse(result["header_values_included"])
        self.assertFalse(result["secrets_persisted"])

    def test_no_designer_login_helper_or_endpoint(self):
        text = "\n".join(path.read_text(encoding="utf-8") for path in MODULE.rglob("*.py"))
        for banned in ("/idp/", "submit-challenge", "/data/app/login", "tools/call", "api-token/generate"):
            self.assertNotIn(banned, text)
        self.assertFalse(hasattr(sys.modules["ignition_harness.adapter"], "login"))
        self.assertFalse(hasattr(sys.modules["ignition_harness.adapter"], "designer_login"))
        with serve() as (base, calls):
            execute(
                "project.create",
                {"name": "HarnessLab"},
                openapi=OPENAPI_2027,
                identity=BETA,
                base_url=base,
                isolated=True,
            )
        self.assertEqual([urlsplit(call["path"]).path for call in calls], ["/data/api/v1/projects"])

    def test_isolated_ack_and_existing_output_do_not_touch_the_network(self):
        with serve() as (base, calls):
            denied = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ignition_harness.adapter",
                    "execute",
                    "--operation",
                    "tag.writeValues",
                    "--base-url",
                    base,
                ],
                capture_output=True,
                text=True,
                cwd=ROOT,
                timeout=15,
            )
        self.assertEqual(denied.returncode, 2, denied.stdout + denied.stderr)
        self.assertIn("isolated_ack_required", denied.stdout)
        self.assertEqual(calls, [])
        self.assertNotIn(base, denied.stdout + denied.stderr)

    def test_cli_refuses_redirects_credential_urls_and_output_overwrite(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = root / "identity.json"
            identity.write_text(json.dumps(BETA))
            openapi = root / "openapi.json"
            openapi.write_text(json.dumps(OPENAPI_2027))
            args = root / "args.json"
            args.write_text(json.dumps({"writes": [{"path": TAG, "value": 42.5}]}))
            headers = root / "headers.json"
            headers.write_text(json.dumps({"X-Fixture-Token": SECRET}))
            output = root / "out.json"
            output.write_text("previous evidence")
            (root / "stable.json").write_text(json.dumps(STABLE))
            with serve() as (target, target_calls):
                with serve("redirect", code=302, location=target) as (base, _calls):
                    redirected = self._cli(
                        "execute",
                        "--operation",
                        "tag.writeValues",
                        "--isolated-test-gateway",
                        "--base-url",
                        base,
                        "--identity-file",
                        str(identity),
                        "--openapi-summary",
                        str(openapi),
                        "--args-file",
                        str(args),
                        "--headers-file",
                        str(headers),
                    )
            self.assertEqual(redirected.returncode, 1, redirected.stdout + redirected.stderr)
            self.assertEqual(target_calls, [])
            self.assertNotIn(SECRET, redirected.stdout + redirected.stderr)
            self.assertIn("redirect_refused", redirected.stdout)
            credential = self._cli(
                "execute",
                "--operation",
                "tag.writeValues",
                "--isolated-test-gateway",
                "--base-url",
                "http://user:" + SECRET + "@127.0.0.1:9/gateway",
                "--identity-file",
                str(identity),
                "--openapi-summary",
                str(openapi),
                "--args-file",
                str(args),
            )
            self.assertEqual(credential.returncode, 2)
            self.assertNotIn(SECRET, credential.stdout + credential.stderr)
            self.assertIn("invalid_endpoint", credential.stdout)
            blocked = self._cli(
                "plan",
                "--operation",
                "mcp.listTools",
                "--identity-file",
                str(root / "stable.json"),
                "--mcp-url",
                "http://user:" + SECRET + "@127.0.0.1:9/mcp",
            )
            self.assertEqual(blocked.returncode, 0, blocked.stdout)
            self.assertIn("artek_mcp_missing", blocked.stdout)
            self.assertNotIn(SECRET, blocked.stdout + blocked.stderr)
            occupied = self._cli(
                "execute",
                "--operation",
                "tag.writeValues",
                "--isolated-test-gateway",
                "--base-url",
                "http://127.0.0.1:9",
                "--identity-file",
                str(identity),
                "--openapi-summary",
                str(openapi),
                "--args-file",
                str(args),
                "--output",
                str(output),
            )
            self.assertEqual(occupied.returncode, 2)
            self.assertEqual(output.read_text(), "previous evidence")
            self.assertIn("output_exists", occupied.stdout)

    def _cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "-m", "ignition_harness.adapter", *arguments],
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=15,
        )


if __name__ == "__main__":
    unittest.main()
