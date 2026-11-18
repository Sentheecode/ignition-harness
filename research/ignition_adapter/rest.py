"""REST operations evidenced by PR #3 and checked against the target OpenAPI.

8.3.9 tag import uses the recorded query string and the caller's original JSON
file bytes. Beta tag read and write documents are checked against the vendored
top-level OpenAPI excerpt before they are sent. Configuration stays caller-supplied.
"""
import json
from pathlib import Path
import re
import urllib.parse
from .archive import ProjectConflict, changed_project_paths, checked_archive
from .core import MAX_BYTES, AdapterError, BETA, credentials, decode_json, encode_json

_TAG_FIELDS = json.loads(Path(__file__).with_name('beta1-tag-openapi-fields.json').read_text(encoding='utf-8'))


def validated_project(project):
    if not isinstance(project, str) or re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', project) is None:
        raise AdapterError('invalid_project')
    return project


def perspective_client_path(project):
    return '/data/perspective/client/' + urllib.parse.quote(validated_project(project), safe='')


def request_target(template, project, query=None):
    path = template.replace('{name}', urllib.parse.quote(validated_project(project), safe=''))
    if '{' in path or '}' in path:
        raise AdapterError('invalid_request_path')
    if query:
        path += '?' + urllib.parse.urlencode(query)
    return path


ROUTE_TABLE = {
    'project.create': ('POST', '/data/api/v1/projects', ('8.3.9', BETA)),
    'project.export': ('GET', '/data/api/v1/projects/export/{name}', ('8.3.9', BETA)),
    'project.importZip': ('POST', '/data/api/v1/projects/import/{name}', ('8.3.9', BETA)),
    'tag.importConfiguration': ('POST', '/data/api/v1/tags/import', ('8.3.9',)),
    'tag.exportConfiguration': ('GET', '/data/api/v1/tags/export', ('8.3.9',)),
    'tag.configure': ('POST', '/data/api/v1/tags/configuration', (BETA,)),
    'tag.readValues': ('GET', '/data/api/v1/tags/read', (BETA,)),
    'tag.writeValues': ('POST', '/data/api/v1/tags/write', (BETA,)),
}


def _provider(provider):
    if not isinstance(provider, str) or re.fullmatch(r'[A-Za-z0-9_-]{1,128}', provider) is None:
        raise AdapterError('invalid_tag_configuration')
    return provider


def _folder(path, *, required):
    if path is None and not required:
        return None
    if not isinstance(path, str) or not path or path.startswith('/') or '\\' in path:
        raise AdapterError('invalid_tag_configuration')
    if any(part in ('', '.', '..') for part in path.split('/')):
        raise AdapterError('invalid_tag_configuration')
    return path


def _collision_policy(policy):
    if policy not in ('Abort', 'MergeOverwrite'):
        raise AdapterError('invalid_tag_configuration')
    return policy


def tag_import_query(provider, path, collision_policy):
    """Recorded 8.3.9 import target. `path` is omitted for the root Abort create."""
    pairs = [('provider', _provider(provider)), ('type', 'json'),
             ('collisionPolicy', _collision_policy(collision_policy))]
    folder = _folder(path, required=False)
    if folder is not None:
        pairs.append(('path', folder))
    return pairs


def tag_export_query(provider, path):
    return [('provider', _provider(provider)), ('type', 'json'), ('path', _folder(path, required=True))]


def tag_import_bytes(document):
    """Keep the caller’s JSON file bytes. Re-encoding would no longer be that file."""
    if not isinstance(document, bytes) or not document or len(document) > MAX_BYTES:
        raise AdapterError('invalid_tag_configuration')
    try:
        parsed = json.loads(document.decode('utf-8'))
    except (UnicodeError, ValueError):
        raise AdapterError('invalid_tag_configuration') from None
    if not isinstance(parsed, (dict, list)) or not parsed:
        raise AdapterError('invalid_tag_configuration')
    return document


def project_create_document(project):
    return {'name': validated_project(project)}


def _value_matches(value, schema):
    """Match only declared JSON types. values items stay unchecked."""
    if not isinstance(schema, dict):
        return False
    declared = schema.get('type')
    if declared == 'array':
        if not isinstance(value, list):
            return False
        items = schema.get('items')
        if isinstance(items, dict) and items.get('type') == 'string':
            return all(isinstance(item, str) for item in value)
        return True
    if declared == 'string':
        return isinstance(value, str)
    if declared == 'object':
        return isinstance(value, dict)
    return True


def tag_value_document(kind, document):
    """Check a Beta read or write document. Do not rename or rebuild it."""
    spec = _TAG_FIELDS.get(kind)
    properties = spec.get('properties') if isinstance(spec, dict) else None
    required = spec.get('required') if isinstance(spec, dict) else None
    if (not isinstance(spec, dict) or spec.get('type') != 'object' or
            not isinstance(properties, dict) or not isinstance(required, list) or
            not isinstance(document, dict) or not set(required) <= set(document) or
            not set(document) <= set(properties)):
        raise AdapterError('tag_document_not_in_excerpt')
    for name, schema in properties.items():
        if name in document and not _value_matches(document[name], schema):
            raise AdapterError('tag_document_type_mismatch')
    if kind == 'write':
        paths, values = document['tagPaths'], document['values']
        if isinstance(paths, list) and isinstance(values, list) and len(paths) != len(values):
            raise AdapterError('tag_paths_values_length_mismatch')
    return document


