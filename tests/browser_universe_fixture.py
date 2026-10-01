"""Temporary evidence-backed universe UI fixture; no personal data or live model calls."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_prototype import PrototypeTests

if __name__=='__main__':
    PrototypeTests.setUpClass();test=PrototypeTests();test.setUp()
    try:
        test.configure();store=test.server.storage;user=test.session_id();ids=[]
        for title in ('Transformer深入理解','代数结构与图论'):
            sections=([{'title':'课程导引与预备知识','objective':'建立序列建模的直觉，不提前展开QKV计算','core_atoms':['序列建模'],'future_atoms':['QKV','Encoder']},
                       {'title':'Attention机制','objective':'理解Attention如何关注相关信息','core_atoms':['Attention','QKV'],'teaching_depth':'detailed'},
                       {'title':'Encoder结构','objective':'理解编码器组织方式','core_atoms':['Encoder'],'teaching_depth':'detailed'}] if not ids else
                      [{'title':'集合与关系','objective':'从零理解集合及关系'},{'title':'图论基础','objective':'掌握图论定义'}])
            draft=store.save_draft(user,title,'从零理解基础概念，并用例子解释解题方法','',{'sections':sections},[])
            course=store.confirm_draft(user,draft['id'],1);ids.append(course['id'])
        cid=ids[0]
        store.save_graph(user,cid,{'atoms':[
            {'id':'a1','title':'序列建模','section':1,'type':'concept','summary':'把有先后顺序的信息作为学习对象','why':'理解Transformer背景','depth':2},
            {'id':'a2','title':'Attention','section':2,'type':'mechanism','summary':'按相关程度分配关注的权重','why':'理解注意力机制','depth':2},
            {'id':'a3','title':'QKV','section':2,'type':'mechanism','summary':'查询、键和值，分别描述要找什么、如何匹配与提供什么信息','why':'理解信息匹配与汇总','depth':2},
            {'id':'a4','title':'Encoder','section':3,'type':'mechanism','summary':'逐层组织注意力与变换以表达输入','why':'理解编码器结构','depth':3}],
            'edges':[{'from':'a1','to':'a2','type':'prerequisite'},{'from':'a2','to':'a3','type':'related'},{'from':'a2','to':'a4','type':'prerequisite'}]})
        test.call('/api/sections/lesson',{'course_id':cid,'ordinal':1});test.call('/api/sections/advance',{'course_id':cid,'expected_ordinal':1});test.call('/api/sections/lesson',{'course_id':cid,'ordinal':2})
        store.learning_event(user,cid,['a2'],'read')
        section=store.course(user,cid)['sections'][1]
        for run in range(2):
            questions=[{'prompt':f'Attention理解题 {run}','assessment_type':'concept','atom_ids':['a2']}, {'prompt':f'QKV应用题 {run}','assessment_type':'application','atom_ids':['a3']}]
            quiz=store.create_quiz(user,cid,section['id'],questions,[{'answer':'b','explanation':'关注相关信息'},{'answer':'b','explanation':'区分查询、键与值'}]);store.submit_quiz(user,cid,quiz['id'],['b','a'])
        print(json.dumps({'url':test.url,'cookie':user,'courses':ids}),flush=True);time.sleep(600)
    except KeyboardInterrupt:pass
    finally:PrototypeTests.tearDownClass()
