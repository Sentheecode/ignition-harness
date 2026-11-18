"""python -m research.ignition_adapter — manual research CLI, not a product UI."""
import argparse
import json
import sys
from pathlib import Path

from .cli import OPERATIONS, discover, execute, outside_gateway_install, plan
from .core import MAX_BYTES, AdapterError


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise AdapterError('invalid_arguments')


def _read_json(path):
    if path is None:
        return None
    try:
        raw = outside_gateway_install(path).read_bytes()
    except AdapterError:
        raise
    except OSError:
        raise AdapterError('invalid_private_input') from None
    if len(raw) > MAX_BYTES:
        raise AdapterError('input_too_large')
    try:
        return json.loads(raw.decode('utf-8'))
    except (UnicodeError, json.JSONDecodeError):
        raise AdapterError('invalid_private_input') from None


def _read_bytes(path):
    try:
        raw = outside_gateway_install(path).read_bytes()
    except AdapterError:
        raise
    except OSError:
        raise AdapterError('invalid_private_input') from None
    if not raw or len(raw) > MAX_BYTES:
        raise AdapterError('input_too_large')
    return raw


def _prepare_args(operation, args):
    if not isinstance(args, dict):
        raise AdapterError('invalid_arguments')
    if operation == 'project.importZip' and 'zip_path' in args:
        args = dict(args)
        args['zip_bytes'] = _read_bytes(args.pop('zip_path'))
    if operation == 'tag.importConfiguration' and 'document_path' in args:
        args = dict(args)
        args['document_bytes'] = _read_bytes(args.pop('document_path'))
    return args


def _emit(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')


def main(argv=None):
    parser = Parser(description='Research-only Ignition adapter. Header values are never printed.')
    commands = parser.add_subparsers(dest='command', required=True)
    discovered = commands.add_parser('discover')
    discovered.add_argument('--version', required=True)
    discovered.add_argument('--openapi-file', type=Path)
    planned = commands.add_parser('plan')
    planned.add_argument('--operation', required=True, choices=OPERATIONS)
    planned.add_argument('--version', required=True)
    planned.add_argument('--project', required=True)
    planned.add_argument('--args-file', type=Path)
    ran = commands.add_parser('execute')
    ran.add_argument('--operation', required=True, choices=OPERATIONS)
    ran.add_argument('--version', required=True)
    ran.add_argument('--project', required=True)
    ran.add_argument('--base-url')
    ran.add_argument('--headers-file', type=Path)
    ran.add_argument('--args-file', type=Path)
    ran.add_argument('--mcp-endpoint')
    ran.add_argument('--mcp-headers-file', type=Path)
    ran.add_argument('--isolated-test-gateway', action='store_true')
    try:
        args = parser.parse_args(argv)
        if args.command == 'execute' and not args.isolated_test_gateway:
            raise AdapterError('isolated_ack_required')
        if args.command == 'discover':
            result = discover(args.version, _read_json(args.openapi_file))
        elif args.command == 'plan':
            result = plan(args.operation, args.version, args.project, _read_json(args.args_file))
        else:
            if not args.base_url or args.headers_file is None:
                raise AdapterError('invalid_arguments')
            operation_args = _prepare_args(args.operation, _read_json(args.args_file) or {})
            result = execute(
                args.operation, base_url=args.base_url, version=args.version, project=args.project,
                rest_headers=_read_json(args.headers_file), args=operation_args,
                mcp_endpoint=args.mcp_endpoint, mcp_headers=_read_json(args.mcp_headers_file),
                isolated=True)
        _emit(result)
        return 0 if result.get('status') in ('ready', 'blocked', 'completed') or args.command == 'discover' else 1
    except AdapterError as error:
        payload = {'status': 'rejected', 'kind': error.reason}
        if error.status is not None:
            payload['http_status'] = error.status
        _emit(payload)
        return 2
    except Exception:
        _emit({'status': 'rejected', 'kind': 'unexpected_failure'})
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
