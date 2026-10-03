"""Owned GET-only universe routes; no client-supplied knowledge state."""
import re
from urllib.parse import urlsplit,parse_qs
from .universe_adapter import KnowledgeUniverseAdapter

def dispatch(handler):
    parsed=urlsplit(handler.path)
    if not (parsed.path=='/api/universe' or parsed.path.startswith('/api/universe/')):return False
    if handler.command!='GET':handler._json(405,{'error':'知识宇宙只提供只读查看'});return True
    user=handler._session();adapter=KnowledgeUniverseAdapter(handler.server.storage);query=parse_qs(parsed.query,keep_blank_values=True)
    allowed={'offset','chapter_id','search','relation_offset'}
    if set(query)-allowed or any(len(v)!=1 for v in query.values()):raise ValueError('宇宙查看参数无效，不能提供能力状态')
    def offset(key='offset'):
        value=query.get(key,['0'])[0]
        if not re.fullmatch(r'\d{1,7}',value):raise ValueError('分页位置无效')
        return int(value)
    if parsed.path=='/api/universe':result=adapter.search(user,query['search'][0]) if 'search' in query else adapter.all(user,offset())
    elif m:=re.fullmatch(r'/api/universe/course/([A-Za-z0-9_-]{1,100})',parsed.path):result=adapter.course(user,m[1],query.get('chapter_id',[None])[0],offset())
    elif m:=re.fullmatch(r'/api/universe/star/(s-[A-Za-z0-9_-]{1,498})',parsed.path):result=adapter.detail(user,m[1],offset('relation_offset'))
    else:handler._json(404,{'error':'知识宇宙入口不存在'});return True
    handler._json(200,result);return True
