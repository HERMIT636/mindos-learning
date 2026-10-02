"""Disposable P2 report course with a fake provider; no user data."""
import sys,json,time,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_prototype import PrototypeTests,FakeProvider
from final_fixture import seed,FinalModel
from authentic_fixture import AuthenticModel
from mindos.learning.final import FinalAssessmentService
if __name__=='__main__':
 os.environ['MINDOS_DEBUG_LEARNING']='1';PrototypeTests.setUpClass();t=PrototypeTests();t.setUp()
 try:
  t.configure();FakeProvider.final_model=FinalModel();FakeProvider.authentic_model=AuthenticModel();course=seed(t.server.storage,t.session_id(),'开放能力验证演示课程');svc=FinalAssessmentService(t.server.storage);svc.complete_content(t.session_id(),course['id']);svc.defer(t.session_id(),course['id'],True)
  print(json.dumps({'url':t.url,'cookie':t.session_id()}),flush=True);time.sleep(600)
 except KeyboardInterrupt:pass
 finally:PrototypeTests.tearDownClass()
