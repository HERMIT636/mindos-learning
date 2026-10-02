"""P4 browser fixture uses temporary synthetic records and requirement responses."""
import sys,json,time,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_prototype import PrototypeTests
from growth_fixture import GrowthModel,browser_seed,graph,requirement
from mindos.server import MindOSHandler
if __name__=='__main__':
 os.environ['MINDOS_DEBUG_LEARNING']='1';PrototypeTests.setUpClass();t=PrototypeTests();t.setUp()
 try:
  t.configure();browser_seed(t.server.storage,t.session_id());model=GrowthModel(graph([requirement(),requirement('额外阅读',importance='optional')]));MindOSHandler._model=lambda self:model
  print(json.dumps({'url':t.url,'cookie':t.session_id()}),flush=True);time.sleep(600)
 except KeyboardInterrupt:pass
 finally:PrototypeTests.tearDownClass()
