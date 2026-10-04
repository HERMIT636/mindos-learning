"""Synthetic practice models; never claim real benchmark execution."""
import copy
from tutor_fixture import packet
from authentic_fixture import AuthenticModel
def definition(cid=None,aid=None):
 return {'milestones':[{'key':'m1','title':'建立基线','objective':'明确可复现环境','tasks':[{'key':'baseline','title':'记录基线','task_type':'document','estimated_minutes':20,'linked_course_id':cid,'linked_atom_id':aid}]},{'key':'m2','title':'实验与报告','objective':'比较观测并报告局限','tasks':[{'key':'experiment','title':'Tile实验','task_type':'experiment','description':'测试不同 tile 的延迟。','dependencies':['baseline'],'artifact_types':['benchmark'],'estimated_minutes':35,'linked_course_id':cid,'linked_atom_id':aid,'experiment':{'hypothesis':'较大 tile 可能减少访存，但需验证','setup':'在用户本机重复测试','variables':{'tile':32},'expected_result':'记录延迟 ms'}},{'key':'report','title':'整理报告','task_type':'document','dependencies':['experiment'],'artifact_types':['report'],'linked_course_id':cid,'linked_atom_id':aid}]}]}
class MissionModel(AuthenticModel):
 chat_model='test-only'
 def __init__(self,plan=None):super().__init__();self.plan=plan or definition();self.tutor_calls=[]
 def mission_plan_json(self,payload):self.calls.append(('mission_plan',copy.deepcopy(payload)));return copy.deepcopy(self.plan)
 def mission_review_json(self,payload):self.calls.append(('mission_review',copy.deepcopy(payload)));return {'observations':['可能需要补充测量条件并独立验证。'],'suggested_verification':'用一个新的场景说明并实现测量方案。'}
 def mission_tutor_json(self,payload,repair_reason=''):
  self.tutor_calls.append(copy.deepcopy(payload));v=packet(payload);ctx=payload['context']['practice_context'];artifacts=[a for a in ctx['artifacts'] if a['text']]
  if ctx['mode']=='artifact_only' and not artifacts:v['blocks'][0]['content']='这个产出无法读取，没有足够信息回答，请补充可读片段。'
  else:v['blocks'][0]['content']+='实验差异只能作为观测，访存和缓存只是可能解释，需要测量验证。'
  return {'response':v,'artifact_citations':[{'artifact_id':artifacts[0]['artifact_id'],'quote':artifacts[0]['text'][:45]}] if artifacts else [],'answerability':'supported' if artifacts or ctx['mode']!='artifact_only' else 'insufficient'}
def protected(store):
 with store.connect() as db:return {t:[tuple(r) for r in db.execute('SELECT * FROM '+t+' ORDER BY rowid')] for t in ['knowledge_states','learning_evidence','personal_knowledge_profiles','learning_misconceptions','learning_events','course_graphs']}
