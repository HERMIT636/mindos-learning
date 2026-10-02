"""Synthetic-only P1 fixtures. Grades flow through Storage.submit_quiz."""
import json
from datetime import datetime,timezone
from mindos.model import ModelGateway

SCENARIOS=[
 ('救援中心要把求助信息交给合适的志愿者。每条消息描述需要，志愿者登记自己的技能，配对后取出联系资料。','在这个流程中，用来比对求助内容的登记信息承担哪一种角色？'),
 ('图书馆的新检索台收到读者的一句需求描述。系统先与书目主题比较，选出相关书，再返回书的介绍，读者无需知道专业分类。','为了按需求选择资料，主题标签和实际介绍应如何分工？'),
 ('农场的温室管理员安排浇水。先说明哪个区域缺水，再对照设备服务区域，找到设备后读取操作说明，而不是对所有区域统一处理。','哪些信息应先用于匹配需求，而不是直接作为最终读取的内容？'),
 ('美术馆策展人整理无标签的作品。观众表达想看的题材，策展人先根据作品特征挑选，再展示画作简介。选取依据和最终阅读内容需要分离。','如果把用于挑选的特征直接当作最终展示内容，会混淆哪种关系？'),
 ('校车调度要响应学生的乘车需求。出发时间与站点要求先和线路描述匹配，之后再取出相应司机的联系方式，不逐一通知所有司机。','用于选择线路的信息和取出的联络信息为什么不能完全等同？'),
 ('维修平台收到一份设备故障说明。系统将故障特征与技师能力标签比较，确定匹配后给出技师的联系方式。技术标签不是联系内容本身。','在这种陌生业务里，什么信息应该承担匹配条件的作用？'),
 ('博物馆的声音导览响应游客兴趣。先根据主题查找展品，再取出展品讲解音频；主题索引是匹配依据，音频才是交给游客的内容。','导览设计应怎样区分查找线索和被返回的内容？'),
 ('医院药房整理配送请求。需求描述先与可供应的类别匹配，匹配后取得具体配送单据；类别比较不直接替代配送内容。','哪种设计保留了匹配依据与最终内容的分工？'),
 ('社区工具共享站按居民的维修需求筛选工具。先比较用途，再读取所选工具的借用说明；用途和说明服务于不同步骤。','把全部借用说明直接用来表示居民需求，会产生什么分工问题？'),
 ('野外观察队要寻找适合拍摄的地点。拍摄要求先同场地特征比对，之后读取匹配地点的路线说明，不把路线本身当作要求。','应该怎样组织需求、特征和结果信息？')]

class FinalModel:
 def __init__(self):self.gateway=ModelGateway({});self.questions=0;self.transfers=0;self.logs=[];self.summaries=0;self.raw=[]
 def _validated_questions(self,*args,**kwargs):return self.gateway._validated_questions(*args,**kwargs)
 def _diagnostic(self,event):self.logs.append(event)
 def final_question(self,course,section,atom,dimension,previous,failure=''):
  self.questions+=1
  return {'questions':[{'prompt':f'第{self.questions}次独立检测中，关于{atom["title"]}，怎样的角色分工符合目标？','choices':dict(a='根据需要先匹配条件，再读取相应信息',b='条件和内容没有区别',c='忽略输入的需求',d='随机选择全部结果'),'answer':'a','explanation':'需求、匹配条件和最终读取内容各自承担不同职责，先匹配再取得内容。','atom_ids':[atom['id']],'assessment_type':'concept' if dimension=='retention' else dimension,'misconceptions':{'b':{'code':'ROLE_CONFUSION','description':'把匹配条件和取出的内容看成同一种职责'}}}]}
 def final_transfer(self,course,atom,previous,failure=''):
  scenario,question=SCENARIOS[self.transfers%len(SCENARIOS)];self.transfers+=1
  return {'scenario':scenario,'question':question,'target_atom_ids':[atom['id']],'rubric':[{'id':'match_role','criterion':'辨认用于匹配的条件角色'},{'id':'content_role','criterion':'区分匹配结果与读取内容'}],'expected_concepts':['需求与条件的比较','读取被选中的内容'],'difficulty':'standard','novelty_reason':'课程中的角色概念应用于没有讲过的实际任务，而非替换数字或变量。','choices':dict(a='先按需求匹配条件，再取得对应内容',b='把条件和内容看成相同职责',c='忽略需求并随机选择',d='所有信息只用于最终展示'),'answer':'a','explanation':'匹配条件帮助选择相关对象，最终读取的是被选中的信息，这两种作用不同。'}
 def final_report_summary(self,report,failure=''):
  self.summaries+=1
  return {'status':report['mastery_state']['status'],'summary':'你已经学完课程内容，但能力判断仍以独立答题证据为准。优先练习薄弱的概念与新情境，长期记忆仍需间隔后再独立验证。'}
 def learning_check(self,course,section,atom,purpose,misconceptions):
  data=[self.final_question(course,section,atom,d,[])['questions'][0] for d in ['concept','application']]
  return self._validated_questions({'questions':data},[],{atom['id']},required=True,count=2)

def seed(store,user='owner',title='终局测试课程',count=3):
 draft=store.save_draft(user,title,'从零理解，学会把方法用于陌生情境','',{'sections':[{'title':f'角色分工{n}','objective':'理解当前角色，不一次学完整门课程','core_atoms':[f'角色{n}']} for n in range(1,count+1)]},[])
 course=store.confirm_draft(user,draft['id'],1);cid=course['id']
 atoms=[{'id':f'a{n}','section':n,'title':f'角色{n}','type':'mechanism','summary':'需求用于表达任务，条件用于匹配，内容在匹配后取得。','why':'区分信息的职责','depth':2} for n in range(1,count+1)]
 store.save_graph(user,cid,{'atoms':atoms,'edges':[{'from':f'a{n}','to':f'a{n+1}','type':'prerequisite'} for n in range(1,count)]})
 for section in course['sections']:
  store.save_lesson(user,cid,section['id'],'需求描述当前任务，条件帮助比较，匹配后才读取相关内容。')
  if section['ordinal']<count:store.advance(user,cid,section['ordinal'])
 return course

def grade(store,course,atom,kind='concept',answer='a',user='owner',purpose='chapter_quiz',at=None,session='',model=None):
 model=model or FinalModel();target=store.atom(user,course['id'],atom,unlocked=True);section=course['sections'][target['section']-1]
 raw=model.final_question(course,section,target,kind,[])['questions'][0]
 if kind=='transfer':raw['assessment_type']='transfer'
 qs,ans=model._validated_questions({'questions':[raw]},[],{atom},required=True,count=1)
 quiz=store.create_quiz(user,course['id'],section['id'],qs,ans)
 with store.connect() as db:db.execute('UPDATE quizzes SET scope=?,assessment_kind=?,target_atom_id=?,loop_session_id=? WHERE id=?',('atom',purpose,atom,session,quiz['id']))
 from unittest.mock import patch
 with patch('mindos.storage.now',return_value=(at or datetime.now(timezone.utc)).isoformat()):store.submit_quiz(user,course['id'],quiz['id'],[answer],['high'])
 return quiz
