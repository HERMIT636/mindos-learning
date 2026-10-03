"""Question-specific decisions layered over the read-only ATIE action."""
import re

class TutorStrategyEngine:
    def choose(self,message,context,action):
        # Continue an existing guide, but let a new explicit question change direction.
        guide=next((m for m in reversed(context['recent_dialogue']) if m.get('strategy')=='socratic' and m['role']=='assistant'),None)
        if context['assessment_mode']!='learning':name='socratic'
        elif re.search(r'报错|错误代码|调试|debug|Traceback',message,re.I):name='debugging'
        elif re.search(r'区别|比较|相同|一样|\bvs\b',message,re.I):name='comparison'
        elif re.search(r'总结|回顾|梳理',message):name='summary'
        elif re.search(r'举例|例子|案例',message):name='example'
        elif re.search(r'推导|证明|怎么想到|引导我|不理解.*softmax|为什么.*softmax',message,re.I):name='socratic'
        elif re.search(r'步骤|过程|怎么计算|如何|为什么.*[QK]|原因',message,re.I) or (re.search('为什么',message) and any(a['type']=='mechanism' for a in context['knowledge_atoms'])):name='step_by_step'
        elif re.search('没理解|不懂|不明白',message) and context['user_state']['cognitive_state']['status'] in {'unknown','weak'}:name='example'
        elif re.search(r'类比|比喻|通俗|直觉',message):name='analogy'
        elif guide and (re.search('口头自查回答',message) or not re.search(r'[?？]|什么|为什么|怎么|如何',message)):name='socratic'
        else:name='direct_explanation'
        required={'comparison':['comparison'],'step_by_step':['steps'],'example':['example'],'socratic':['question'],'debugging':['steps']}.get(name,[])
        if re.search('图示|看图|关系图',message) and name not in {'socratic','comparison'}:required=['diagram']
        known=[a['id'] for a in context['knowledge_atoms'] if (a['knowledge_state'].get('graded_evidence_count') or 0)>=3 and (a['knowledge_state'].get('understanding') or 0)>=.8]
        return {'known_concepts':known,'name':name,'required_blocks':required,'reason':'按当前问题、教学阶段及最近引导选择讲法',
                'avoid_repeating_basics':bool(known) or action.get('reduce_repeated_basics',False),
                'stage':'respond_then_guide' if name=='socratic' and guide else 'check_prerequisite_then_guide' if name=='socratic' else 'explain',
                'grade_user_answer':False}

class SocraticTutor:
    @staticmethod
    def instruction(strategy):
        return '先定性回应用户刚才的解释，再提出一个简短引导问题，不评分、不宣称掌握。' if strategy['stage']=='respond_then_guide' else '必要时先用一句话检查前置概念，然后只提出一个引导问题，等待用户回答。不同时给出完整解答，不评分。'
