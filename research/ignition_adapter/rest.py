"""REST operations evidenced by PR #3 and checked against target OpenAPI."""
import urllib.parse
from .archive import checked_archive
from .core import AdapterError, BETA, credentials, decode_json


def _paths(paths):
    if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p for p in paths):
        raise AdapterError('nonempty_tag_paths_required')


class Rest:
    def __init__(self, http, version, project, headers):
        if (not isinstance(project, str) or not project or project in ('.', '..') or
                any(c in project for c in '/\\') or any(ord(c) < 32 for c in project)):
            raise AdapterError('invalid_project')
        self._http, self._version, self._project = http, version, urllib.parse.quote(project, safe='')
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

    def _call(self, method, template, *, query=None, body=None, data=None, content_type=None, binary=False):
        if self._document is None or method.lower() not in self._document['paths'].get(template, {}):
            raise AdapterError('operation_not_discovered')
        path = template.replace('{name}', self._project)
        if query is not None:
            path += '?' + urllib.parse.urlencode(query)
        headers = dict(self._headers)
        if content_type:
            headers['Content-Type'] = content_type
        raw, _ = self._http.request(method, path, headers, data=data, json_body=body)
        return raw if binary else decode_json(raw)

    @staticmethod
    def _write_allowed(flag):
        if flag is not True:
            raise AdapterError('explicit_gateway_write_required')

    def export_project(self):
        return checked_archive(self._call('GET', '/data/api/v1/projects/export/{name}', binary=True))

    def import_project(self, archive, *, allow_overwrite=False, disposable_project=False):
        if allow_overwrite is not True or disposable_project is not True:
            raise AdapterError('explicit_disposable_project_overwrite_required')
        checked_archive(archive)
        result = self._call('POST', '/data/api/v1/projects/import/{name}', query={'overwrite':'true'},
                            data=archive, content_type='application/zip')
        if not isinstance(result, dict) or result.get('success') is not True:
            raise AdapterError('operation_failed')
        return result

    def _version_required(self, version):
        if self._version != version:
            raise AdapterError('unsupported_version_operation')

    @staticmethod
    def _config_result(result):
        if (not isinstance(result, dict) or type(result.get('failureCount')) is not int or
                result['failureCount'] != 0 or type(result.get('successCount')) is not int):
            raise AdapterError('tag_configuration_failed')
        return result

    def import_tag_configuration(self, provider, path, document, *, collision_policy='Abort', allow_gateway_write=False):
        self._version_required('8.3.9')
        self._write_allowed(allow_gateway_write)
        if (collision_policy not in ('Abort','MergeOverwrite') or not isinstance(document, dict) or
                not isinstance(document.get('tags'), list)):
            raise AdapterError('invalid_tag_configuration')
        import json
        try:
            data = json.dumps(document, allow_nan=False).encode()
        except (ValueError, TypeError):
            raise AdapterError('invalid_tag_configuration') from None
        result = self._call('POST', '/data/api/v1/tags/import',
            query={'provider':provider,'type':'json','collisionPolicy':collision_policy,'path':path},
            data=data, content_type='application/octet-stream')
        return self._config_result(result)

    def export_tag_configuration(self, provider, path):
        self._version_required('8.3.9')
        return self._call('GET', '/data/api/v1/tags/export',query={'provider':provider,'type':'json','path':path})

    def configure_tags(self, provider, path, tags, *, collision_policy='MergeOverwrite', allow_gateway_write=False):
        self._version_required(BETA)
        self._write_allowed(allow_gateway_write)
        if collision_policy not in ('Abort','MergeOverwrite') or not isinstance(tags, dict):
            raise AdapterError('invalid_tag_configuration')
        return self._config_result(self._call('POST', '/data/api/v1/tags/configuration',
            body={'provider':provider,'path':path,'collisionPolicy':collision_policy,'tags':tags}))

    def read_values(self, paths):
        self._version_required(BETA)
        _paths(paths)
        return self._call('GET', '/data/api/v1/tags/read', body={'tags':paths})

    def write_values(self, paths, values, *, allow_gateway_write=False):
        self._version_required(BETA)
        self._write_allowed(allow_gateway_write)
        _paths(paths)
        if not isinstance(values, list) or len(paths) != len(values):
            raise AdapterError('tag_value_count_mismatch')
        result = self._call('POST', '/data/api/v1/tags/write', body={'tagPaths':paths,'values':values})
        rows = result.get('results') if isinstance(result, dict) else None
        if (not isinstance(rows, list) or len(rows) != len(paths) or
                not all(isinstance(r, dict) and r.get('code') == 192 for r in rows)):
            raise AdapterError('tag_write_not_all_good')
        return result
