"""Synthetic courses and elapsed time, isolated from personal learning data."""
import sys,json,time
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_prototype import PrototypeTests

def seed(test,title,old_days=0,repair=False,recent=False):
 store=test.server.storage;user=test.session_id();at=datetime.now(timezone.utc)-timedelta(days=old_days)
 draft=store.save_draft(user,title,'从零理解知识并练习应用','',{'sections':[{'title':'QKV角色','objective':'区分查询、键和值','core_atoms':['QKV']},{'title':'多头注意力','objective':'组合多个注意力结果','core_atoms':['Multi Head']}]},[]);course=store.confirm_draft(user,draft['id'],1);cid=course['id']
 store.save_graph(user,cid,{'atoms':[{'id':'a1','section':1,'title':'QKV','type':'mechanism','summary':'查询用于表达需求，键用于匹配，值提供内容。','why':'理解注意力的角色','depth':2},{'id':'a2','section':2,'title':'Multi Head','type':'mechanism','summary':'组合多组注意力结果。','why':'理解不同信息角度','depth':2}],'edges':[{'from':'a1','to':'a2','type':'prerequisite'}]})
 for section in course['sections']:
  store.save_lesson(user,cid,section['id'],'本节只讲当前角色与一个生活例子。');
  if section['ordinal']==1:store.advance(user,cid,1)
 for atom in ['a1','a2']:
  for trial in range(2):
   sec=course['sections'][0 if atom=='a1' else 1];quiz=store.create_quiz(user,cid,sec['id'],[{'prompt':'选择符合角色分工的正确表述。','choices':dict(a='正确角色',b='交换角色',c='忽略条件',d='所有角色相同'),'atom_ids':[atom],'assessment_type':'application'}],[{'answer':'a','explanation':'不同角色各自处理不同的信息。'}])
   with patch('mindos.storage.now',return_value=at.isoformat()):store.submit_quiz(user,cid,quiz['id'],['b' if repair else 'a'],['high'])
 if recent:
  with store.connect() as db:db.execute('UPDATE loop_activity SET last_active_at=? WHERE course_id=?',(datetime.now(timezone.utc).isoformat(),cid))
 return cid
if __name__=='__main__':
 PrototypeTests.setUpClass();test=PrototypeTests();test.setUp()
 try:
  test.configure();seed(test,'闭环补强课程',repair=True);seed(test,'间隔复习课程',old_days=14,recent=True);seed(test,'中断恢复课程',old_days=8)
  print(json.dumps({'url':test.url,'cookie':test.session_id()}),flush=True);time.sleep(600)
 except KeyboardInterrupt:pass
 finally:PrototypeTests.tearDownClass()
