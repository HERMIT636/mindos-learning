"""Select bounded, owned atom materials; no learner-state updates."""
import json,re
from .protocol import POLICY,resource_text,digest
from .service import ResourceService
class MultimodalTutorContextBuilder:
 def __init__(self,store):self.resources=ResourceService(store)
 def build(self,user,cid,aid,message,focus=None,grounded=False):
  self.resources.atom(user,cid,aid)
  focused=self.resources.mapped(user,cid,aid,focus) if focus else None
  if grounded and not focused:raise ValueError('只根据材料回答时，请先选择一份资料')
  result=[];excluded=[];remaining=POLICY['context']['max_resource_chars_total']
  if grounded:pool=[focused]
  else:
   with self.resources.store.connect() as db:rows=db.execute("SELECT r.id,m.role FROM knowledge_resources r JOIN atom_resource_mappings m ON r.id=m.resource_id WHERE r.user_id=? AND m.user_id=? AND m.course_id=? AND m.atom_id=? AND m.status='active' ORDER BY r.updated_at DESC LIMIT 100",(user,user,cid,aid)).fetchall()
   pool=[{**self.resources.get(user,r['id']),'role':r['role']} for r in rows]
   words=set(re.findall(r'[A-Za-z0-9_]+|[\u4e00-\u9fff]{2}',message.lower()))
   def rank(r):return (r['id']==focus,r.get('role')=='primary_explanation',sum(w in (r['title']+' '+resource_text(r)[:500]).lower() for w in words),r['updated_at'])
   pool.sort(key=rank,reverse=True)
  for r in pool:
   value=resource_text(r)
   if not value:excluded.append({'id':r['id'],'reason':'资料未能读取，或是未提取正文的 PDF 原文件','status':r['status']});continue
   if len(result)>=POLICY['context']['max_resources_per_tutor_request'] or remaining<100:excluded.append({'id':r['id'],'reason':'本次资料数量或文字预算已满'});continue
   n=min(remaining,POLICY['context']['max_text_chars_per_resource']);clipped=value[:n];remaining-=len(clipped)
   result.append({'resource_id':r['id'],'title':r['title'],'type':r['resource_type'],'source_type':r['source_type'],'hash':r['content_hash'],'role':r.get('role','reference'),'text':clipped,'truncated':len(clipped)<len(value),'needs_review':r['source_type']=='generated' and (bool(r['metadata'].get('needs_review')) or r['metadata'].get('context_fingerprint')!=self.resources.fingerprint(user,cid,aid)),'pages':r['metadata'].get('pages')})
  return {'mode':'resource_only' if grounded else 'resources_and_course','focused_resource_id':focus,'resources':result,'excluded':excluded[:4],'scope':digest({'focus':focus,'grounded':grounded,'resources':[(r['resource_id'],r['hash']) for r in result]})}
