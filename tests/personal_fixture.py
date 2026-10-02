"""Synthetic P3 courses and semantic judges; real scores go through quiz submit."""
import copy,json
from final_fixture import FinalModel,grade
class PersonalModel(FinalModel):
 def __init__(self,relationship='same',confidence=.96):super().__init__();self.relationship=relationship;self.confidence=confidence;self.mapping_calls=[];self.invalid=False
 def mapping_judge(self,payload):
  self.mapping_calls.append(copy.deepcopy(payload))
  if self.invalid:raise ValueError('synthetic malformed output')
  relation='different' if payload['course_atom']['domain']!=payload['canonical']['domain'] else self.relationship
  return {'same_concept':relation=='same','confidence':self.confidence,'relationship':relation,'reasons':['根据定义、领域和教学上下文判断身份，而不是用户能力'],'conflicts':[]}
 def learning_check(self,course,section,atom,purpose,misconceptions):
  return self._validated_questions({'questions':[{'prompt':'某平台要响应一项新请求，先比较对象特征，再读取相应结果。这种流程应该怎样区分用于匹配的信息和最终返回的信息？' if i==0 else '管理员把所有内容平均提供给每项请求，完全忽略需求差异。关于这种方案的问题，下列解释中哪一项形成正确因果关系？','choices':{'a':'需求先与匹配特征比较，之后读取对应内容','b':'需求和最终内容没有任何区别','c':'不需要比较任何特征','d':'随机读取全部记录'},'answer':'a','explanation':'表达需求、匹配条件与最终提供内容分别承担不同职责。','atom_ids':[atom['id']],'assessment_type':'concept' if i==0 else 'application'} for i in range(2)]},[],{atom['id']},required=True,count=2)
def course(store,title='Transformer基础',name='QKV',depth=2,user='owner',summary='查询表达当前需求，键提供用于匹配的特征，值提供匹配后读取的内容。'):
 d=store.save_draft(user,title,'理解需求与匹配条件，学会应用','',{'sections':[{'title':'信息匹配机制','objective':'理解需求、条件和内容的职责','core_atoms':[name]}]},[]);c=store.confirm_draft(user,d['id'],1)
 store.save_graph(user,c['id'],{'atoms':[{'id':'same-local-id','section':1,'title':name,'type':'mechanism','summary':summary,'why':'理解信息匹配的因果关系','depth':depth}],'edges':[]});store.save_lesson(user,c['id'],c['sections'][0]['id'],'查询表达当前需求，键用于匹配，值提供内容。')
 return c
def train(store,c,n=24,user='owner'):
 for i in range(n):grade(store,c,'same-local-id',kind=['concept','application','transfer'][i%3],user=user)
