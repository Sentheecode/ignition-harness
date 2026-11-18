"""Protocol regression tests, never Ignition runtime evidence or existing Gateways."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
import zipfile

try:
    from research.ignition_adapter import (ResearchAdapter, LabTarget, AdapterError, Status, patch_existing_view)
except ImportError:
    ResearchAdapter = None

CONTRACT = json.loads((Path(__file__).parent/'fixtures/catalyst-beta1-contract.json').read_text())
VIEW = 'com.inductiveautomation.perspective/views/Lab/Home/view.json'


def archive(text='baseline'):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as z:
        z.writestr('project.json', '{"title":"Fixture"}')
        z.writestr('ignition/global-props/data.bin', b'fixture-opaque-bytes')
        z.writestr('unknown-module/untouched.txt', b'preserve exactly')
        z.writestr(VIEW, json.dumps({'root': {'props': {'text': text}}}))
        z.writestr(VIEW.replace('view.json', 'resource.json'), '{"files":["view.json"]}')
    return data.getvalue()


@contextlib.contextmanager
def fixture_server(mode='ok'):
    calls, current = [], {'zip': archive()}
    routes = {'/data/api/v1/projects': {'post': {}},
              '/data/api/v1/projects/export/{name}': {'get': {}},
              '/data/api/v1/projects/import/{name}': {'post': {}},
              '/data/api/v1/tags/import': {'post': {}}, '/data/api/v1/tags/export': {'get': {}},
              '/data/api/v1/tags/configuration': {'post': {}},
              '/data/api/v1/tags/read': {'get': {}}, '/data/api/v1/tags/write': {'post': {}}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, body=b'', content_type='application/json', **headers):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            for key, value in headers.items():
                self.send_header(key.replace('_','-'),value)
            self.end_headers()
            self.wfile.write(body if isinstance(body, bytes) else json.dumps(body).encode())

        def dispatch(self):
            raw = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            calls.append({'method': self.command, 'path': self.path, 'headers': dict(self.headers), 'body': raw})
            path = self.path.split('?')[0]
            if mode == 'malformed-status':
                self.wfile.write(b'private-server-response Cookie=secret-value\r\n\r\n')
                return
            if mode == 'redirect':
                return self.reply(302, Location='http://127.0.0.1:9/stolen-secret-location')
            if mode == 'redirect-post' and self.command == 'POST':
                return self.reply(307, Location='http://127.0.0.1:9/stolen-secret-location')
            if mode == 'denied':
                return self.reply(403, b'private-server-response Cookie=secret-value')
            if path == '/data/api/v1/projects' and self.command == 'POST':
                posted = json.loads(raw)
                if mode == 'create-fails' or posted.get('name') != 'FixtureProject':
                    return self.reply(200, {'success': False, 'problem': {'message': 'private-server-response'}})
                return self.reply(200, {'success': True, 'changes': [{'name': 'FixtureProject'}]})
            if path == '/openapi.json':
                paths = {} if mode == 'missing-routes' else routes
                return self.reply(200, {'openapi':'3.1.0','info':{'title':'Fixture','version':'1'},'paths':paths})
            if path.startswith('/data/api/v1/projects/export/'):
                return self.reply(200, current['zip'], 'application/zip')
            if path.startswith('/data/api/v1/projects/import/'):
                if mode == 'import-fails':
                    return self.reply(200, {'success':False,'problem':{'message':'private-server-response'}})
                current['zip']=raw
                return self.reply(200, {'success':True,'changes':[{'name':'FixtureProject'}]})
            if path == '/data/api/v1/tags/read':
                return self.reply(200, current.get('read_body', {'results':[{'value':42.5,'quality':{'code':192}}]}))
            if path == '/data/api/v1/tags/write':
                if mode == 'nested-quality':
                    return self.reply(200, {'results': [{'quality': {'code': 192}}]})
                if 'write_body' in current:
                    return self.reply(200, current['write_body'])
                return self.reply(200, {'results':[{'code':192 if mode!='bad-quality' else 0}]})
            if path in ('/data/api/v1/tags/configuration','/data/api/v1/tags/import'):
                return self.reply(200, {'successCount':1,'failureCount':0 if mode!='partial-config' else 1,'failures':[]})
            if path == '/data/api/v1/tags/export':
                body = {'name':'Fixture','tagType':'Folder','tags':[]}
                if mode == 'echo-secret':
                    body['leak'] = self.headers.get('Cookie')
                return self.reply(200, body, 'application/octet-stream')
            if path == '/data/catalyst-agent/mcp-servers/HarnessLab':
                message=json.loads(raw)
                if mode == 'mcp-missing':return self.reply(404)
                if mode == 'expired' and message['method']!='initialize':
                    return self.reply(404)
                if message['method']=='initialize':
                    session = 'bad session' if mode == 'bad-session' else 'fixture-session-secret'
                    return self.reply(200, {'jsonrpc':'2.0','id':message['id'],'result':CONTRACT['initialize']},Mcp_Session_Id=session)
                if message['method']=='notifications/initialized':
                    if mode == 'notify-error':
                        return self.reply(200, {'jsonrpc':'2.0','error':{'code':-32000,'message':'private-server-response'}})
                    if mode == 'notify-benign':
                        return self.reply(200, {'jsonrpc':'2.0'})
                    return self.reply(202)
                if message['method']=='tools/list':
                    cursor=message['params'].get('cursor')
                    if cursor is None:
                        result={'tools':CONTRACT['tools'][:2],'nextCursor':'fixture-cursor'}
                    else:
                        result={'tools':copy.deepcopy(CONTRACT['tools'][2:])}
                        if mode=='changed-schema':
                            result['tools'][-1]['inputSchema']['required']=['unverified_new_argument']
                    if mode == 'loop':result['nextCursor']='fixture-cursor'
                else:
                    if mode == 'poison-json':
                        body=b'{"jsonrpc":"2.0","id":'+str(message['id']).encode()+b',"result":{"private-server-response"'
                        self.send_response(200)
                        self.send_header('Content-Type','application/json')
                        self.send_header('Content-Length',str(len(body)))
                        self.send_header('Mcp-Session-Id','poison-session-id')
                        self.end_headers();self.wfile.write(body);return
                    if mode == 'dual-rpc':
                        return self.reply(200, {'jsonrpc':'2.0','id':message['id'],'result':{'isError':False},
                                                'error':{'code':-32000,'message':'private-server-response'}},
                                          Mcp_Session_Id='after-dual-fields')
                    if mode == 'string-id':
                        return self.reply(200, {'jsonrpc':'2.0','id':str(message['id']),'result':{'isError':False}},
                                          Mcp_Session_Id='id-type-mismatch')
                    if mode == 'nan-result':
                        body=('{"jsonrpc":"2.0","id":%d,"result":{"isError":false,"structuredContent":{"value":NaN,"inf":Infinity},"leak":"private-server-response"}}'%message['id']).encode()
                        self.send_response(200)
                        self.send_header('Content-Type','application/json')
                        self.send_header('Content-Length',str(len(body)))
                        self.send_header('Mcp-Session-Id','nan-session')
                        self.end_headers();self.wfile.write(body);return
                    if mode == 'tool-error':result={'isError':True,'content':[{'type':'text','text':'private-server-response'}]}
                    else:result={'isError':False,'structuredContent':{'fixture':True}}
                payload={'jsonrpc':'2.0','id':message['id'],'result':result}
                if message['method']=='tools/list' and cursor is not None:
                    return self.reply(200, ('data: '+json.dumps(payload)+'\n\n').encode(),'text/event-stream')
                return self.reply(200, payload)
            return self.reply(404)

        do_GET=dispatch
        do_POST=dispatch

    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        yield 'http://127.0.0.1:'+str(server.server_port),calls,current
    finally:
        server.shutdown();server.server_close();thread.join()


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(ResearchAdapter, 'Research thin adapter has not been implemented')

    def adapter(self, base, version='2027.2.0-beta1'):
        return ResearchAdapter(LabTarget(base,version,isolated_test_gateway=True), 'FixtureProject',
            rest_headers={'Cookie':'web-fixture-secret','X-CSRF-Token':'csrf-fixture-secret'},
            mcp_endpoint=base+'/data/catalyst-agent/mcp-servers/HarnessLab',
            mcp_headers={'X-Ignition-API-Token':'Fixture:token-fixture-secret'})

    def test_production_port_and_nonisolated_targets_rejected_without_network(self):
        rejected = [
            ('http://127.0.0.1:8088', True), ('http://127.0.0.1:08088', True),
            ('http://127.0.0.1:8043', True), ('http://[::1]:8060', True),
            ('http://example.com:18088', True), ('http://127.0.0.1:18088', False),
            ('http://127.0.0.1:18088', 1), ('http://@127.0.0.1:18088', True),
            ('http://127.0.0.1:18088\\@evil.com/', True), ('http://127.1:18088', True),
        ]
        for base, flag in rejected:
            with self.subTest(base=base, flag=flag), self.assertRaises(AdapterError):
                LabTarget(base, '2027.2.0-beta1', isolated_test_gateway=flag)

    def test_openapi_is_required_and_missing_routes_are_not_invented(self):
        with fixture_server('missing-routes') as (base,calls,_):
            a=self.adapter(base)
            with self.assertRaises(AdapterError):a.rest.export_project()
            self.assertEqual(calls,[])
            a.rest.discover()
            with self.assertRaises(AdapterError):a.rest.export_project()
            self.assertEqual([x['path'] for x in calls],['/openapi.json'])

    def test_both_versions_export_import_readback_and_explicit_restore_preserve_archive(self):
        for version in ['8.3.9','2027.2.0-beta1']:
            with self.subTest(version=version),fixture_server() as (base,calls,_):
                a=self.adapter(base,version);a.rest.discover();original=a.rest.export_project()
                changed=patch_existing_view(original,VIEW,{'root':{'props':{'text':'changed'}}})
                with zipfile.ZipFile(io.BytesIO(changed)) as z:
                    self.assertEqual(z.read('unknown-module/untouched.txt'),b'preserve exactly')
                    self.assertEqual(z.read('ignition/global-props/data.bin'),b'fixture-opaque-bytes')
                a.rest.import_project(changed,expected_current=original,allow_overwrite=True,disposable_project=True)
                self.assertEqual(a.rest.export_project(),changed)
                a.rest.import_project(original,expected_current=changed,allow_overwrite=True,disposable_project=True)
                self.assertEqual(a.rest.export_project(),original)
                self.assertEqual(calls[1]['headers']['Accept'],'application/zip, */*')
                self.assertEqual(calls[3]['path'],'/data/api/v1/projects/import/FixtureProject?overwrite=true')
                self.assertEqual(calls[3]['headers']['Content-Type'],'application/zip')
                self.assertEqual(calls[3]['body'],changed)
                self.assertFalse(a.capabilities['atomic_project_write'])
                self.assertEqual(a.identities.perspective,Status.UNKNOWN)

    def test_stale_write_and_restore_never_post(self):
        from research.ignition_adapter import ProjectConflict
        script = 'ignition/script-python/Test/code.py'
        for version in ['8.3.9', '2027.2.0-beta1']:
            for restore in [False, True]:
                with self.subTest(version=version, restore=restore), fixture_server() as (base, calls, current):
                    rest = self.adapter(base, version).rest
                    rest.discover()
                    baseline = rest.export_project()
                    changed = patch_existing_view(baseline, VIEW, {'text': 'changed'})
                    expected, desired = baseline, changed
                    flags = dict(allow_overwrite=True, disposable_project=True)
                    if restore:
                        rest.import_project(changed, expected_current=baseline, **flags)
                        expected, desired = rest.export_project(), baseline
                    edited = io.BytesIO(expected)
                    with zipfile.ZipFile(edited, 'a') as zipped:
                        zipped.writestr(script, 'edited by another user')
                    current['zip'] = edited.getvalue()
                    calls.clear()
                    with self.assertRaises(ProjectConflict) as caught:
                        rest.import_project(desired, expected_current=expected, **flags)
                    self.assertEqual(caught.exception.paths, (script,))
                    self.assertEqual([call['method'] for call in calls], ['GET'])
                    self.assertEqual(current['zip'], edited.getvalue())

    def test_cli_import_checks_saved_baseline_before_post(self):
        from research.ignition_adapter.__main__ import main
        with tempfile.TemporaryDirectory() as directory, fixture_server() as (base, calls, current):
            root = Path(directory)
            (root/'expected.zip').write_bytes(current['zip'])
            (root/'desired.zip').write_bytes(archive('A'))
            (root/'headers.json').write_text('{}')
            arguments = dict(allow_overwrite=True, disposable_project=True,
                             zip_path=str(root/'desired.zip'), expected_path=str(root/'expected.zip'))
            (root/'args.json').write_text(json.dumps(arguments))
            cmd = ['execute', '--operation', 'project.importZip', '--isolated-test-gateway',
                   '--base-url', base, '--project', 'FixtureProject', '--version', '8.3.9',
                   '--headers-file', str(root/'headers.json'), '--args-file', str(root/'args.json')]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(cmd), 0)
            self.assertEqual([call['method'] for call in calls], ['GET', 'GET', 'POST'])
            current['zip'] = archive('B')
            calls.clear()
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(cmd), 2)
            self.assertEqual(json.loads(out.getvalue())['kind'], 'project_contents_changed')
            self.assertEqual([call['method'] for call in calls], ['GET', 'GET'])

    def test_compare_uncompressed_entries_and_report_all_changes(self):
        from research.ignition_adapter import changed_project_paths
        from research.ignition_adapter.cli import plan
        original = archive()
        def repack(edit):
            buffer = io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(original)) as src, zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as dst:
                for name in reversed(src.namelist()):
                    if edit and name == 'unknown-module/untouched.txt':
                        continue
                    data = b'new' if edit and name == VIEW else src.read(name)
                    dst.writestr(name, data)
                if edit:
                    dst.writestr('new-file', b'')
            return buffer.getvalue()
        self.assertEqual(changed_project_paths(original, repack(False)), ())
        self.assertEqual(changed_project_paths(original, repack(True)),
                         tuple(sorted([VIEW, 'new-file', 'unknown-module/untouched.txt'])))
        with self.assertRaises(AdapterError) as error:
            plan('project.importZip', '8.3.9', 'FixtureProject',
                 {'allow_overwrite': True, 'disposable_project': True})
        self.assertEqual(error.exception.reason, 'expected_archive_required')

    def test_directory_packing_is_not_a_content_conflict(self):
        from research.ignition_adapter import ProjectConflict, changed_project_paths
        from research.ignition_adapter.archive import checked_archive
        files = [
            ('project.json', b'{"title":"Fixture"}'),
            ('com.inductiveautomation.perspective/views/Main/view.json', b'{"root":{}}'),
            ('com.inductiveautomation.perspective/views/Main/resource.json', b'{}'),
        ]
        directories = (
            'com.inductiveautomation.perspective/',
            'com.inductiveautomation.perspective/views/',
            'com.inductiveautomation.perspective/views/Main/',
            'views/',
        )
        def build(with_directories, view=b'{"root":{}}', extra=None, drop=()):
            data = io.BytesIO()
            with zipfile.ZipFile(data, 'w') as archive:
                for name, payload in files:
                    if name in drop:
                        continue
                    archive.writestr(name, view if name.endswith('view.json') else payload)
                if extra:
                    archive.writestr(extra[0], extra[1])
                if with_directories:
                    for name in directories:
                        archive.writestr(name, b'')
            return data.getvalue()
        plain, packed = build(False), build(True)
        self.assertEqual(changed_project_paths(plain, packed), ())
        self.assertEqual(changed_project_paths(packed, plain), ())
        self.assertTrue(checked_archive(packed).startswith(b'PK'))
        with zipfile.ZipFile(io.BytesIO(packed)) as archive:
            for name in directories:
                self.assertTrue(archive.getinfo(name).is_dir())
        view_path = 'com.inductiveautomation.perspective/views/Main/view.json'
        edited = build(True, view=b'{"root":{"changed":true}}')
        added = build(True, extra=('ignition/script-python/Test/code.py', b'added'))
        removed = build(True, drop=('com.inductiveautomation.perspective/views/Main/resource.json',))
        self.assertEqual(changed_project_paths(packed, edited), (view_path,))
        self.assertEqual(changed_project_paths(packed, added), ('ignition/script-python/Test/code.py',))
        self.assertEqual(changed_project_paths(packed, removed),
                         ('com.inductiveautomation.perspective/views/Main/resource.json',))
        with fixture_server() as (base, calls, current):
            current['zip'] = packed
            rest = self.adapter(base).rest
            rest.discover()
            calls.clear()
            rest.import_project(plain, expected_current=plain, allow_overwrite=True, disposable_project=True)
            self.assertEqual([call['method'] for call in calls], ['GET', 'POST'])
        with fixture_server() as (base, calls, current):
            current['zip'] = edited
            rest = self.adapter(base).rest
            rest.discover()
            calls.clear()
            with self.assertRaises(ProjectConflict) as caught:
                rest.import_project(plain, expected_current=packed, allow_overwrite=True, disposable_project=True)
            self.assertEqual(caught.exception.paths, (view_path,))
            self.assertEqual([call['method'] for call in calls], ['GET'])
            self.assertEqual(current['zip'], edited)

    def test_import_needs_both_explicit_acknowledgements(self):
        with fixture_server() as (base,calls,_):
            a=self.adapter(base);a.rest.discover()
            for kwargs in [{},{'allow_overwrite':True},{'disposable_project':True}]:
                with self.assertRaises(AdapterError):a.rest.import_project(archive(),expected_current=archive(),**kwargs)
            self.assertEqual(len(calls),1)

    def test_http_success_with_business_failure_is_not_accepted(self):
        with fixture_server('import-fails') as (base,calls,_):
            a=self.adapter(base);a.rest.discover()
            with self.assertRaises(AdapterError) as error:a.rest.import_project(archive(),expected_current=archive(),allow_overwrite=True,disposable_project=True)
            self.assertEqual(error.exception.reason,'operation_failed')
            self.assertNotIn('private-server-response',str(error.exception))
            self.assertEqual(len(calls),3)

    def test_839_mcp_and_runtime_tag_writes_block_without_requests(self):
        with fixture_server() as (base,calls,_):
            a=self.adapter(base,'8.3.9')
            with self.assertRaises(AdapterError):a.mcp.initialize()
            with self.assertRaises(AdapterError):a.rest.read_values({'paths':['[default]Fixture/T']})
            with self.assertRaises(AdapterError):a.rest.configure_tags({'name':'T'},allow_gateway_write=True)
            with self.assertRaises(AdapterError):a.rest.write_values({'value':1},expected_count=1,allow_gateway_write=True)
            self.assertEqual(calls,[])
            self.assertEqual(a.identities.mcp,Status.BLOCKED)

    def test_839_tag_configuration_import_export_have_verified_wire_shapes(self):
        with fixture_server() as (base,calls,_):
            a=self.adapter(base,'8.3.9');a.rest.discover()
            created=b'{"name":"HarnessLab","tagType":"Folder","tags":[{"name":"Temperature","value":42.5}]}\n'
            updated=b'{"tags":[{"name":"Temperature","value":21.5}]}\n'
            a.rest.import_tag_configuration('default',created,collision_policy='Abort',allow_gateway_write=True)
            a.rest.import_tag_configuration('default',updated,path='HarnessLab',collision_policy='MergeOverwrite',allow_gateway_write=True)
            result=a.rest.export_tag_configuration('default','HarnessLab')
            self.assertEqual(calls[-3]['path'],'/data/api/v1/tags/import?provider=default&type=json&collisionPolicy=Abort')
            self.assertEqual(calls[-3]['headers']['Content-Type'],'application/octet-stream')
            self.assertEqual(calls[-3]['body'],created)
            self.assertEqual(calls[-2]['path'],'/data/api/v1/tags/import?provider=default&type=json&collisionPolicy=MergeOverwrite&path=HarnessLab')
            self.assertEqual(calls[-2]['headers']['Content-Type'],'application/octet-stream')
            self.assertEqual(calls[-2]['body'],updated)
            self.assertEqual(calls[-1]['path'],'/data/api/v1/tags/export?provider=default&type=json&path=HarnessLab')
            self.assertNotIn('X-Ignition-Api-Token',calls[-1]['headers'])
            self.assertEqual(calls[-1]['headers']['Cookie'],'web-fixture-secret')
            self.assertEqual(result['tagType'],'Folder')

    def test_beta_read_values_uses_get_json_body_and_write_is_distinct(self):
        with fixture_server() as (base,calls,_):
            a=self.adapter(base);a.rest.discover()
            read_body={'tags':['[default]Fixture/T']}
            write_body={'tagPaths':['[default]Fixture/T'],'values':[21.5]}
            self.assertEqual(a.rest.read_values(read_body)['results'][0]['value'],42.5)
            a.rest.write_values(write_body,expected_count=1,allow_gateway_write=True)
            self.assertEqual(calls[-2]['method'],'GET')
            self.assertEqual(calls[-2]['path'],'/data/api/v1/tags/read')
            self.assertEqual(calls[-2]['headers']['Content-Type'],'application/json')
            self.assertEqual(calls[-2]['body'],json.dumps(read_body,separators=(',',':')).encode())
            self.assertEqual(calls[-1]['method'],'POST')
            self.assertEqual(calls[-1]['path'],'/data/api/v1/tags/write')
            self.assertEqual(calls[-1]['body'],json.dumps(write_body,separators=(',',':')).encode())
            self.assertNotIn(b'paths',calls[-2]['body'])
            self.assertNotIn(b'collisionPolicy',calls[-1]['body'])

    def test_beta_read_results_must_be_one_object_per_requested_tag(self):
        with fixture_server() as (base,calls,current):
            adapter=self.adapter(base);adapter.rest.discover()
            accepted=[
                ({'tags':['[default]Fixture/T']},
                 {'results':[{'value':42.5,'quality':{'code':192}}]}),
                ({'tags':['[default]Fixture/T','[default]Fixture/U']},
                 {'results':[{'value':1,'quality':{'code':192}},{'value':2,'quality':{'code':192}}]}),
                ({'tags':['[default]Fixture/T']},
                 {'results':[{'quality':{'code':0,'diagnosticMessage':'not Good'}}]}),
                ({'tags':['[default]Fixture/T']},
                 {'results':[{'quality':{'code':192.0},'timestamp':'2026-11-18T10:50:00Z'}]}),
                ({'tags':['[default]Fixture/T']}, {'results':[{}]}),
                ({'tags':['[default]Fixture/T']}, {'results':[{'code':192}]}),
                ({'tags':['[default]Fixture/T']}, {'results':[{'value':None}]}),
            ]
            for document, body in accepted:
                with self.subTest(accepted=body):
                    current['read_body']=body
                    self.assertEqual(adapter.rest.read_values(document), body)
            rejected=[
                ({'tags':['[default]Fixture/T','[default]Fixture/U']},
                 {'results':[{'value':1,'quality':{'code':192}}]}),
                ({'tags':['[default]Fixture/T']},
                 {'results':[{'value':1,'quality':{'code':192}},{'value':2,'quality':{'code':192}}]}),
                ({'tags':['[default]Fixture/T']}, {'results':[None]}),
                ({'tags':['[default]Fixture/T']}, {'results':['bad']}),
                ({'tags':['[default]Fixture/T']}, {'results':[192]}),
                ({'tags':['[default]Fixture/T']}, {'results':[]}),
                ({'tags':['[default]Fixture/T']}, {}),
                ({'tags':['[default]Fixture/T']}, {'results':None}),
                ({'tags':['[default]Fixture/T']}, {'results':{'value':1}}),
                ({'tags':['[default]Fixture/T']}, {'results':[{'quality':192}]}),
                ({'tags':['[default]Fixture/T']}, {'results':[{'quality':{'code':'192'}}]}),
                ({'tags':['[default]Fixture/T']}, {'results':[{'quality':{'code':True}}]}),
                ({'tags':['[default]Fixture/T']},
                 {'results':[{'quality':{'code':0,'diagnosticMessage':0}}]}),
                ({'tags':['[default]Fixture/T']}, {'results':[{'timestamp':1794929264393}]}),
            ]
            for document, body in rejected:
                with self.subTest(rejected=body):
                    current['read_body']=body
                    before=len(calls)
                    with self.assertRaises(AdapterError) as error:
                        adapter.rest.read_values(document)
                    self.assertEqual(error.exception.reason,'tag_read_failed')
                    self.assertEqual(calls[-1]['path'],'/data/api/v1/tags/read')
                    self.assertEqual(calls[-1]['body'],json.dumps(document,separators=(',',':')).encode())
                    self.assertEqual(len(calls),before+1)

    def test_beta_tag_documents_outside_excerpt_are_not_sent_or_rewritten(self):
        from research.ignition_adapter.cli import plan
        with fixture_server() as (base,calls,_):
            adapter=self.adapter(base);adapter.rest.discover()
            rejected=[
                ('read', {'paths':['[default]Fixture/T']}, {}),
                ('read', {'tags':['[default]Fixture/T'],'paths':['x']}, {}),
                ('write', [{'path':'[default]Fixture/T','value':21.5}], {'expected_count':1,'allow_gateway_write':True}),
                ('write', {'tagPaths':['[default]Fixture/T','[default]Fixture/U'],'values':[21.5]},
                 {'expected_count':1,'allow_gateway_write':True}),
            ]
            for kind, document, kwargs in rejected:
                with self.subTest(document=document):
                    with self.assertRaises(AdapterError) as error:
                        if kind=='read': adapter.rest.read_values(document)
                        else: adapter.rest.write_values(document, **kwargs)
                    if isinstance(document, dict) and isinstance(document.get('tagPaths'), list) and isinstance(document.get('values'), list) and len(document['tagPaths'])!=len(document['values']):
                        self.assertEqual(error.exception.reason,'tag_paths_values_length_mismatch')
                    else:
                        self.assertEqual(error.exception.reason,'tag_document_not_in_excerpt')
            self.assertEqual([call['path'] for call in calls],['/openapi.json'])
        with self.assertRaises(AdapterError) as error:
            plan('tag.readValues','2027.2.0-beta1','FixtureProject',{'document':{'paths':['[default]Fixture/T']}})
        self.assertEqual(error.exception.reason,'tag_document_not_in_excerpt')
        with self.assertRaises(AdapterError) as error:
            plan('tag.writeValues','2027.2.0-beta1','FixtureProject',{
                'document':{'tagPaths':['[default]Fixture/T'],'values':[1,2]},'expected_count':1})
        self.assertEqual(error.exception.reason,'tag_paths_values_length_mismatch')
        ready=plan('tag.writeValues','2027.2.0-beta1','FixtureProject',{
            'document':{'tagPaths':['[default]Fixture/T'],'values':[21.5]},'expected_count':1})
        self.assertEqual(ready['calls'][0]['body'],{'tagPaths':['[default]Fixture/T'],'values':[21.5]})
        null_value={'tagPaths':['[default]Fixture/T'],'values':[None]}
        self.assertEqual(plan('tag.writeValues','2027.2.0-beta1','FixtureProject',{
            'document':null_value,'expected_count':1})['calls'][0]['body'],null_value)

    def test_beta_tag_wrong_json_types_are_not_sent(self):
        from research.ignition_adapter.cli import plan
        wrong=[
            ('read', {'tags':'[default]Fixture/T'}),
            ('read', {'tags':{'path':'[default]Fixture/T'}}),
            ('read', {'tags':None}),
            ('write', {'tagPaths':['[default]Fixture/T'],'values':21.5}),
            ('write', {'tagPaths':'[default]Fixture/T','values':[21.5]}),
            ('write', {'tagPaths':['[default]Fixture/T'],'values':{'v':21.5}}),
            ('write', {'tagPaths':['[default]Fixture/T'],'values':'21.5'}),
            ('write', {'tagPaths':None,'values':[21.5]}),
        ]
        with fixture_server() as (base,calls,_):
            adapter=self.adapter(base);adapter.rest.discover()
            for kind, document in wrong:
                with self.subTest(document=document):
                    with self.assertRaises(AdapterError) as error:
                        if kind=='read':
                            adapter.rest.read_values(document)
                        else:
                            adapter.rest.write_values(document,expected_count=1,allow_gateway_write=True)
                    self.assertEqual(error.exception.reason,'tag_document_type_mismatch')
                    with self.assertRaises(AdapterError) as planned:
                        if kind=='read':
                            plan('tag.readValues','2027.2.0-beta1','FixtureProject',{'document':document})
                        else:
                            plan('tag.writeValues','2027.2.0-beta1','FixtureProject',{
                                'document':document,'expected_count':1})
                    self.assertEqual(planned.exception.reason,'tag_document_type_mismatch')
            self.assertEqual([call['path'] for call in calls],['/openapi.json'])

    def test_config_and_quality_failures_are_not_success_and_writes_are_not_retried(self):
        for mode in ['bad-quality','partial-config']:
            with self.subTest(mode=mode),fixture_server(mode) as (base,calls,_):
                a=self.adapter(base);a.rest.discover()
                with self.assertRaises(AdapterError):
                    if mode=='bad-quality':a.rest.write_values({'tagPaths':['[default]Fixture/T'],'values':[1]},expected_count=1,allow_gateway_write=True)
                    else:a.rest.configure_tags({'name':'T'},allow_gateway_write=True)
                self.assertEqual(len(calls),2)

    def test_catalyst_pagination_and_calls_keep_four_identity_states_separate(self):
        with fixture_server() as (base,calls,_):
            a=self.adapter(base);a.mcp.initialize();tools=a.mcp.list_tools()
            initial=json.loads(calls[0]['body'])
            self.assertEqual(initial['method'],'initialize')
            self.assertEqual(initial['params']['protocolVersion'],'2025-06-18')
            self.assertEqual(initial['params']['capabilities'],{})
            self.assertEqual(set(initial['params']),{'protocolVersion','capabilities','clientInfo'})
            self.assertNotIn('Mcp-Protocol-Version',calls[0]['headers'])
            self.assertNotIn('Mcp-Session-Id',calls[0]['headers'])
            self.assertEqual(calls[0]['headers']['Accept'],'application/json, text/event-stream')
            self.assertEqual(json.loads(calls[1]['body']),{'jsonrpc':'2.0','method':'notifications/initialized'})
            self.assertEqual(calls[1]['headers']['Mcp-Protocol-Version'],'2025-06-18')
            self.assertEqual(calls[1]['headers']['Mcp-Session-Id'],'fixture-session-secret')
            self.assertEqual(json.loads(calls[2]['body'])['params'],{})
            self.assertEqual(json.loads(calls[3]['body'])['params'],{'cursor':'fixture-cursor'})
            for call in calls:
                self.assertNotIn('Cookie',call['headers'])
            self.assertEqual([t['name'] for t in tools],['diagnostics','realtime','query','providers'])
            self.assertEqual(a.mcp.providers()['structuredContent'],{'fixture':True})
            a.mcp.realtime(['[default]Fixture/T'])
            a.mcp.diagnostics('[default]Fixture/T')
            a.mcp.query('[default]Fixture/*',quality='Good',max_results=10,continuation_point='opaque')
            self.assertEqual(json.loads(calls[-1]['body'])['params'],{'name':'query','arguments':{
                'path':'[default]Fixture/*','filters':{'quality':'Good','maxResults':10},'continuationPoint':'opaque'}})
            self.assertEqual(a.identities.mcp,Status.READY)
            self.assertEqual(a.identities.engineering,Status.UNAVAILABLE)
            self.assertEqual(a.identities.gateway_web,Status.UNKNOWN)
            self.assertEqual(a.identities.perspective,Status.UNKNOWN)
            self.assertFalse(a.capabilities['realtime_subscription'])
            self.assertNotIn('Cookie',calls[-1]['headers'])
            self.assertEqual(calls[-1]['headers']['X-Ignition-Api-Token'],'Fixture:token-fixture-secret')
            self.assertEqual(calls[-1]['headers']['Mcp-Session-Id'],'fixture-session-secret')

    def test_session_expiry_requires_explicit_reinitialization_not_automatic_retry(self):
        with fixture_server('expired') as (base,calls,_):
            a=self.adapter(base)
            with self.assertRaises(AdapterError):a.mcp.initialize()
            self.assertEqual(a.identities.mcp,Status.EXPIRED)
            self.assertEqual(len(calls),2)
            with self.assertRaises(AdapterError):a.mcp.providers()
            self.assertEqual(len(calls),2)

    def test_repeated_tool_cursor_fails_closed(self):
        with fixture_server('loop') as (base,calls,_):
            a=self.adapter(base);a.mcp.initialize()
            with self.assertRaises(AdapterError):a.mcp.list_tools()
            with self.assertRaises(AdapterError):a.mcp.providers()
            self.assertEqual(len(calls),4)

    def test_mcp_error_and_unknown_tool_are_not_forwarded_or_retried(self):
        with fixture_server('tool-error') as (base,calls,_):
            a=self.adapter(base);a.mcp.initialize();a.mcp.list_tools()
            with self.assertRaises(AdapterError) as error:a.mcp.providers()
            self.assertNotIn('private-server-response',repr(error.exception))
            self.assertEqual(len(calls),5)
            with self.assertRaises(AdapterError):a.mcp.call('unverified_write',{})
            self.assertEqual(len(calls),5)

    def test_preview_url_does_not_make_requests_or_mark_authenticated(self):
        with fixture_server() as (base,calls,_):
            a=self.adapter(base)
            self.assertEqual(a.preview_url(),base+'/data/perspective/client/FixtureProject')
            self.assertNotIn('/app/perspective',a.preview_url())
            self.assertEqual(calls,[])
            self.assertEqual(a.identities.perspective,Status.UNKNOWN)

    def test_rest_never_receives_mcp_credentials_and_errors_hide_server_content(self):
        with fixture_server('denied') as (base,calls,_):
            a=self.adapter(base)
            with self.assertRaises(AdapterError) as error:a.rest.discover()
            self.assertEqual(error.exception.status,403)
            self.assertNotIn('X-Ignition-Api-Token',calls[0]['headers'])
            self.assertEqual(calls[0]['headers']['Cookie'],'web-fixture-secret')
            self.assertNotIn('secret',str(error.exception))
            self.assertEqual(a.identities.engineering,Status.UNAVAILABLE)

    def test_same_tool_name_with_changed_schema_is_not_callable(self):
        with fixture_server('changed-schema') as (base,calls,_):
            a=self.adapter(base);a.mcp.initialize();a.mcp.list_tools()
            with self.assertRaises(AdapterError) as error:a.mcp.providers()
            self.assertEqual(error.exception.reason,'tool_schema_not_verified')
            self.assertEqual(len(calls),4)

    def test_initial_endpoint_404_is_not_an_expired_session(self):
        with fixture_server('mcp-missing') as (base,calls,_):
            a=self.adapter(base)
            with self.assertRaises(AdapterError):a.mcp.initialize()
            self.assertEqual(a.identities.mcp,Status.FAILED)
            self.assertEqual(len(calls),1)

    def test_cross_target_endpoint_and_malformed_credentials_rejected_before_network(self):
        with fixture_server() as (base,calls,_):
            target=LabTarget(base,'2027.2.0-beta1',isolated_test_gateway=True)
            with self.assertRaises(AdapterError):
                ResearchAdapter(target,'FixtureProject',rest_headers={},
                                mcp_endpoint='http://127.0.0.1:8088/data/catalyst-agent/mcp-servers/HarnessLab')
            with self.assertRaises(AdapterError):
                ResearchAdapter(target,'FixtureProject',rest_headers={'Cookie':'unsafe\r\nheader'})
            with self.assertRaises(AdapterError):
                ResearchAdapter(target,'FixtureProject',rest_headers={},
                                mcp_endpoint=base+'/data/%2e%2e/mcp')
            self.assertEqual(calls,[])

    def test_malformed_http_status_is_sanitized_and_updates_mcp_failure_state(self):
        with fixture_server('malformed-status') as (base,calls,_):
            a=self.adapter(base)
            with self.assertRaises(Exception) as error:a.mcp.initialize()
            self.assertIsInstance(error.exception,AdapterError)
            self.assertNotIn('private-server-response',str(error.exception))
            self.assertNotIn('secret-value',str(error.exception))
            self.assertEqual(a.identities.mcp,Status.FAILED)
            self.assertEqual(len(calls),1)

    def test_redirects_not_followed(self):
        with fixture_server('redirect') as (base,calls,_):
            with self.assertRaises(AdapterError) as error:self.adapter(base).rest.discover()
            self.assertEqual(error.exception.status,302)
            self.assertNotIn('stolen-secret-location',str(error.exception))
            self.assertEqual(len(calls),1)
            self.assertEqual(calls[0]['path'],'/openapi.json')

    def test_archive_patch_rejects_new_resource_and_invalid_zip(self):
        with self.assertRaises(AdapterError):patch_existing_view(archive(),VIEW.replace('Home','New'),{})
        with self.assertRaises(AdapterError):patch_existing_view(b'not zip',VIEW,{})

    def test_archive_patch_preserves_entry_metadata_and_order(self):
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as source:
            info=zipfile.ZipInfo('project.json',date_time=(2020,1,2,3,4,6))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o644<<16
            source.writestr(info,'{"title":"Fixture"}')
            source.writestr('folder/',b'')
            opaque=zipfile.ZipInfo('ignition/global-props/data.bin',date_time=(2019,5,6,7,8,8))
            opaque.compress_type=zipfile.ZIP_DEFLATED
            source.writestr(opaque,b'\x00\x01opaque')
            source.writestr(VIEW,json.dumps({'root':{'props':{'text':'baseline'}}}))
            source.comment=b'archive-comment'
        original=raw.getvalue()
        changed=patch_existing_view(original,VIEW,{'root':{'props':{'text':'changed'}}})
        with zipfile.ZipFile(io.BytesIO(original)) as before, zipfile.ZipFile(io.BytesIO(changed)) as after:
            self.assertEqual(before.namelist(),after.namelist())
            self.assertEqual(after.comment,b'archive-comment')
            for name in before.namelist():
                old,new=before.getinfo(name),after.getinfo(name)
                self.assertEqual(old.compress_type,new.compress_type)
                self.assertEqual(old.date_time,new.date_time)
                self.assertEqual(old.external_attr,new.external_attr)
            self.assertEqual(after.read('ignition/global-props/data.bin'),b'\x00\x01opaque')
            self.assertEqual(json.loads(after.read(VIEW))['root']['props']['text'],'changed')

    def test_project_create_sends_only_the_recorded_name(self):
        for version in ('8.3.9','2027.2.0-beta1'):
            with self.subTest(version=version),fixture_server() as (base,calls,_):
                adapter=self.adapter(base,version);adapter.rest.discover()
                with self.assertRaises(AdapterError):adapter.rest.create_project()
                self.assertEqual(len(calls),1)
                result=adapter.rest.create_project(allow_gateway_write=True)
                self.assertEqual(calls[-1]['method'],'POST')
                self.assertEqual(calls[-1]['path'],'/data/api/v1/projects')
                self.assertEqual(calls[-1]['body'],b'{"name":"FixtureProject"}')
                self.assertTrue(result['success'])
                self.assertEqual(adapter.identities.engineering,Status.UNAVAILABLE)

    def test_create_business_failure_hides_server_text_and_is_not_retried(self):
        with fixture_server('create-fails') as (base,calls,_):
            adapter=self.adapter(base);adapter.rest.discover()
            with self.assertRaises(AdapterError) as error:
                adapter.rest.create_project(allow_gateway_write=True)
            self.assertEqual(error.exception.reason,'operation_failed')
            self.assertNotIn('private-server-response',str(error.exception))
            self.assertEqual(len(calls),2)

    def test_beta_tag_routes_are_not_used_on_839_and_import_is_not_a_beta_write(self):
        with fixture_server() as (base,calls,_):
            beta=self.adapter(base)
            with self.assertRaises(AdapterError):
                beta.rest.import_tag_configuration('default',b'{"tags":[{"name":"T"}]}',allow_gateway_write=True)
            with self.assertRaises(AdapterError):
                beta.rest.export_tag_configuration('default','HarnessLab')
            stable=self.adapter(base,'8.3.9')
            with self.assertRaises(AdapterError):
                stable.rest.configure_tags({'name':'T'},allow_gateway_write=True)
            self.assertEqual(calls,[])

    def test_tag_import_rejects_reencoded_documents_and_unverified_policies(self):
        with fixture_server() as (base,calls,_):
            adapter=self.adapter(base,'8.3.9');adapter.rest.discover()
            for document in ({'tags':[{'name':'T'}]}, b'not-json', b'{}', b'[]', b''):
                with self.assertRaises(AdapterError):
                    adapter.rest.import_tag_configuration('default',document,allow_gateway_write=True)
            with self.assertRaises(AdapterError):
                adapter.rest.import_tag_configuration('default',b'{"tags":[{"name":"T"}]}',collision_policy='Ignore',allow_gateway_write=True)
            self.assertEqual(len(calls),1)

    def test_configure_document_is_not_wrapped(self):
        with fixture_server() as (base,calls,_):
            adapter=self.adapter(base);adapter.rest.discover()
            document={'path':'[default]HarnessLab/Temperature','tagType':'AtomicTag'}
            adapter.rest.configure_tags(document,allow_gateway_write=True)
            self.assertEqual(calls[-1]['path'],'/data/api/v1/tags/configuration')
            self.assertEqual(calls[-1]['body'],json.dumps(document,separators=(',',':')).encode())
            self.assertNotIn(b'"provider"',calls[-1]['body'])
            before=len(calls)
            with self.assertRaises(AdapterError) as error:
                adapter.rest.configure_tags({'provider':1,'tags':{'name':'T'},'collisionPolicy':'not-an-enum'},
                                            allow_gateway_write=True)
            self.assertEqual(error.exception.reason,'tag_configuration_type_mismatch')
            self.assertEqual(len(calls),before)

    def test_nested_quality_and_short_write_results_are_not_success(self):
        with fixture_server('nested-quality') as (base,calls,_):
            adapter=self.adapter(base);adapter.rest.discover()
            with self.assertRaises(AdapterError):
                adapter.rest.write_values({'tagPaths':['[default]Fixture/T'],'values':[1]},expected_count=1,allow_gateway_write=True)
            self.assertEqual(len(calls),2)
        with fixture_server() as (base,calls,_):
            adapter=self.adapter(base);adapter.rest.discover()
            with self.assertRaises(AdapterError):
                adapter.rest.write_values({'tagPaths':['[default]Fixture/T','[default]Fixture/U'],'values':[1,2]},
                                          expected_count=2,allow_gateway_write=True)
            self.assertEqual(len(calls),2)

    def test_write_expected_count_must_match_tag_paths_before_post(self):
        from research.ignition_adapter.cli import execute, plan
        two={'tagPaths':['[default]Fixture/T','[default]Fixture/U'],'values':[21.5,22.5]}
        with self.assertRaises(AdapterError) as planned:
            plan('tag.writeValues','2027.2.0-beta1','FixtureProject',{'document':two,'expected_count':1})
        self.assertEqual(planned.exception.reason,'tag_value_count_mismatch')
        with fixture_server() as (base,calls,current):
            adapter=self.adapter(base);adapter.rest.discover()
            current['write_body']={'results':[{'code':192}]}
            before=len(calls)
            with self.assertRaises(AdapterError) as error:
                adapter.rest.write_values(two,expected_count=1,allow_gateway_write=True)
            self.assertEqual(error.exception.reason,'tag_value_count_mismatch')
            self.assertEqual(calls[before:],[])
            with self.assertRaises(AdapterError) as executed:
                execute('tag.writeValues',base_url=base,version='2027.2.0-beta1',project='FixtureProject',
                        rest_headers={'Cookie':'web-fixture-secret'},args={'document':two,'expected_count':1},
                        isolated=True)
            self.assertEqual(executed.exception.reason,'tag_value_count_mismatch')
            self.assertEqual(calls[before:],[])
            current['write_body']={'results':[{'code':192},{'code':192}]}
            with self.assertRaises(AdapterError) as error:
                adapter.rest.write_values(two,expected_count=1,allow_gateway_write=True)
            self.assertEqual(error.exception.reason,'tag_value_count_mismatch')
            self.assertEqual(calls[before:],[])
            accepted=[
                ({'tagPaths':['[default]Fixture/T'],'values':[21.5]},1,{'results':[{'code':192}]}),
                ({'tagPaths':['[default]Fixture/T'],'values':[21.5]},1,{'results':[{'code':192.0}]}),
                (two,2,{'results':[{'code':192},{'code':192,'diagnosticMessage':'Good'}]}),
            ]
            for document, count, body in accepted:
                with self.subTest(accepted=body):
                    current['write_body']=body
                    self.assertEqual(adapter.rest.write_values(document,expected_count=count,allow_gateway_write=True),body)
                    self.assertEqual(calls[-1]['path'],'/data/api/v1/tags/write')
                    self.assertEqual(calls[-1]['body'],json.dumps(document,separators=(',',':')).encode())
            rejected=[
                (two,2,{'results':[{'code':192}]}),
                (two,2,{'results':[{'code':192},{'code':0,'diagnosticMessage':'not Good'}]}),
                ({'tagPaths':['[default]Fixture/T'],'values':[21.5]},1,{'results':[None]}),
                ({'tagPaths':['[default]Fixture/T'],'values':[21.5]},1,{'results':['bad']}),
                ({'tagPaths':['[default]Fixture/T'],'values':[21.5]},1,{'results':[192]}),
                ({'tagPaths':['[default]Fixture/T'],'values':[21.5]},1,{'results':[]}),
                ({'tagPaths':['[default]Fixture/T'],'values':[21.5]},1,{}),
                ({'tagPaths':['[default]Fixture/T'],'values':[21.5]},1,{'results':None}),
                ({'tagPaths':['[default]Fixture/T'],'values':[21.5]},1,{'results':{'code':192}}),
                ({'tagPaths':['[default]Fixture/T'],'values':[21.5]},1,{'results':[{'quality':{'code':192}}]}),
                ({'tagPaths':['[default]Fixture/T'],'values':[21.5]},1,{'results':[{'code':True}]}),
            ]
            for document, count, body in rejected:
                with self.subTest(rejected=body):
                    current['write_body']=body
                    posted=len(calls)
                    with self.assertRaises(AdapterError) as error:
                        adapter.rest.write_values(document,expected_count=count,allow_gateway_write=True)
                    self.assertEqual(error.exception.reason,'tag_write_not_all_good')
                    self.assertEqual(calls[-1]['path'],'/data/api/v1/tags/write')
                    self.assertEqual(len(calls),posted+1)
        self.assertEqual(plan('tag.writeValues','2027.2.0-beta1','FixtureProject',{
            'document':{'tagPaths':['[default]Fixture/T'],'values':[21.5]},'expected_count':1})['status'],'ready')

    def test_post_redirect_is_not_followed_and_proxy_env_is_ignored(self):
        with fixture_server('redirect-post') as (base,calls,_):
            adapter=self.adapter(base);adapter.rest.discover()
            before=len(calls)
            with self.assertRaises(AdapterError) as error:
                adapter.rest.import_project(archive(),expected_current=archive(),allow_overwrite=True,disposable_project=True)
            self.assertEqual(error.exception.status,307)
            self.assertNotIn('stolen-secret-location',str(error.exception))
            self.assertEqual([call['path'] for call in calls[before:]],['/data/api/v1/projects/export/FixtureProject','/data/api/v1/projects/import/FixtureProject?overwrite=true'])
        previous={key:os.environ.get(key) for key in ('http_proxy','https_proxy','HTTP_PROXY','ALL_PROXY')}
        os.environ['http_proxy']=os.environ['https_proxy']=os.environ['HTTP_PROXY']=os.environ['ALL_PROXY']='http://127.0.0.1:9'
        try:
            with fixture_server() as (base,calls,_):
                self.adapter(base).rest.discover()
                self.assertEqual([call['path'] for call in calls],['/openapi.json'])
        finally:
            for key,value in previous.items():
                if value is None:os.environ.pop(key,None)
                else:os.environ[key]=value

    def test_invalid_mcp_session_is_not_stored_or_echoed(self):
        with fixture_server('bad-session') as (base,calls,_):
            adapter=self.adapter(base)
            with self.assertRaises(AdapterError) as error:adapter.mcp.initialize()
            self.assertEqual(error.exception.reason,'invalid_session_header')
            self.assertNotIn('bad session',str(error.exception))
            self.assertEqual(adapter.identities.mcp,Status.FAILED)
            self.assertIsNone(adapter.mcp._session_id)
            self.assertEqual(len(calls),1)

    def test_reinitialize_does_not_send_the_previous_session(self):
        with fixture_server() as (base,calls,_):
            adapter=self.adapter(base)
            adapter.mcp.initialize()
            adapter.mcp.initialize()
            self.assertNotIn('Mcp-Session-Id',calls[2]['headers'])
            self.assertEqual(json.loads(calls[2]['body'])['method'],'initialize')

    def test_ipv6_loopback_target_stays_on_loopback(self):
        class Server(ThreadingHTTPServer):
            address_family=socket.AF_INET6
        seen=[]

        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):
                pass
            def do_GET(self):
                seen.append(self.path)
                body=json.dumps({'openapi':'3.1.0','info':{'title':'Fixture','version':'1'},'paths':{}}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)))
                self.end_headers();self.wfile.write(body)
        server=Server(('::1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            base='http://[::1]:'+str(server.server_address[1])
            self.adapter(base,'8.3.9').rest.discover()
            self.assertEqual(seen,['/openapi.json'])
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_cli_plan_matches_wire_shape_and_execute_redacts_headers(self):
        from research.ignition_adapter.cli import plan
        root=Path(__file__).parents[1]
        planned=plan('tag.importConfiguration','8.3.9','HarnessLab',
                     {'provider':'default','collision_policy':'Abort'})
        self.assertEqual(planned['calls'][0]['path'],'/data/api/v1/tags/import?provider=default&type=json&collisionPolicy=Abort')
        self.assertEqual(planned['network'],False)
        blocked=plan('tag.readValues','8.3.9','HarnessLab',{'document':{'paths':['[default]HarnessLab/Temperature']}})
        self.assertEqual(blocked['status'],'blocked')
        self.assertEqual(blocked['calls'],[])
        with fixture_server() as (base,calls,_):
            proc=subprocess.run([sys.executable,'-m','research.ignition_adapter','execute','--operation','tag.exportConfiguration',
                                 '--version','8.3.9','--project','FixtureProject','--base-url',base,
                                 '--headers-file',str(root/'tests'/'test_research_adapter.py')],
                                cwd=root,capture_output=True,text=True)
            self.assertEqual(calls,[])
            self.assertEqual(proc.returncode,2)
            self.assertIn('isolated_ack_required',proc.stdout)
            self.assertNotIn('web-fixture-secret',proc.stdout)
        with fixture_server('echo-secret') as (base,calls,_):
            with tempfile.TemporaryDirectory() as directory:
                header_path=Path(directory)/'headers.json'
                args_path=Path(directory)/'args.json'
                header_path.write_text(json.dumps({'Cookie':'web-fixture-secret','X-CSRF-Token':'csrf-fixture-secret'}),encoding='utf-8')
                args_path.write_text(json.dumps({'provider':'default','path':'HarnessLab'}),encoding='utf-8')
                proc=subprocess.run([sys.executable,'-m','research.ignition_adapter','execute','--isolated-test-gateway',
                                     '--operation','tag.exportConfiguration','--version','8.3.9','--project','FixtureProject',
                                     '--base-url',base,'--headers-file',str(header_path),'--args-file',str(args_path)],
                                    cwd=root,capture_output=True,text=True)
            self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
            self.assertNotIn('web-fixture-secret',proc.stdout)
            self.assertNotIn('csrf-fixture-secret',proc.stdout)
            self.assertIn('[redacted]',proc.stdout)
            self.assertEqual(calls[-1]['path'],'/data/api/v1/tags/export?provider=default&type=json&path=HarnessLab')
            self.assertEqual(calls[-1]['headers']['Cookie'],'web-fixture-secret')
            self.assertNotIn('X-Ignition-Api-Token',calls[-1]['headers'])

    def test_cli_refuses_gateway_install_paths_and_reports_openapi_routes_offline(self):
        from research.ignition_adapter.cli import discover, outside_gateway_install
        with self.assertRaises(AdapterError):
            outside_gateway_install('/usr/local/ignition/data/db/config.idb')
        report=discover('8.3.9')
        self.assertEqual(report['network'],False)
        self.assertEqual(report['operations']['tag.importConfiguration'],'needs_target_openapi')
        self.assertEqual(report['operations']['tag.readValues'],'blocked_by_version')
        self.assertEqual(report['operations']['mcp.listTools'],'blocked_by_version')
        self.assertIn('designer_login',report['not_claimed'])
        present=discover('2027.2.0-beta1',{'openapi':'3.1.0','paths':{
            '/data/api/v1/tags/read':{'get':{}},'/data/api/v1/tags/write':{'post':{}},
            '/data/api/v1/tags/configuration':{'post':{}}}})
        self.assertEqual(present['operations']['tag.readValues'],'present')
        self.assertEqual(present['operations']['tag.importConfiguration'],'blocked_by_version')
        self.assertEqual(present['operations']['mcp.call'],'needs_explicit_endpoint')
        hidden=discover('8.3.9', {'openapi':'3.1.0','paths':{
            '/data/api/v1/projects/import/{name}':{'post':{}}}})
        self.assertEqual(hidden['operations']['project.export'],'absent')
        self.assertEqual(hidden['operations']['project.importZip'],'absent')

    def test_discover_tag_document_policy_matches_plan(self):
        from research.ignition_adapter.cli import discover, plan
        beta=discover('2027.2.0-beta1')
        self.assertNotIn('beta_tag_document',beta)
        policy=beta['tag_document_policy']
        self.assertEqual(policy['tag.readValues'],'excerpt:beta1-tag-openapi-fields.json')
        self.assertEqual(policy['tag.writeValues'],'excerpt:beta1-tag-openapi-fields.json')
        self.assertNotEqual(policy['tag.readValues'],'caller_supplied_json')
        self.assertNotEqual(policy['tag.writeValues'],'caller_supplied_json')
        self.assertEqual(policy['tag.configure'],'caller_supplied_json')
        stable=discover('8.3.9')
        self.assertNotIn('beta_tag_document',stable)
        self.assertEqual(stable['tag_document_policy']['tag.readValues'],'blocked_by_version')
        self.assertEqual(stable['tag_document_policy']['tag.writeValues'],'blocked_by_version')
        self.assertNotEqual(stable['tag_document_policy']['tag.readValues'],'caller_supplied_json')
        read_doc={'tags':['[default]Fixture/T']}
        ready=plan('tag.readValues','2027.2.0-beta1','FixtureProject',{'document':read_doc})
        self.assertEqual(ready['status'],'ready')
        self.assertEqual(ready['calls'][0]['method'],'GET')
        self.assertEqual(ready['calls'][0]['body'],read_doc)
        write_doc={'tagPaths':['[default]Fixture/T'],'values':[21.5]}
        ready=plan('tag.writeValues','2027.2.0-beta1','FixtureProject',{'document':write_doc,'expected_count':1})
        self.assertEqual(ready['status'],'ready')
        self.assertEqual(ready['calls'][0]['method'],'POST')
        self.assertEqual(ready['calls'][0]['body'],write_doc)
        with self.assertRaises(AdapterError) as error:
            plan('tag.readValues','2027.2.0-beta1','FixtureProject',{'document':{'paths':['[default]Fixture/T']}})
        self.assertEqual(error.exception.reason,'tag_document_not_in_excerpt')
        with self.assertRaises(AdapterError) as error:
            plan('tag.writeValues','2027.2.0-beta1','FixtureProject',{
                'document':[{'path':'[default]Fixture/T','value':21.5}],'expected_count':1})
        self.assertEqual(error.exception.reason,'tag_document_not_in_excerpt')
        configured={'name':'T','valueSource':'memory'}
        self.assertEqual(plan('tag.configure','2027.2.0-beta1','FixtureProject',{'document':configured})['calls'][0]['body'],configured)
        blocked=plan('tag.writeValues','8.3.9','FixtureProject',{'document':write_doc,'expected_count':1})
        self.assertEqual(blocked['status'],'blocked')
        self.assertEqual(blocked['calls'],[])

    def _ready_catalog(self, mode='ok'):
        context=fixture_server(mode)
        base,calls,_=context.__enter__()
        self.addCleanup(lambda: context.__exit__(None,None,None))
        adapter=self.adapter(base)
        adapter.mcp.initialize()
        adapter.mcp.list_tools()
        self.assertEqual(adapter.identities.mcp,Status.READY)
        return adapter,calls

    def test_malformed_success_does_not_install_session_or_stay_ready(self):
        for mode,secret in (('poison-json','private-server-response'),('dual-rpc','private-server-response'),
                            ('string-id','id-type-mismatch'),('nan-result','private-server-response')):
            with self.subTest(mode=mode):
                adapter,calls=self._ready_catalog(mode)
                before=len(calls)
                with self.assertRaises(AdapterError) as error:
                    adapter.mcp.providers()
                self.assertNotIn(secret,str(error.exception))
                self.assertNotIn(secret,repr(error.exception))
                self.assertNotEqual(adapter.identities.mcp,Status.READY)
                self.assertFalse(adapter.mcp._initialized)
                self.assertIsNone(adapter.mcp._catalog)
                self.assertNotIn('poison',adapter.mcp._session_id or '')
                self.assertNotIn('after-dual',adapter.mcp._session_id or '')
                self.assertNotIn('id-type',adapter.mcp._session_id or '')
                self.assertNotIn('nan-session',adapter.mcp._session_id or '')
                with self.assertRaises(AdapterError):
                    adapter.mcp.providers()
                self.assertEqual(len(calls),before+1)
                self.assertNotIn('poison-session-id',calls[-1]['headers'].get('Mcp-Session-Id',''))

    def test_notification_error_body_does_not_mark_ready_and_empty_body_still_does(self):
        with fixture_server('notify-error') as (base,calls,_):
            adapter=self.adapter(base)
            with self.assertRaises(AdapterError) as error:
                adapter.mcp.initialize()
            self.assertEqual(error.exception.reason,'rpc_error')
            self.assertNotIn('private-server-response',str(error.exception))
            self.assertNotEqual(adapter.identities.mcp,Status.READY)
            self.assertFalse(adapter.mcp._initialized)
            self.assertIsNone(adapter.mcp._session_id)
            self.assertEqual(len(calls),2)
        with fixture_server('notify-benign') as (base,calls,_):
            adapter=self.adapter(base)
            adapter.mcp.initialize()
            self.assertEqual(adapter.identities.mcp,Status.READY)
            self.assertEqual(len(calls),2)

    def test_folded_or_quoted_session_is_rejected_without_replay(self):
        class Scripted:
            def __init__(self, session):
                self.session,self.calls=session,[]
            def request(self, method, path, headers, **kwargs):
                self.calls.append(dict(headers))
                body=json.dumps({'jsonrpc':'2.0','id':1,'result':{'protocolVersion':'2025-06-18','capabilities':{},
                                 'serverInfo':{'name':'fixture','version':'0'}}}).encode()
                return body,{'mcp-session-id':self.session}
        with fixture_server() as (base,calls,_):
            for session in ('good\r\n X-Boundary-Inject: pwned','session "quoted" value'):
                with self.subTest(session=session):
                    adapter=self.adapter(base)
                    scripted=Scripted(session)
                    adapter.mcp._http=scripted
                    with self.assertRaises(AdapterError) as error:
                        adapter.mcp.initialize()
                    self.assertEqual(error.exception.reason,'invalid_session_header')
                    self.assertNotIn('Boundary-Inject',str(error.exception))
                    self.assertNotIn('quoted',str(error.exception))
                    self.assertIsNone(adapter.mcp._session_id)
                    self.assertNotEqual(adapter.identities.mcp,Status.READY)
                    self.assertEqual(len(scripted.calls),1)
                    self.assertNotIn('Mcp-Session-Id',scripted.calls[0])
                    with self.assertRaises(AdapterError):
                        adapter.mcp.list_tools()
                    self.assertEqual(len(scripted.calls),1)
            self.assertEqual(calls,[])

    def test_archive_rejects_control_and_drive_names_without_extracting(self):
        from research.ignition_adapter.archive import checked_archive
        def zipped(name):
            data=io.BytesIO()
            with zipfile.ZipFile(data,'w') as archive:
                archive.writestr('project.json',b'{"title":"Fixture"}')
                stored='views/Xevil.json' if '\x00' in name else name
                archive.writestr(stored,b'private-server-response')
            raw=data.getvalue()
            if '\x00' in name:
                raw=raw.replace(b'views/Xevil.json', name.encode('utf-8'))
            return raw
        for name in ('views/\r\n/evil.json','views/\x00evil.json','C:/Windows/system32/evil.json'):
            with self.subTest(name=name):
                with self.assertRaises(AdapterError) as error:
                    checked_archive(zipped(name))
                self.assertEqual(error.exception.reason,'invalid_project_archive')
                self.assertNotIn('private-server-response',str(error.exception))
                self.assertNotIn('evil.json',str(error.exception))
        self.assertTrue(checked_archive(archive()).startswith(b'PK'))

    def test_vendored_beta_tag_excerpt_records_both_sources(self):
        raw=json.loads((Path(__file__).parents[1]/'research/ignition_adapter/beta1-tag-openapi-fields.json').read_text())
        self.assertEqual(raw['provenance']['field_names']['sha256'],
                         'd7461e7bc941eebac42f75c2992968dd03b26fce4c505aad4e72612af696e4e0')
        self.assertEqual(raw['provenance']['types']['sha256'],
                         'b2bfc2d59854d48f313e33dc22f7302e8647f2a3be1cf6d0a42cd1d73d8c0ec4')
        self.assertEqual(raw['read']['properties']['tags']['items']['type'],'string')
        self.assertEqual(raw['write']['properties']['tagPaths']['items']['type'],'string')
        self.assertEqual(raw['write']['properties']['values'],{'type':'array'})
        self.assertNotIn('additionalProperties',raw['read'])
        self.assertNotIn('type',raw['configuration'])
        self.assertNotIn('required',raw['configuration'])


if __name__=='__main__':unittest.main()
