"""Real loopback Handler/HTTP/parser checks; outbound pages are synthetic only."""
import email.message
import http.client
import io
import json
import pathlib
import socket
import sys
import threading
from unittest.mock import patch

sys.path.insert(0,str(pathlib.Path.cwd()/'tools'))
import geo_flow as flow

OUT=pathlib.Path(__file__).resolve().parent

class Response(io.BytesIO):
    def __init__(self,body,kind):
        super().__init__(body.encode());self.headers=email.message.Message();self.headers['Content-Type']=kind

class Transport:
    def open(self,request,timeout=30):
        host=flow.urllib.parse.urlsplit(request.full_url).hostname
        if host=='sparse.example':return Response('<title>Sparse Brand | Shop</title>','text/html')
        if host=='unbranded.example':return Response('<html><body>'+('SYNTHETIC body details '*20)+'</body></html>','text/html')
        if host=='plain.example':return Response('SYNTHETIC plain details '*20,'text/plain')
        raise flow.urllib.error.URLError('SYNTHETIC private-error-not-for-client')

server=flow.http.server.ThreadingHTTPServer(('127.0.0.1',0),flow.Handler)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
rows=[]
def request(name,url,auth=True,origin=None):
    conn=http.client.HTTPConnection('127.0.0.1',server.server_port)
    headers={'Host':'127.0.0.1:8772','Content-Type':'application/json'}
    if auth:headers['Authorization']='Bearer '+flow.TOKEN
    if origin:headers['Origin']=origin
    conn.request('POST','/api/geo/inspect',json.dumps({'website':url,'market':'US'}),headers)
    r=conn.getresponse();row={'name':name,'status':r.status,'body':json.loads(r.read())};rows.append(row);conn.close();return row

real_dns=socket.getaddrinfo
def dns(host,*args,**kwargs):
    if host=='127.0.0.1':return real_dns(host,*args,**kwargs)
    return [(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1' if host=='localhost' else '93.184.216.34',443))]

try:
    with patch.object(flow.socket,'getaddrinfo',side_effect=dns),patch.object(flow.urllib.request,'build_opener',return_value=Transport()),patch.object(flow,'catalog') as catalog,patch.object(flow,'bridge') as bridge,patch.object(flow,'direct_bridge') as direct:
        sparse=request('sparse null','https://sparse.example/')
        assert sparse['status']==200 and sparse['body']['diagnosis']['score'] is None
        assert sparse['body']['brand']['needs_confirmation']
        missing=request('no brand metadata','https://unbranded.example/')
        assert missing['status']==200 and missing['body']['diagnosis']['score']==25
        assert missing['body']['brand']['source']=='domain_fallback' and missing['body']['brand']['needs_confirmation']
        plain=request('plain unknown','https://plain.example/')
        assert plain['status']==200 and plain['body']['diagnosis']['score'] is None
        assert plain['body']['diagnosis']['checks'][0]['status']=='unknown'
        denied=request('private DNS denied','http://localhost/')
        assert denied['status']==400 and 'diagnosis' not in denied['body']
        denied=request('origin denied','https://sparse.example/',origin='https://evil.example')
        assert denied['status']==401
        denied=request('no token denied','https://sparse.example/',auth=False)
        assert denied['status']==401
        failure=request('remote error sanitized','https://failure.example/')
        assert failure['status']==400 and 'private-error' not in json.dumps(failure['body'])
        catalog.assert_not_called();bridge.assert_not_called();direct.assert_not_called()
finally:
    server.shutdown();server.server_close();thread.join()
(OUT/'http-boundaries-summary.json').write_text(json.dumps({'synthetic':True,'real_loopback_http':True,'no_model_transport_called':True,'results':rows},ensure_ascii=False,indent=2))
print('PASS 7 actual HTTP boundary cases: sparse/null, no brand, plain/unknown, private DNS, Origin, token, sanitized failure; no models invoked.')
