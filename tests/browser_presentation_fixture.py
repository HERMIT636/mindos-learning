"""Disposable algebra UI fixture with model-selected representations."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_prototype import PrototypeTests,FakeProvider

if __name__=='__main__':
    PrototypeTests.setUpClass();test=PrototypeTests();test.setUp()
    try:
        test.configure();FakeProvider.presentation_demo=True;store=test.server.storage
        draft=store.save_draft(test.session_id(),'代数结构与图论','从零理解基础，掌握期末解题方法','',{'sections':[
            {'title':'集合与关系','objective':'理解集合、有序对与关系','core_atoms':['集合','关系']},
            {'title':'图论中的关系','objective':'进入后续小节后再讨论图论'}]},[])
        course=store.confirm_draft(test.session_id(),draft['id'],1)
        print(json.dumps({'url':test.url,'cookie':test.session_id(),'course':course['id']}),flush=True);time.sleep(600)
    except KeyboardInterrupt:pass
    finally:PrototypeTests.tearDownClass()
