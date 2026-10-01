"""Temporary courses for response races and visible content version checks."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_prototype import PrototypeTests
from test_knowledge import graph
from test_production import TEXT,candidate
from mindos.acquisition import DirectInputProvider
from mindos.production import normalize_candidate_result
if __name__=='__main__':
 PrototypeTests.setUpClass();test=PrototypeTests();test.setUp()
 try:
  test.configure();store=test.server.storage;courses=[]
  for title in ('响应保护课程A','响应保护课程B'):
   draft=store.save_draft(test.session_id(),title,'学习基础','',{'sections':[{'title':'概念基础','objective':'建立直觉'},{'title':'后续应用','objective':'掌握方法'}]},[])
   course=store.confirm_draft(test.session_id(),draft['id'],1);store.save_graph(test.session_id(),course['id'],graph());courses.append(course['id'])
  source=store.save_source(test.session_id(),courses[0],DirectInputProvider().acquire(title='新定义资料',text=TEXT))
  result=normalize_candidate_result(candidate(source,'概念 1'),source,1,source['metadata']['blocks'],{'a1','a2'})
  store.save_batch(test.session_id(),courses[0],source['id'],1,result)
  print(json.dumps({'url':test.url,'cookie':test.session_id(),'courses':courses}),flush=True);time.sleep(600)
 except KeyboardInterrupt:pass
 finally:PrototypeTests.tearDownClass()
