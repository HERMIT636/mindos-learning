"""Synthetic goal requirements, never estimates of a real learner."""
import copy
from personal_fixture import PersonalModel,course,train
from mindos.learning.canonical import KnowledgeMappingEngine
from mindos.learning.growth import GrowthService
SUMMARY='查询表达当前需求，键提供用于匹配的特征，值提供匹配后读取的内容。'
def requirement(name='QKV',level='application',importance='critical',kind='knowledge'):
 return {'name':name,'type':kind,'required_level':level,'importance':importance,'description':SUMMARY if name=='QKV' else '在陌生任务中独立应用并说明理由。','concept_type':'mechanism'} if kind=='knowledge' else {'name':name,'type':kind,'required_level':level,'importance':importance,'description':'设计小型信息匹配方案并解释角色与步骤。'}
def graph(caps=None,edges=None):return {'goal_summary':'理解信息匹配，独立完成适当应用。','capabilities':caps or [requirement()],'dependencies':edges or []}
class GrowthModel(PersonalModel):
 def __init__(self,raw=None):super().__init__();self.raw=raw or graph();self.capability_calls=[];self.stage_calls=[];self.fail=False
 def growth_capabilities(self,payload):
  self.capability_calls.append(copy.deepcopy(payload))
  if self.fail:raise RuntimeError('synthetic unavailable')
  return copy.deepcopy(self.raw)
 def growth_stages(self,payload):
  self.stage_calls.append(copy.deepcopy(payload));caps=payload['capabilities']
  return {'stages':[{'title':'补齐并验证当前目标','objective':'先确认角色分工，再独立应用。','capability_ids':payload.get('program_order',[c['id'] for c in caps])}]}
 def growth_goal(self,store,user='owner',**kwargs):
  svc=GrowthService(store);g=svc.create(user,{'title':'LLM 信息匹配应用','description':'理解并应用QKV分工',**kwargs});g=svc.analyze(user,g['id'],self)['goal'];svc.analyze(user,g['id'],self,{'confirm':True,'draft_version':g['draft_version']});return svc,g['id']
def browser_seed(store,user):
 for i in range(3):
  c=course(store,'LLM历史基础 '+str(i+1),depth=1,user=user);train(store,c,user=user)
 current=course(store,'LLM当前目标课程',depth=2,user=user);train(store,current,n=8,user=user)
 KnowledgeMappingEngine(store).scan(user,current['id'],PersonalModel());return current
