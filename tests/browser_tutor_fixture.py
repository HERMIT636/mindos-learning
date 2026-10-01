"""Temporary assistant browser fixture, no production course writes."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from test_prototype import PrototypeTests
from test_course_tutor import Search
if __name__=='__main__':
    PrototypeTests.setUpClass();test=PrototypeTests();test.setUp()
    try:
        test.configure();store=PrototypeTests.server.storage;ids=[];PrototypeTests.server.assistant_search_factory=lambda mode:Search()
        for title in ['Attention课程','独立图论课程']:
            draft=store.save_draft(test.session_id(),title,'从零理解基本原理','',{'sections':[{'title':'Attention基础','objective':'从零理解'},{'title':'后续知识','objective':'继续深入'}]},[])
            course=store.confirm_draft(test.session_id(),draft['id'],1);cid=course['id'];ids.append(cid)
            store.save_graph(test.session_id(),cid,{'atoms':[{'id':'a1','section':1,'title':'Attention','summary':'根据信息的重要程度分配权重','why':'理解当前课程基础','type':'concept','depth':2},{'id':'a2','section':2,'title':'QKV','summary':'查询键和值表示','why':'后续深入理解','type':'concept','depth':2}], 'edges':[{'from':'a1','to':'a2','type':'prerequisite'}]})
            store.save_lesson(test.session_id(),cid,course['sections'][0]['id'],'## 基础内容\n这是当前课程的真实讲解。'+('\n\n循序渐进地建立直觉。'*90))
        print(json.dumps({'url':test.url,'cookie':test.session_id(),'courses':ids}),flush=True);time.sleep(600)
    except KeyboardInterrupt:pass
    finally:PrototypeTests.tearDownClass()
