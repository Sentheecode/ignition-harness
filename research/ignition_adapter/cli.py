"""Manual discover/plan/execute entry for the research adapter.

Importing this module does not open a socket. Network access happens only when
execute() is called with an explicit isolated loopback target.
"""
import hashlib
from pathlib import Path

from .core import AdapterError, BETA, LabTarget, encode_json
from .mcp import PROTOCOL, VERIFIED_TOOLS, Catalyst
from .rest import (
    ROUTE_TABLE, perspective_client_path, project_create_document, request_target,
    tag_export_query, tag_import_query, validated_project,
)
from . import ResearchAdapter

OPERATIONS = (
    'preview.clientUrl', 'project.create', 'project.export', 'project.importZip',
    'tag.importConfiguration', 'tag.exportConfiguration', 'tag.configure',
    'tag.readValues', 'tag.writeValues', 'mcp.listTools', 'mcp.call',
)
_INSTALL_ROOT = Path('/usr/local/ignition')


def redact(value, secrets):
    blocked = [item for item in secrets if isinstance(item, str) and len(item) >= 4]
    if isinstance(value, str):
        for secret in blocked:
            value = value.replace(secret, '[redacted]')
        return value
    if isinstance(value, list):
        return [redact(item, blocked) for item in value]
    if isinstance(value, dict):
        return {
            redact(key, blocked) if isinstance(key, str) else key: redact(item, blocked)
            for key, item in value.items()
        }
    return value


def outside_gateway_install(path):
    resolved = Path(path).expanduser().resolve()
    if resolved == _INSTALL_ROOT or _INSTALL_ROOT in resolved.parents:
        raise AdapterError('gateway_install_path_refused')
    return resolved


def discover(version, document=None):
    if version not in ('8.3.9', BETA):
        raise AdapterError('unsupported_version_operation')
    paths = None
    if document is not None:
        if not isinstance(document, dict) or not isinstance(document.get('paths'), dict):
            raise AdapterError('invalid_openapi')
        paths = document['paths']
    operations = {}
    for name, (method, template, versions) in ROUTE_TABLE.items():
        if version not in versions:
            operations[name] = 'blocked_by_version'
        elif paths is None:
            operations[name] = 'needs_target_openapi'
        else:
            item = paths.get(template)
            operations[name] = 'present' if isinstance(item, dict) and method.lower() in item else 'absent'
    if operations['project.export'] == 'absent':
        operations['project.importZip'] = 'absent'
    mcp_state = 'blocked_by_version' if version != BETA else 'needs_explicit_endpoint'
    operations['preview.clientUrl'] = 'url_only'
    operations['mcp.listTools'] = mcp_state
    operations['mcp.call'] = mcp_state
    return {
        'version': version,
        'network': False,
        'operations': operations,
        'identities': {
            'engineering': 'unavailable',
            'gateway_web': 'unknown',
            'mcp': 'blocked' if version != BETA else 'disconnected',
            'perspective': 'unknown',
        },
        'not_claimed': [
            'designer_login', 'artek_mcp', 'realtime_subscription',
            'database_inspector', 'atomic_project_write',
        ],
        'beta_tag_document': 'caller_supplied_json',
    }


def _args(args, allowed):
    if args is None:
        args = {}
    if not isinstance(args, dict) or set(args) - allowed:
        raise AdapterError('invalid_arguments')
    return args


def _ready(operation, version, project, calls):
    return {'operation': operation, 'version': version, 'project': validated_project(project),
            'status': 'ready', 'network': False, 'calls': calls}


