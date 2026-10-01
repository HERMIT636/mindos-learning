"""Independent temporary ATIE browser course."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_prototype import PrototypeTests
if __name__=='__main__':
 PrototypeTests.setUpClass();test=PrototypeTests();test.setUp()
 try:
  test.configure();store=PrototypeTests.server.storage
  draft=store.save_draft(test.session_id(),'ATIE浏览器课程','从零理解Attention和QKV','',{'sections':[{'title':'Attention机制','objective':'建立直觉并理解QKV','core_atoms':['Attention','QKV'],'teaching_depth':'detailed'},{'title':'Encoder结构','objective':'理解编码器结构','core_atoms':['Encoder'],'teaching_depth':'detailed'}]},[])
  course=store.confirm_draft(test.session_id(),draft['id'],1);cid=course['id']
  store.save_graph(test.session_id(),cid,{'atoms':[{'id':'a1','section':1,'title':'Attention','type':'mechanism','summary':'关注相关信息','why':'建立直觉','depth':2},{'id':'a2','section':2,'title':'Encoder','type':'mechanism','summary':'编码结构','why':'理解模型结构','depth':3}],'edges':[{'from':'a1','to':'a2','type':'prerequisite'}]})
  print(json.dumps({'url':test.url,'cookie':test.session_id(),'course':cid}),flush=True);time.sleep(600)
 except KeyboardInterrupt:pass
 finally:PrototypeTests.tearDownClass()
