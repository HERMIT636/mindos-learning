"""Voluntary timing browser acceptance on a disposable local database."""
import sys,json,time,os
from pathlib import Path
from datetime import timedelta
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_prototype import PrototypeTests
from growth_fixture import GrowthModel
from personal_fixture import course,PersonalModel
from mindos.server import MindOSHandler
from mindos.learning.execution import StudySessionService
from mindos.learning.policy import clock
if __name__=='__main__':
 os.environ['MINDOS_DEBUG_LEARNING']='1';PrototypeTests.setUpClass();t=PrototypeTests();t.setUp()
 try:
  t.configure();user=t.session_id();c=course(t.server.storage,title='LLM KV Cache 执行验收课程',user=user);model=GrowthModel();svc,gid=model.growth_goal(t.server.storage,user);plan=svc.generate(user,gid)['roadmap'];now=[clock()-timedelta(days=7)]
  study=StudySessionService(t.server.storage,lambda:now[0])
  for duration in [35,35]:
   s=study.start(user,{'course_id':c['id'],'planned_minutes':25})['session'];now[0]+=timedelta(minutes=duration);study.action(user,s['id'],'end',{'completion':'done','reason':'finished'})
  MindOSHandler._model=lambda self:model
  original_post=MindOSHandler._post
  def fixture_post(self):
   if self.path=='/__test__/interrupt-study':
    self._check_local_request();self._request_json();owner=self._session()
    if owner!=user:raise ValueError('测试用户无效')
    with self.server.storage.connect() as db:db.execute("UPDATE study_sessions SET last_checkpoint_at=? WHERE user_id=? AND status='active'",((clock()-timedelta(hours=4)).isoformat(),user))
    self._json(200,{'simulated':True});return
   return original_post(self)
  MindOSHandler._post=fixture_post
  print(json.dumps({'url':t.url,'cookie':user}),flush=True);time.sleep(600)
 except KeyboardInterrupt:pass
 finally:PrototypeTests.tearDownClass()
