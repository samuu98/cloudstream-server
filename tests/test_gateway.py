import importlib.util
import os
import sys
import unittest
from unittest.mock import patch, AsyncMock
from pathlib import Path
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
import httpx
from fastapi.testclient import TestClient

os.environ["API_TOKEN"] = "unit-test-token"
os.environ["DATA_DIR"] = "/tmp/cloudstream-unit-tests"
spec = importlib.util.spec_from_file_location("server", Path(__file__).parents[1] / "gateway/app.py")
server = importlib.util.module_from_spec(spec)
sys.modules["server"] = server
spec.loader.exec_module(server)

class ProxyTests(unittest.TestCase):
    def setUp(self):
        server.media.clear()
    def test_hls_variant_key_map_and_segments(self):
        text = '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="../key?k=1"\n#EXT-X-MAP:URI="init.mp4"\n720/index.m3u8\nsegment.ts?token=2\n'
        output = server.hls_rewrite(text, "https://cdn.example/live/master.m3u8", {"Referer":"https://site.example/"})
        self.assertNotIn("URI=\"../", output)
        urls = {item.url for item in server.media.values()}
        self.assertEqual(urls, {"https://cdn.example/key?k=1", "https://cdn.example/live/init.mp4", "https://cdn.example/live/720/index.m3u8", "https://cdn.example/live/segment.ts?token=2"})
        self.assertTrue(all(item.headers == {"Referer":"https://site.example/"} for item in server.media.values()))
    def test_dash_base_and_template_inheritance(self):
        xml = '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><BaseURL>assets/</BaseURL><Period><AdaptationSet><Representation id="v"><SegmentTemplate media="v-$Number%05d$.m4s?sig=ok" initialization="init.mp4"/></Representation></AdaptationSet></Period></MPD>'
        root = ET.fromstring(server.dash_rewrite(xml,"https://cdn.example/live/main.mpd",{}))
        template = root.find('.//{*}SegmentTemplate')
        self.assertIn('$Number%05d$',template.attrib['media'])
        self.assertEqual({item.url for item in server.media.values()}, {'https://cdn.example/live/assets/','https://cdn.example/live/assets/init.mp4','https://cdn.example/live/assets/v-$Number%05d$.m4s?sig=ok'})
        self.assertIn('<MPD ',server.dash_rewrite(xml,'https://cdn.example/live/main.mpd',{}))
        self.assertNotIn('/resource/', root.find('{*}BaseURL').text)
    def test_session_expiry_and_invalid_schemes(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException): server.register('file:///etc/passwd',{})
        first = server.register('https://cdn.example/a.m3u8',{})
        self.assertEqual(first,server.register('https://cdn.example/a.m3u8',{}))
    def test_auth_and_validation(self):
        with TestClient(server.app) as api:
            self.assertEqual(api.get('/api/providers').status_code,401)
            auth={'Authorization':'Bearer unit-test-token'}
            self.assertEqual(api.post('/api/provider/resolve',headers=auth,json={'provider':'X'}).status_code,422)
            self.assertEqual(api.get('/media/missing/resource').status_code,410)
    def test_lan_without_token_and_private_mode(self):
        with patch.object(server, 'AUTH_REQUIRED', False), patch.object(server, 'TOKEN', ''), patch.object(server, 'rpc', AsyncMock(return_value=[{'name': 'Test'}])):
            with TestClient(server.app) as api:
                self.assertEqual(api.get('/config').json(), {'authRequired': False})
                self.assertEqual(api.get('/api/providers').json()[0]['name'], 'Test')
                self.assertEqual(api.post('/api/provider/resolve', json={'provider':'X'}).status_code, 422)
        with patch.object(server, 'AUTH_REQUIRED', True):
            with TestClient(server.app) as api:
                self.assertTrue(api.get('/config').json()['authRequired'])
                self.assertEqual(api.get('/api/providers').status_code, 401)
                self.assertEqual(api.get('/api/providers', headers={'Authorization':'Bearer wrong'}).status_code, 401)
        with patch.object(server, 'AUTH_REQUIRED', True), patch.object(server, 'TOKEN', ''):
            with self.assertRaises(RuntimeError):
                with TestClient(server.app): pass

    def test_multiple_repositories_failure_and_duplicate_names(self):
        import asyncio
        repos=['https://example.org/a.json','https://example.org/b.json']
        async def exercise():
            old=server.bootstrap
            try:
                with patch.object(server,'REPOS',repos), patch.object(server,'rpc',AsyncMock(side_effect=[RuntimeError('offline'),{'repository':'B','plugins':[{'loaded':True}]}])) as rpc:
                    await server.import_repositories()
                    self.assertEqual(server.bootstrap['state'],'partial')
                    self.assertEqual(rpc.await_count,2)
                    self.assertEqual(server.bootstrap['result']['repositories'][0]['error'],'offline')
                server.bootstrap={'result':{'repositories':[{'url':u,'repository':label} for u,label in zip(repos,['A','B'])]}}
                data=[{'name':'Duplicate','id':str(i),'sourcePlugin':'/plugins/repo.'+str(server.repository_hash(u))+'/x.cs3'} for i,u in enumerate(repos)]
                with patch.object(server,'rpc',AsyncMock(return_value=data)):
                    result=await server.provider_list()
                    self.assertEqual([p['displayName'] for p in result],['Duplicate · A','Duplicate · B'])
                    self.assertNotEqual(result[0]['id'],result[1]['id'])
            finally: server.bootstrap=old
        asyncio.run(exercise())

    def test_relay_redirect_range_and_playlist(self):
        captured=[]
        def transport(request):
            data=__import__('json').loads(request.content)
            captured.append(data)
            if data['url']=='https://cdn.example/a':
                return httpx.Response(302,headers={'Location':'/b.m3u8'})
            return httpx.Response(200,headers={'Content-Type':'application/vnd.apple.mpegurl'},content=b'#EXTM3U\nseg.ts\n')
        with TestClient(server.app) as api:
            old=server.client
            server.client=httpx.AsyncClient(transport=httpx.MockTransport(transport))
            route=server.register('https://cdn.example/a',{'User-Agent':'Test'})
            result=api.get(route,headers={'Range':'bytes=0-'})
            self.assertEqual(result.status_code,200)
            self.assertIn('/media/',result.text)
            self.assertEqual(captured[1]['headers']['Range'],'bytes=0-')
            self.assertIn('https://cdn.example/seg.ts',{item.url for item in server.media.values()})
            server.client=old
    def test_dash_template_preserves_signed_query_with_slashes(self):
        captured=[]
        def transport(request):
            captured.append(__import__('json').loads(request.content)['url'])
            return httpx.Response(200,headers={'Content-Type':'video/mp4'},content=b'ftyp')
        with TestClient(server.app) as api:
            old=server.client
            server.client=httpx.AsyncClient(transport=httpx.MockTransport(transport))
            url='https://cdn.example/live/$RepresentationID$/seg-$Number%05d$.m4s?hdnts=acl=/live/ch-c5/c5.isml*~hmac=abc'
            route=server.register_template(url,{})
            expanded=route.replace('$RepresentationID$','v1').replace('$Number%05d$','00042')
            self.assertEqual(api.get(expanded).status_code,200)
            self.assertEqual(captured[0],'https://cdn.example/live/v1/seg-00042.m4s?hdnts=acl=/live/ch-c5/c5.isml*~hmac=abc')
            server.client=old
    def test_signed_dash_fragment_and_traversal(self):
        captured=[]
        def transport(request):
            data=__import__('json').loads(request.content); captured.append(data)
            return httpx.Response(206,headers={'Content-Type':'video/mp4','Content-Range':'bytes 0-3/100'},content=b'ftyp')
        with TestClient(server.app) as api:
            old=server.client
            server.client=httpx.AsyncClient(transport=httpx.MockTransport(transport))
            route=server.register('https://cdn.example/live/',{}).rsplit('/',1)[0]
            result=api.get(route+'/channel.isml*~hmac=abcd/QualityLevels(128000)/Fragments(audio=0)',headers={'Range':'bytes=0-3'})
            self.assertEqual(result.status_code,206)
            self.assertEqual(captured[0]['url'],'https://cdn.example/live/channel.isml*~hmac=abcd/QualityLevels(128000)/Fragments(audio=0)')
            self.assertEqual(api.get(route+'/%2e%2e%2fsecret').status_code,400)
            server.client=old

if __name__=='__main__': unittest.main()
