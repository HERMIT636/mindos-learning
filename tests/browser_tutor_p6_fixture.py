"""Disposable course and synthetic P6 observation; no personal data or live model calls."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_prototype import PrototypeTests
import tutor_fixture
original=tutor_fixture.packet
def packet(payload):
 value=original(payload);message=payload['message']
 if '我不理解Q和K' in message:
  value['observations']=[{'atom_id':'a1','observation_type':'possible_gap','description':'可能还需要检查查询和键的职责','supporting_quote':message,'confidence':.7}]
 if '我喜欢先讲直觉' in message:
  value['memories']=[{'memory_type':'explanation_style','content':'先直觉再公式','supporting_quote':message}]
 return value
tutor_fixture.packet=packet
if __name__=='__main__':
 PrototypeTests.setUpClass();t=PrototypeTests();t.setUp()
 try:
  t.configure();store=t.server.storage;owner=t.session_id();ids=[]
  for title in ['Transformer导师验收课程','独立图论导师课程']:
   d=store.save_draft(owner,title,'理解机制与应用，逐步学习','',{'sections':[{'title':'Attention与QKV','objective':'理解匹配与加权，不急着推导'}]},[]);c=store.confirm_draft(owner,d['id'],1);ids.append(c['id'])
   store.save_graph(owner,c['id'],{'atoms':[{'id':'a1','section':1,'title':'QKV','summary':'查询描述需求，键提供匹配特征，值提供内容。','why':'区分角色和理解加权信息','type':'mechanism','depth':2}],'edges':[]});store.save_lesson(owner,c['id'],c['sections'][0]['id'],'从图书馆的检索需求与书籍标签理解查询、键和值的分工。')
  print(json.dumps({'url':t.url,'cookie':owner,'courses':ids}),flush=True);time.sleep(600)
 except KeyboardInterrupt:pass
 finally:PrototypeTests.tearDownClass()
