"""Disposable P7 browser data. Test-only diagnostics are never registered by the app."""
import hashlib,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(ROOT/'scripts')]
from test_prototype import PrototypeTests
from mindos.server import MindOSHandler
from final_fixture import grade
from check_tutor_model import protected
from mindos.universe.universe_graph import star_id
import tutor_fixture
original=tutor_fixture.packet
captured=[]
def packet(payload):
 captured.append({'context_id':payload['context']['course']['id'],'atom_id':payload['context']['current_context']['knowledge_atom_id']})
 return original(payload)
tutor_fixture.packet=packet
if __name__=='__main__':
 PrototypeTests.setUpClass();t=PrototypeTests();t.setUp()
 try:
  t.configure();store=t.server.storage;owner=t.session_id();courses=[]
  for title in ['Transformer宇宙验收','独立图论星系','大型知识星系']:
   d=store.save_draft(owner,title,'从零理解基础，逐步练习应用','',{'sections':[{'title':'Attention机制','objective':'理解匹配与加权的原因'},{'title':'后续进阶','objective':'继续学习，不提前展开'}]},[]);c=store.confirm_draft(owner,d['id'],1);courses.append(c)
   g={'atoms':[{'id':aid,'section':n,'title':name,'summary':summary,'why':'用于理解机制与应用','type':'mechanism','depth':2} for aid,n,name,summary in [('qkv',1,'QKV','查询表示需求，键用于匹配，值提供内容。'),('attention',1,'Attention','先匹配相关内容，再按权重汇总。'),('future',2,'Multi-head Attention','在后续小节逐步学习多组关注。')]],'edges':[{'from':'qkv','to':'attention','type':'prerequisite'},{'from':'attention','to':'future','type':'prerequisite'}]}
   store.save_graph(owner,c['id'],g);store.save_lesson(owner,c['id'],c['sections'][0]['id'],'本节已经学习QKV职责，重点理解Attention为什么需要匹配与加权。')
  first=courses[0]
  for i in range(9):grade(store,first,'qkv',user=owner,kind=['concept','application','concept'][i%3])
  grade(store,first,'attention',user=owner,answer='b')
  large=courses[2]
  with store.connect() as db:
   atoms=[{'id':'big'+str(i),'section':1,'title':'大图知识'+str(i),'summary':'已有索引，不自动证明掌握。','why':'查看已有知识结构','type':'concept','depth':2} for i in range(405)]
   db.execute('UPDATE course_graphs SET graph_json=? WHERE course_id=?',(json.dumps({'atoms':atoms,'edges':[{'from':'big'+str(i),'to':'big'+str(i+1),'type':'prerequisite'} for i in range(404)]}),large['id']))
  get=MindOSHandler._get;post=MindOSHandler._post
  def fixture_get(handler):
   if handler.path=='/api/p7-fixture':
    with store.connect() as db:
     extra={name:[tuple(r) for r in db.execute('SELECT * FROM '+name)] for name in ['learning_events','courses','course_atom_mappings','personal_knowledge_profiles']}
    digest=hashlib.sha256(json.dumps({'protected':protected(store),'extra':extra},sort_keys=True).encode()).hexdigest()
    handler._json(200,{'digest':digest,'calls':captured,'first_id':first['id'],'large_id':large['id']});return
   get(handler)
  def fixture_post(handler):
   if handler.path=='/api/p7-fixture-evidence':
    handler._request_json();grade(store,first,'attention',user=owner,answer='a');handler._json(200,{'saved':True});return
   post(handler)
  MindOSHandler._get=fixture_get;MindOSHandler._post=fixture_post
  print(json.dumps({'url':t.url,'cookie':owner}),flush=True);time.sleep(600)
 except KeyboardInterrupt:pass
 finally:PrototypeTests.tearDownClass()
