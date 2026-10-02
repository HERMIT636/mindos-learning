"""Synthetic task/rubric responses for P2; never live learner answers."""
import copy
class AuthenticModel:
 def __init__(self,score=.82):self.calls=[];self.score=score;self.bad=False;self.invalid_quote=False;self.bad_weights=False;self.force_type=None;self.domain='水资源分配';self.structure='根据区域需求与土壤特征匹配后读取灌溉方案';self.logs=[]
 def _diagnostic(self,event):self.logs.append(event)
 def authentic_json(self,stage,payload):
  self.calls.append((stage,copy.deepcopy(payload)))
  if self.bad:raise RuntimeError('synthetic provider unavailable')
  if stage=='authentic_evaluation':
   return {'criteria':[{'id':c['id'],'passed':self.score>=.5,'score':self.score,'evidence':'没有出现在回答中的句子' if self.invalid_quote else payload['answer'][:18]} for c in payload['task']['rubric']['criteria']],'overall_score':.123,'confidence':.9,'misconception_candidates':[]}
  c=payload['context'];type_=self.force_type or c['task_type']
  prompt={'explanation':'请向第一次学习的同学解释信息需求、匹配条件、最终读取内容之间的因果关系。不能只翻译名词。',
   'analysis':'有人说匹配条件本身就是最终提供的内容，这样可以省掉读取过程。请找出这个说法的问题并解释原因。',
   'design':'设计一个社区工具分配的小方案：居民提交用途，工具登记能力，最终返回借用说明。说明各类信息的职责和完整步骤。',
   'open_transfer':'干旱地区需要分配水资源。管理员把各区域的需求与土壤特征比较，再取得对应灌溉方案。请自行说明怎样借鉴信息匹配原理，并解释比无差别平均分配好的原因。'}[type_]
  return {'task_type':type_,'atom_ids':[c['atom']['id']],'prompt':prompt,'rubric':{'criteria':[{'id':'matching','description':'说明需求与条件如何决定匹配','weight':.6},{'id':'retrieval','description':'说明最终读取内容及因果关系','weight':.7 if self.bad_weights else .4}]},'expected_concepts':['匹配条件','读取内容'],'forbidden_shortcuts':['不能只翻译术语'],'difficulty':c['difficulty'],'minutes':5,'source_domain':'课程信息匹配机制','target_domain':self.domain,'shared_principle':'先比较需求和条件，再读取匹配对象对应的内容','surface_difference':'从课程中的概念角色转移到区域水资源决策任务','novelty_reason':'场景和信息对象都改变，需要自主建立角色映射而不是选择选项','structure':self.structure}
