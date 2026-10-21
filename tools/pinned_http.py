"""Direct website requests pinned to prevalidated addresses, with normal TLS trust.

A generic HTTP proxy may resolve the destination again. Without a proxy contract
that enforces the same address pin, website fetching must fail closed.
"""
import http.client
import socket
import ssl
import urllib.request


def require_direct_policy():
 proxies=urllib.request.getproxies()
 if any(proxies.get(scheme) for scheme in ('http','https','all')):
  raise ValueError('官网抓取在当前代理环境下无法安全固定目标地址；未尝试直连，请填写业务背景继续')


def connect_addresses(addresses,timeout):
 last=None
 for family,kind,proto,_,address in addresses:
  sock=None
  try:
   # Deliberately do not use create_connection: it resolves the hostname again.
   sock=socket.socket(family,kind,proto);sock.settimeout(socket.getdefaulttimeout() if timeout is socket._GLOBAL_DEFAULT_TIMEOUT else timeout);sock.connect(address)
   return sock
  except BaseException as error:
   if sock is not None:sock.close()
   if not isinstance(error,OSError):raise
   last=error
 if last:raise last
 raise OSError('No validated website addresses')


class PinnedHTTPConnection(http.client.HTTPConnection):
 def __init__(self,host,*,addresses,**kwargs):
  self.addresses=addresses;super().__init__(host,**kwargs)
 def connect(self):
  if self._tunnel_host:raise OSError('Proxy tunnels are not supported for pinned websites')
  self.sock=connect_addresses(self.addresses,self.timeout)


class PinnedHTTPSConnection(http.client.HTTPSConnection):
 def __init__(self,host,*,addresses,**kwargs):
  self.addresses=addresses;super().__init__(host,**kwargs)
  if self._context.verify_mode!=ssl.CERT_REQUIRED or not self._context.check_hostname:
   raise ValueError('Website TLS requires certificate and hostname verification')
 def connect(self):
  if self._tunnel_host:raise OSError('Proxy tunnels are not supported for pinned websites')
  sock=connect_addresses(self.addresses,self.timeout)
  try:self.sock=self._context.wrap_socket(sock,server_hostname=self.host)
  except BaseException:sock.close();raise


class PinnedHTTPHandler(urllib.request.HTTPHandler):
 def __init__(self,addresses):self.addresses=tuple(addresses);super().__init__()
 def http_open(self,req):
  def connection(host,**kwargs):return PinnedHTTPConnection(host,addresses=self.addresses,**kwargs)
  return self.do_open(connection,req)


class PinnedHTTPSHandler(urllib.request.HTTPSHandler):
 def __init__(self,addresses):self.addresses=tuple(addresses);super().__init__()
 def https_open(self,req):
  def connection(host,**kwargs):return PinnedHTTPSConnection(host,addresses=self.addresses,**kwargs)
  return self.do_open(connection,req,context=self._context,check_hostname=self._check_hostname)