def plan(operation, version, project, args=None):
    if operation not in OPERATIONS:
        raise AdapterError('invalid_operation')
    if version not in ('8.3.9', BETA):
        raise AdapterError('unsupported_version_operation')
    project = validated_project(project)
    if operation in ROUTE_TABLE and version not in ROUTE_TABLE[operation][2]:
        return {'operation': operation, 'version': version, 'project': project,
                'status': 'blocked', 'network': False, 'calls': []}
    if operation in ('mcp.listTools', 'mcp.call') and version != BETA:
        return {'operation': operation, 'version': version, 'project': project,
                'status': 'blocked', 'network': False, 'calls': []}

    if operation == 'preview.clientUrl':
        _args(args, set())
        return _ready(operation, version, project, [{
            'kind': 'url', 'path': perspective_client_path(project), 'requested': False,
        }])
    if operation == 'project.create':
        _args(args, set())
        body = project_create_document(project)
        return _ready(operation, version, project, [{
            'method': 'POST', 'path': request_target('/data/api/v1/projects', project),
            'content_type': 'application/json', 'body': body,
        }])
    if operation == 'project.export':
        _args(args, set())
        return _ready(operation, version, project, [{
            'method': 'GET', 'path': request_target('/data/api/v1/projects/export/{name}', project),
            'accept': 'application/zip, */*', 'body': None,
        }])
    if operation == 'project.importZip':
        values = _args(args, {'allow_overwrite', 'disposable_project', 'zip_path', 'zip_bytes', 'expected_path', 'expected_current'})
        if values.get('allow_overwrite') is not True or values.get('disposable_project') is not True:
            raise AdapterError('explicit_disposable_project_overwrite_required')
        if values.get('expected_path') is None and values.get('expected_current') is None:
            raise AdapterError('expected_archive_required')
        return _ready(operation, version, project, [{
            'method': 'GET', 'path': request_target('/data/api/v1/projects/export/{name}', project),
            'accept': 'application/zip, */*', 'body': None,
        }, {
            'method': 'POST',
            'path': request_target('/data/api/v1/projects/import/{name}', project, [('overwrite', 'true')]),
            'content_type': 'application/zip', 'body': 'zip-bytes',
        }])
    if operation == 'tag.importConfiguration':
        values = _args(args, {'provider', 'path', 'collision_policy', 'document_path', 'document_bytes'})
        query = tag_import_query(values.get('provider'), values.get('path'), values.get('collision_policy', 'Abort'))
        return _ready(operation, version, project, [{
            'method': 'POST', 'path': request_target('/data/api/v1/tags/import', project, query),
            'content_type': 'application/octet-stream', 'body': 'raw-json-file-bytes',
        }])
    if operation == 'tag.exportConfiguration':
        values = _args(args, {'provider', 'path'})
        query = tag_export_query(values.get('provider'), values.get('path'))
        return _ready(operation, version, project, [{
            'method': 'GET', 'path': request_target('/data/api/v1/tags/export', project, query),
            'accept': 'application/json', 'body': None,
        }])
    if operation == 'tag.configure':
        values = _args(args, {'document'})
        encode_json(values.get('document'))
        return _ready(operation, version, project, [{
            'method': 'POST', 'path': request_target('/data/api/v1/tags/configuration', project),
            'content_type': 'application/json', 'body': values['document'],
        }])
    if operation == 'tag.readValues':
        values = _args(args, {'document'})
        encode_json(values.get('document'))
        return _ready(operation, version, project, [{
            'method': 'GET', 'path': request_target('/data/api/v1/tags/read', project),
            'content_type': 'application/json', 'body': values['document'],
        }])
    if operation == 'tag.writeValues':
        values = _args(args, {'document', 'expected_count'})
        encode_json(values.get('document'))
        if type(values.get('expected_count')) is not int or values['expected_count'] < 1:
            raise AdapterError('tag_value_count_mismatch')
        return _ready(operation, version, project, [{
            'method': 'POST', 'path': request_target('/data/api/v1/tags/write', project),
            'content_type': 'application/json', 'body': values['document'],
            'expected_count': values['expected_count'],
        }])
    if operation == 'mcp.listTools':
        _args(args, set())
        return _ready(operation, version, project, [
            {'jsonrpc': 'initialize', 'protocol': PROTOCOL, 'capabilities': {}},
            {'jsonrpc': 'notifications/initialized'},
            {'jsonrpc': 'tools/list', 'pagination': True, 'tools_executed': False},
        ])
    values = _args(args, {'name', 'arguments'})
    Catalyst._validate(values.get('name'), values.get('arguments'))
    return _ready(operation, version, project, [{
        'jsonrpc': 'tools/call', 'name': values['name'], 'arguments': values['arguments'],
        'schema_checked_at_execute': True,
    }])


def _summary(operation, payload):
    return {'operation': operation, 'status': 'completed', 'network': True, 'result': payload}


def execute(operation, *, base_url, version, project, rest_headers, args=None,
            mcp_endpoint=None, mcp_headers=None, isolated=False):
    if isolated is not True:
        raise AdapterError('isolated_ack_required')
    if not isinstance(rest_headers, dict) or (mcp_headers is not None and not isinstance(mcp_headers, dict)):
        raise AdapterError('invalid_credentials')
    planned = plan(operation, version, project, args)
    target = LabTarget(base_url, version, isolated_test_gateway=True)
    adapter = ResearchAdapter(
        target, project, rest_headers=rest_headers, mcp_endpoint=mcp_endpoint, mcp_headers=mcp_headers)
    secrets = list(rest_headers.values()) + list((mcp_headers or {}).values())
    if planned['status'] != 'ready':
        return redact(planned, secrets)
    if operation == 'preview.clientUrl':
        return redact({'operation': operation, 'status': 'completed', 'network': False, 'result': {
            'url': adapter.preview_url(), 'perspective': adapter.identities.perspective.value,
        }}, secrets)
    if operation == 'project.importZip' and not all(isinstance(args.get(key), bytes)
                                                    for key in ('zip_bytes', 'expected_current')):
        raise AdapterError('invalid_arguments')
    if operation == 'tag.importConfiguration' and not isinstance((args or {}).get('document_bytes'), bytes):
        raise AdapterError('invalid_arguments')

    def finish(payload):
        session = adapter.mcp._session_id
        if session:
            secrets.append(session)
        return redact(_summary(operation, payload), secrets)

    if operation == 'mcp.listTools':
        adapter.mcp.initialize()
        tools = adapter.mcp.list_tools()
        return finish({'tool_names': [tool['name'] for tool in tools], 'tools_executed': False})
    if operation == 'mcp.call':
        adapter.mcp.initialize()
        adapter.mcp.list_tools()
        return finish(adapter.mcp.call(args['name'], args['arguments']))

    adapter.rest.discover()
    if operation == 'project.create':
        return finish(adapter.rest.create_project(allow_gateway_write=True))
    if operation == 'project.export':
        raw = adapter.rest.export_project()
        return finish({'byte_length': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    if operation == 'project.importZip':
        return finish(adapter.rest.import_project(
            args['zip_bytes'], expected_current=args['expected_current'], allow_overwrite=True, disposable_project=True))
    if operation == 'tag.importConfiguration':
        return finish(adapter.rest.import_tag_configuration(
            args.get('provider'), args.get('document_bytes'), path=args.get('path'),
            collision_policy=args.get('collision_policy', 'Abort'), allow_gateway_write=True))
    if operation == 'tag.exportConfiguration':
        return finish(adapter.rest.export_tag_configuration(args.get('provider'), args.get('path')))
    if operation == 'tag.configure':
        return finish(adapter.rest.configure_tags(args['document'], allow_gateway_write=True))
    if operation == 'tag.readValues':
        return finish(adapter.rest.read_values(args['document']))
    return finish(adapter.rest.write_values(
        args['document'], expected_count=args['expected_count'], allow_gateway_write=True))
