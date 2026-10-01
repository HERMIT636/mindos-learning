"""Temporary discovery fixture with simulated public-body transport; no real keys."""
import json
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from test_prototype import PrototypeTests, FakeProvider
from test_discovery import Provider
if __name__=='__main__':
    PrototypeTests.setUpClass();test=PrototypeTests();test.setUp()
    try:
        FakeProvider.discovery_demo=True
        PrototypeTests.server.discovery_provider_factory=lambda course:Provider()
        test.configure()
        print(json.dumps({'url':test.url,'cookie':test.session_id()}),flush=True)
        time.sleep(600)
    except KeyboardInterrupt:pass
    finally:PrototypeTests.tearDownClass()