def tag_configuration_document(document):
    """Type-check only official configuration properties that the caller included.

    The official request schema has no type, required, or additionalProperties.
    Unknown keys stay, and collisionPolicy text is not an enum.
    """
    if not isinstance(document, dict):
        return document
    properties = _TAG_FIELDS.get('configuration', {}).get('properties', {})
    for name, schema in properties.items():
        if name in document and not _value_matches(document[name], schema):
            raise AdapterError('tag_configuration_type_mismatch')
    return document


def _paths(paths):
    if not isinstance(paths, list) or not paths or not all(isinstance(path, str) and path for path in paths):
        raise AdapterError('nonempty_tag_paths_required')


class Rest:
    def __init__(self, http, version, project, headers):
        self._http = http
        self._version = version
        self._project = validated_project(project)
        self._headers = credentials(headers)
        self._document = None

    def discover(self):
        self._document = None
        raw, _ = self._http.request('GET', '/openapi.json', self._headers)
        document = decode_json(raw)
        if not isinstance(document, dict) or not isinstance(document.get('paths'), dict) or not document.get('openapi'):
            raise AdapterError('invalid_openapi')
        self._document = document
        return document

    def _call(self, method, template, *, query=None, body=None, data=None, content_type=None,
              binary=False, accept='application/json'):
        path_item = None if self._document is None else self._document['paths'].get(template)
        if not isinstance(path_item, dict) or method.lower() not in path_item:
            raise AdapterError('operation_not_discovered')
        path = request_target(template, self._project, query)
        headers = dict(self._headers)
        if body is not None:
            data = encode_json(body)
            content_type = 'application/json'
        if content_type:
            headers['Content-Type'] = content_type
        raw, _ = self._http.request(method, path, headers, data=data, accept=accept)
        return raw if binary else decode_json(raw)

    @staticmethod
    def _write_allowed(flag):
        if flag is not True:
            raise AdapterError('explicit_gateway_write_required')

    def _version_required(self, version):
        if self._version != version:
            raise AdapterError('unsupported_version_operation')

    def export_project(self):
        return checked_archive(self._call(
            'GET', '/data/api/v1/projects/export/{name}', binary=True, accept='application/zip, */*'))

    def import_project(self, archive, *, expected_current, allow_overwrite=False, disposable_project=False):
        if allow_overwrite is not True or disposable_project is not True:
            raise AdapterError('explicit_disposable_project_overwrite_required')
        checked_archive(archive)
        changes = changed_project_paths(expected_current, self.export_project())
        if changes:
            raise ProjectConflict(changes)
        result = self._call('POST', '/data/api/v1/projects/import/{name}', query=[('overwrite', 'true')],
                            data=archive, content_type='application/zip')
        if not isinstance(result, dict) or result.get('success') is not True:
            raise AdapterError('operation_failed')
        return result

    def create_project(self, *, allow_gateway_write=False):
        self._write_allowed(allow_gateway_write)
        result = self._call('POST', '/data/api/v1/projects', body=project_create_document(self._project))
        if not isinstance(result, dict) or result.get('success') is not True:
            raise AdapterError('operation_failed')
        return result

    @staticmethod
    def _config_result(result):
        if (not isinstance(result, dict) or type(result.get('failureCount')) is not int or
                result['failureCount'] != 0 or type(result.get('successCount')) is not int or
                result['successCount'] < 1):
            raise AdapterError('tag_configuration_failed')
        return result

    def import_tag_configuration(self, provider, document, *, path=None, collision_policy='Abort',
                                 allow_gateway_write=False):
        self._version_required('8.3.9')
        self._write_allowed(allow_gateway_write)
        query = tag_import_query(provider, path, collision_policy)
        result = self._call('POST', '/data/api/v1/tags/import', query=query, data=tag_import_bytes(document),
                            content_type='application/octet-stream')
        return self._config_result(result)

    def export_tag_configuration(self, provider, path):
        self._version_required('8.3.9')
        return self._call('GET', '/data/api/v1/tags/export', query=tag_export_query(provider, path))

    def configure_tags(self, document, *, allow_gateway_write=False):
        self._version_required(BETA)
        self._write_allowed(allow_gateway_write)
        tag_configuration_document(document)
        return self._config_result(self._call('POST', '/data/api/v1/tags/configuration', body=document))

    def read_values(self, document):
        self._version_required(BETA)
        tag_value_document('read', document)
        result = self._call('GET', '/data/api/v1/tags/read', body=document)
        if not isinstance(result, dict) or not isinstance(result.get('results'), list) or not result['results']:
            raise AdapterError('tag_read_failed')
        return result

    def write_values(self, document, *, expected_count, allow_gateway_write=False):
        self._version_required(BETA)
        self._write_allowed(allow_gateway_write)
        tag_value_document('write', document)
        if type(expected_count) is not int or expected_count < 1:
            raise AdapterError('tag_value_count_mismatch')
        result = self._call('POST', '/data/api/v1/tags/write', body=document)
        rows = result.get('results') if isinstance(result, dict) else None
        if (not isinstance(rows, list) or len(rows) != expected_count or
                not all(isinstance(row, dict) and row.get('code') == 192 for row in rows)):
            raise AdapterError('tag_write_not_all_good')
        return result
