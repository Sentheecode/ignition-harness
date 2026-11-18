"""CLI for the thin Gateway adapter.

Discover capabilities, print the verified call for a domain operation, or execute
that call against a caller-supplied isolated endpoint. Header values are never printed.
"""

import argparse
import json
import os
from pathlib import Path
import sys

from .errors import AdapterError
from .http import MAX_BYTES
from .operations import OPERATIONS, execute, plan
from .capabilities import discover_capabilities


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise AdapterError("invalid_arguments")


def _read_json(path):
    if path is None:
        return None
    try:
        raw = Path(path).read_bytes()
    except OSError:
        raise AdapterError("invalid_private_input") from None
    if len(raw) > MAX_BYTES:
        raise AdapterError("input_too_large")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise AdapterError("invalid_private_input") from None


def _emit(result, output):
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if output is not None:
        if Path(output).exists():
            raise AdapterError("output_exists")
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
    sys.stdout.write(text)


def _exit_code(command, result):
    status = result.get("status")
    if command in {"discover", "plan"}:
        return 0
    if status in {"completed", "blocked", "unavailable", "requires_endpoint"}:
        return 0
    return 1


def _add_common(parser):
    parser.add_argument("--openapi-summary", type=Path)
    parser.add_argument("--tools-file", type=Path)
    parser.add_argument("--identity-file", type=Path)
    parser.add_argument("--redactions-file", type=Path)
    parser.add_argument("--output", type=Path)


def main(argv=None):
    parser = Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    discover = commands.add_parser("discover", description="Report capabilities from local inputs.")
    _add_common(discover)
    discover.add_argument("--mcp-endpoint-supplied", action="store_true")

    planned = commands.add_parser("plan", description="Print the verified call without contacting a Gateway.")
    _add_common(planned)
    planned.add_argument("--operation", required=True, choices=OPERATIONS)
    planned.add_argument("--args-file", type=Path)
    planned.add_argument("--mcp-url")

    ran = commands.add_parser("execute", description="Execute one planned call against a caller-supplied endpoint.")
    _add_common(ran)
    ran.add_argument("--operation", required=True, choices=OPERATIONS)
    ran.add_argument("--args-file", type=Path)
    ran.add_argument("--base-url")
    ran.add_argument("--mcp-url")
    ran.add_argument("--headers-file", type=Path)
    ran.add_argument("--timeout", type=float, default=15)
    ran.add_argument("--isolated-test-gateway", action="store_true")

    try:
        args = parser.parse_args(argv)
        if args.command == "execute" and not args.isolated_test_gateway:
            raise AdapterError("isolated_ack_required")
        if args.output is not None and args.output.exists():
            raise AdapterError("output_exists")
        openapi = _read_json(args.openapi_summary)
        tools = _read_json(args.tools_file)
        identity = _read_json(args.identity_file)
        redactions = _read_json(args.redactions_file)
        if args.command == "discover":
            result = discover_capabilities(
                openapi,
                tools,
                identity,
                mcp_endpoint_supplied=args.mcp_endpoint_supplied,
            )
        elif args.command == "plan":
            result = plan(
                args.operation,
                _read_json(args.args_file),
                openapi=openapi,
                tools=tools,
                identity=identity,
                mcp_url=args.mcp_url,
            )
        else:
            result = execute(
                args.operation,
                _read_json(args.args_file),
                openapi=openapi,
                tools=tools,
                identity=identity,
                base_url=args.base_url,
                mcp_url=args.mcp_url,
                headers=_read_json(args.headers_file),
                timeout=args.timeout,
                redactions=redactions,
                isolated=True,
            )
        if redactions and args.command != "execute":
            from .redact import Redactor

            result = Redactor(redactions).clean(result)
        _emit(result, None if args.output is None else str(args.output))
        return _exit_code(args.command, result)
    except AdapterError as error:
        payload = {"status": "rejected", "kind": error.kind}
        if error.status is not None:
            payload["http_status"] = error.status
        sys.stdout.write(json.dumps(payload) + "\n")
        return 2
    except Exception:
        sys.stdout.write(json.dumps({"status": "rejected", "kind": "unexpected_failure"}) + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
