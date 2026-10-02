"""Disposable P3 related and ambiguous courses; no personal database."""
import sys,json,time,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_prototype import PrototypeTests
from personal_fixture import course,train,PersonalModel
from mindos.learning.canonical import KnowledgeMappingEngine
if __name__=='__main__':
 os.environ['MINDOS_DEBUG_LEARNING']='1';PrototypeTests.setUpClass();t=PrototypeTests();t.setUp()
 try:
  t.configure();store=t.server.storage;user=t.session_id();engine=KnowledgeMappingEngine(store)
  a=course(store,'Transformer历史基础',user=user);train(store,a,user=user)
  b=course(store,'LLM当前课程','Query-Key-Value',user=user);engine.scan(user,b['id'],PersonalModel())
  c=course(store,'LLM候选关联',summary='比较请求和各条记录的表示，选取相应信息。',user=user);engine.scan(user,c['id'],PersonalModel(confidence=.71))
  d=course(store,'LLM候选拒绝',summary='比较请求和各条记录的表示，选取相应信息。',user=user);engine.scan(user,d['id'],PersonalModel(confidence=.71))
  print(json.dumps({'url':t.url,'cookie':user}),flush=True);time.sleep(600)
 except KeyboardInterrupt:pass
 finally:PrototypeTests.tearDownClass()
