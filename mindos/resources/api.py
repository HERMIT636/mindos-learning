"""Resource boundary routes; existing source search, tutor quality, assessment stay authoritative."""
import base64,binascii,os,re
from urllib.parse import urlsplit,parse_qs
from .service import ResourceService
from .generation import ResourceGenerator
from .tutor import ResourceTutorService
from .protocol import POLICY

def dispatch(h):
 parsed=urlsplit(h.path);path=parsed.path
 atom=re.fullmatch(r'/api/courses/([A-Za-z0-9_-]+)/atoms/([A-Za-z0-9_-]+)/resources(?:/(generate|[A-Za-z0-9_-]+/link))?',path)
 if not atom and not path.startswith('/api/resources'):return False
 user=h._session();svc=ResourceService(h.server.storage);method=h.command
 if method!='GET':h._check_local_request()
 if atom:
  cid,aid,op=atom.groups()
  if op is None and method=='GET':
   q=parse_qs(parsed.query,keep_blank_values=True)
   if set(q)-{'offset','search','type'} or any(len(v)!=1 for v in q.values()):raise ValueError('资料筛选参数无效')
   value=q.get('offset',['0'])[0]
   if not re.fullmatch(r'\d{1,6}',value):raise ValueError('资料页码无效')
   result=svc.list(user,cid,aid,int(value),q.get('search',[''])[0],q.get('type',[None])[0])
  elif op is None and method=='POST':result={'resource':svc.create_for_atom(user,cid,aid,h._request_json(80000))}
  elif op=='generate' and method=='POST':
   p=h._request_json()
   if set(p)-{'type','source_resource_id'}:raise ValueError('材料生成请求无效')
   result=ResourceGenerator(h.server.storage).generate(user,cid,aid,p.get('type'),h._model(),p.get('source_resource_id'))
  elif op and op.endswith('/link') and method in {'POST','DELETE'}:
   rid=op.split('/')[0];p=h._request_json()
   if set(p)-({'role'} if method=='POST' else set()):raise ValueError('资料关联字段无效')
   if method=='POST':result={'resource':svc.link(user,cid,aid,rid,p.get('role'))}
   else:svc.unlink(user,cid,aid,rid);result={'unlinked':True}
  else:h._json(405,{'error':'资料操作不支持此请求'});return True
 elif path=='/api/resources/upload' and method=='POST':
  p=h._request_json(POLICY['uploads']['max_pdf_bytes']*4//3+10000)
  if set(p)-{'filename','content_base64','alt','caption'}:raise ValueError('上传资料字段无效')
  try:data=base64.b64decode(p.get('content_base64',''),validate=True)
  except (ValueError,binascii.Error):raise ValueError('上传文件编码无效') from None
  r=svc.upload(user,p.get('filename'),data,p.get('alt',''),p.get('caption',''));result={'resource_id':r['id'],'resource':r}
 elif path=='/api/resources/tutor/chat' and method=='POST':
  try:model=h._model()
  except ValueError:model=None
  result=ResourceTutorService(h.server.storage).chat(user,h._request_json(16000),model,h.server.assistant_search_factory or h._search)
 elif m:=re.fullmatch(r'/api/resources/([A-Za-z0-9_-]+)(?:/(file|extract|inspect|reprocess|fetch))?',path):
  rid,op=m.groups()
  if op=='file' and method=='GET':p,mime=svc.file(user,rid);h._send(200,p.read_bytes(),mime);return True
  if op is None and method=='GET':result=svc.inspect(user,rid)
  elif op is None and method=='DELETE':
   p=h._request_json()
   if set(p)!={'confirm'}:raise ValueError('请确认永久删除资料')
   result=svc.delete(user,rid,p['confirm'])
  elif op=='fetch' and method=='POST':
   if h._request_json():raise ValueError('正文获取不接受客户端伪造内容')
   r=svc.get(user,rid)
   if r['resource_type']!='reference' or not r['payload'].get('url'):raise ValueError('请选择公开参考链接')
   from ..acquisition import fetch_public_document
   source=fetch_public_document(r['payload']['url'],r['title'])
   if not source.content:raise ValueError('未取得实际正文，保留参考链接')
   child=svc.create(user,'paper_excerpt',r['title']+' · 网页片段',{'text':source.content[:30000]},'external_reference',{'derived_from_resource_id':rid,'retrieved_at':source.created_time,'truncated':len(source.content)>30000},source_uri=r['payload']['url'])
   result={'resource':child}
  elif op in {'extract','reprocess'} and method=='POST':
   p=h._request_json()
   if set(p)!={'pages'}:raise ValueError('请选择 PDF 页码范围')
   result={'resource':svc.extract(user,rid,p['pages'])}
  elif op=='inspect' and method=='GET':
   if os.getenv('MINDOS_DEBUG_LEARNING')!='1':h._json(404,{'error':'接口不存在'});return True
   result=svc.inspect(user,rid)
  else:h._json(405,{'error':'资料操作不支持此请求'});return True
 else:h._json(404,{'error':'资料入口不存在'});return True
 h._json(200,result);return True
