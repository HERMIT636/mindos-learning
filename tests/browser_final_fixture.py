"""Synthetic P1 browser course; no live profiles or personal course records."""
import sys,json,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_prototype import PrototypeTests,FakeProvider
from final_fixture import seed,FinalModel
if __name__=='__main__':
 PrototypeTests.setUpClass();test=PrototypeTests();test.setUp()
 try:
  test.configure();FakeProvider.final_model=FinalModel();seed(test.server.storage,test.session_id(),'终局闭环演示课程');seed(test.server.storage,test.session_id(),'稍后检测课程')
  print(json.dumps({'url':test.url,'cookie':test.session_id()}),flush=True);time.sleep(600)
 except KeyboardInterrupt:pass
 finally:PrototypeTests.tearDownClass()
