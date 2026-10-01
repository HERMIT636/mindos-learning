"""Temporary browser fixture for course management, isolated from real user data."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from test_prototype import PrototypeTests
from test_discovery import Provider
if __name__=='__main__':
    PrototypeTests.setUpClass();test=PrototypeTests();test.setUp()
    try:
        test.configure();PrototypeTests.server.discovery_provider_factory=lambda course:Provider()
        store=PrototypeTests.server.storage;ids=[]
        for title in ['图论课程','代数课程','Python课程']:
            draft=store.save_draft(test.session_id(),title,'掌握基础解题方法','',{'sections':[{'title':'基础','objective':'从零理解'},{'title':'应用','objective':'动手练习'}]},[])
            ids.append(store.confirm_draft(test.session_id(),draft['id'],1)['id'])
        print(json.dumps({'url':test.url,'cookie':test.session_id(),'courses':ids}),flush=True);time.sleep(600)
    except KeyboardInterrupt:pass
    finally:PrototypeTests.tearDownClass()
