"""Small, strict material contracts. All supplied text is untrusted content."""
import hashlib,json,re
from pathlib import Path
POLICY=json.loads(Path(__file__).with_name('resource_policy.json').read_text())
TYPES={'text','formula','code','image','diagram','paper_excerpt','reference','practice'}
SOURCES={'generated','user_uploaded','course_content','external_reference','manual'}
ROLES={'primary_explanation','example','formula','visual','implementation','reference','practice','advanced','personal_note'}
DEFAULT_ROLES={'text':'primary_explanation','formula':'formula','code':'implementation','image':'visual','diagram':'visual','paper_excerpt':'reference','reference':'reference','practice':'practice'}
def digest(value):return hashlib.sha256(value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def text(value,limit=30000,empty=False):
 if not isinstance(value,str) or len(value)>limit or (not empty and not value.strip()):raise ValueError('资料文字为空或过长')
 return value.strip()
def url(value):
 from urllib.parse import urlsplit
 value=text(value,2000);p=urlsplit(value)
 if p.scheme not in {'http','https'} or not p.hostname or p.username or p.password:raise ValueError('参考地址必须是公开 HTTP(S) 地址')
 return value

def content(kind,value):
 if kind not in TYPES or not isinstance(value,dict):raise ValueError('资料类型或格式无效')
 result={}
 def strings(keys,required=()):
  for k in keys:
   if k in value:result[k]=text(value[k],30000 if k in {'text','code','prompt'} else 6000,empty=k not in required)
   elif k in required:raise ValueError('资料缺少 '+k)
 if kind in {'text','paper_excerpt'}:strings(['text','language'],['text'])
 elif kind=='formula':
  strings(['expression','explanation'],['expression']);result['format']=value.get('format','latex')
  if result['format'] not in {'latex','plain'}:raise ValueError('公式格式无效')
  variables=value.get('variables',{})
  if not isinstance(variables,dict) or len(variables)>30:raise ValueError('符号说明无效')
  result['variables']={text(k,80):text(v,500) for k,v in variables.items()}
 elif kind=='code':
  strings(['code','description','source'],['code']);language=value.get('language','text')
  if language not in {'text','python','javascript','sql','json','bash','cpp'}:raise ValueError('代码语言无效')
  result.update(language=language,runnable=False)
 elif kind=='image':strings(['alt','caption','source']);result['vision_status']='text_description_only'
 elif kind=='diagram':
  strings(['explanation']);nodes=value.get('nodes',[]);edges=value.get('edges',[])
  if not isinstance(nodes,list) or not 1<=len(nodes)<=12 or not isinstance(edges,list) or len(edges)>16:raise ValueError('图示最多 12 个节点、16 条连线')
  result['nodes']=[{'id':text(n.get('id'),60),'label':text(n.get('label'),100)} for n in nodes if isinstance(n,dict)]
  ids={n['id'] for n in result['nodes']}
  if len(ids)!=len(nodes):raise ValueError('图示节点重复或无效')
  result['edges']=[]
  for e in edges:
   if not isinstance(e,dict) or e.get('from') not in ids or e.get('to') not in ids:raise ValueError('图示连线无效')
   result['edges'].append({'from':e['from'],'to':e['to'],'label':text(e.get('label',''),120,True)})
 elif kind=='reference':
  strings(['description']);result['url']=url(value['url']) if value.get('url') else ''
  if not result['url'] and not value.get('document'):raise ValueError('参考资料需要地址')
 elif kind=='practice':
  strings(['prompt'],['prompt']);typ=value.get('task_type','explanation')
  if typ not in {'explanation','analysis','design','open_transfer'}:raise ValueError('实践类型无效')
  minutes=value.get('expected_time',10)
  if type(minutes) is not int or not 1<=minutes<=120:raise ValueError('预计时间无效')
  result.update(task_type=typ,expected_time=minutes,linked_authentic_type=typ)
 if set(value)-set(result)-{'document'}:raise ValueError('资料包含不支持的字段')
 return result

def resource_text(resource):
 p=resource['payload'];kind=resource['resource_type']
 if resource['status']!='ready' or resource['metadata'].get('document'):return ''
 if kind in {'text','paper_excerpt'}:return p['text']
 if kind=='formula':return p['expression']+'\n'+p.get('explanation','')+'\n'+json.dumps(p.get('variables',{}),ensure_ascii=False)
 if kind=='diagram':return '\n'.join(n['label'] for n in p['nodes'])+'\n'+json.dumps(p['edges'],ensure_ascii=False)+'\n'+p.get('explanation','')
 if kind=='code':return p['code']+'\n'+p.get('description','')
 if kind=='image':return '仅用户文字描述，文字模型未看到图片：\n'+p.get('alt','')+'\n'+p.get('caption','')
 if kind=='practice':return p['prompt']
 return '参考链接（未获取正文）：'+p['url']+'\n'+p.get('description','')
