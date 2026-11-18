"""Protocol regression tests, never Ignition runtime evidence or existing Gateways."""
import contextlib
import copy
import io
import json
from pathlib import Path
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
    routes = {'/data/api/v1/projects/export/{name}': {'get': {}},
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
                return self.reply(302, Location='/do-not-follow')
            if mode == 'denied':
                return self.reply(403, b'private-server-response Cookie=secret-value')
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
                return self.reply(200, {'results':[{'value':42.5,'quality':{'code':192}}]})
            if path == '/data/api/v1/tags/write':
                return self.reply(200, {'results':[{'code':192 if mode!='bad-quality' else 0}]})
            if path in ('/data/api/v1/tags/configuration','/data/api/v1/tags/import'):
                return self.reply(200, {'successCount':1,'failureCount':0 if mode!='partial-config' else 1,'failures':[]})
            if path == '/data/api/v1/tags/export':
                return self.reply(200, {'name':'Fixture','tagType':'Folder','tags':[]},'application/octet-stream')
            if path == '/data/catalyst-agent/mcp-servers/HarnessLab':
                message=json.loads(raw)
                if mode == 'mcp-missing':return self.reply(404)
                if mode == 'expired' and message['method']!='initialize':
                    return self.reply(404)
                if message['method']=='initialize':
                    return self.reply(200, {'jsonrpc':'2.0','id':message['id'],'result':CONTRACT['initialize']},Mcp_Session_Id='fixture-session-secret')
                if message['method']=='notifications/initialized':
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
        for base,flag in [('http://127.0.0.1:8088',True),('http://example.com:18088',True),('http://127.0.0.1:18088',False)]:
            with self.subTest(base=base),self.assertRaises(AdapterError):
                LabTarget(base,'2027.2.0-beta1',isolated_test_gateway=flag)

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
                a.rest.import_project(changed,allow_overwrite=True,disposable_project=True)
                self.assertEqual(a.rest.export_project(),changed)
                a.rest.import_project(original,allow_overwrite=True,disposable_project=True)
                self.assertEqual(a.rest.export_project(),original)
                self.assertEqual(calls[2]['path'],'/data/api/v1/projects/import/FixtureProject?overwrite=true')
                self.assertEqual(calls[2]['headers']['Content-Type'],'application/zip')
                self.assertEqual(calls[2]['body'],changed)
                self.assertFalse(a.capabilities['atomic_project_write'])
                self.assertEqual(a.identities.perspective,Status.UNKNOWN)

    def test_import_needs_both_explicit_acknowledgements(self):
        with fixture_server() as (base,calls,_):
            a=self.adapter(base);a.rest.discover()
            for kwargs in [{},{'allow_overwrite':True},{'disposable_project':True}]:
                with self.assertRaises(AdapterError):a.rest.import_project(archive(),**kwargs)
            self.assertEqual(len(calls),1)

    def test_http_success_with_business_failure_is_not_accepted(self):
        with fixture_server('import-fails') as (base,calls,_):
            a=self.adapter(base);a.rest.discover()
            with self.assertRaises(AdapterError) as error:a.rest.import_project(archive(),allow_overwrite=True,disposable_project=True)
            self.assertEqual(error.exception.reason,'operation_failed')
            self.assertNotIn('private-server-response',str(error.exception))
            self.assertEqual(len(calls),2)

    def test_839_mcp_and_runtime_tag_writes_block_without_requests(self):
        with fixture_server() as (base,calls,_):
            a=self.adapter(base,'8.3.9')
            with self.assertRaises(AdapterError):a.mcp.initialize()
            with self.assertRaises(AdapterError):a.rest.write_values(['[default]Fixture/T'],[1],allow_gateway_write=True)
            self.assertEqual(calls,[])
            self.assertEqual(a.identities.mcp,Status.BLOCKED)

    def test_839_tag_configuration_import_export_have_verified_wire_shapes(self):
        with fixture_server() as (base,calls,_):
            a=self.adapter(base,'8.3.9');a.rest.discover()
            document={'tags':[{'name':'T','tagType':'AtomicTag','valueSource':'memory','value':21.5}]}
            a.rest.import_tag_configuration('default','Fixture',document,collision_policy='MergeOverwrite',allow_gateway_write=True)
            result=a.rest.export_tag_configuration('default','Fixture')
            self.assertEqual(calls[-2]['path'],'/data/api/v1/tags/import?provider=default&type=json&collisionPolicy=MergeOverwrite&path=Fixture')
            self.assertEqual(calls[-2]['headers']['Content-Type'],'application/octet-stream')
            self.assertEqual(json.loads(calls[-2]['body']),document)
            self.assertEqual(calls[-1]['path'],'/data/api/v1/tags/export?provider=default&type=json&path=Fixture')
            self.assertEqual(result['tagType'],'Folder')

    def test_beta_read_values_uses_get_json_body_and_write_is_distinct(self):
        with fixture_server() as (base,calls,_):
            a=self.adapter(base);a.rest.discover()
            self.assertEqual(a.rest.read_values(['[default]Fixture/T'])['results'][0]['value'],42.5)
            a.rest.write_values(['[default]Fixture/T'],[21.5],allow_gateway_write=True)
            self.assertEqual(calls[-2]['method'],'GET')
            self.assertEqual(json.loads(calls[-2]['body']),{'tags':['[default]Fixture/T']})
            self.assertEqual(json.loads(calls[-1]['body']),{'tagPaths':['[default]Fixture/T'],'values':[21.5]})

    def test_config_and_quality_failures_are_not_success_and_writes_are_not_retried(self):
        for mode in ['bad-quality','partial-config']:
            with self.subTest(mode=mode),fixture_server(mode) as (base,calls,_):
                a=self.adapter(base);a.rest.discover()
                with self.assertRaises(AdapterError):
                    if mode=='bad-quality':a.rest.write_values(['[default]Fixture/T'],[1],allow_gateway_write=True)
                    else:a.rest.configure_tags('default','Fixture',{'name':'T'},allow_gateway_write=True)
                self.assertEqual(len(calls),2)

    def test_catalyst_pagination_and_calls_keep_four_identity_states_separate(self):
        with fixture_server() as (base,calls,_):
            a=self.adapter(base);a.mcp.initialize();tools=a.mcp.list_tools()
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
            self.assertEqual(len(calls),1)

    def test_archive_patch_rejects_new_resource_and_invalid_zip(self):
        with self.assertRaises(AdapterError):patch_existing_view(archive(),VIEW.replace('Home','New'),{})
        with self.assertRaises(AdapterError):patch_existing_view(b'not zip',VIEW,{})


if __name__=='__main__':unittest.main()
