"""Pure quality decisions: never writes state, memories, observations or diagnostics."""
import json
from pathlib import Path
from .depth_checker import DepthChecker
from .repetition_checker import RepetitionChecker
from .alignment_checker import AlignmentChecker
from .confidence_checker import ConfidenceChecker

POLICY = json.loads(Path(__file__).with_name('quality_policy.json').read_text())
ADJUSTMENTS = {
    'too_deep':'保持当前 ATIE 深度上限，用直觉、图示或小例子替代公式和实现细节。',
    'too_basic':'用一句话回顾已独立验证的基础，重点解释用户问的原因或机制。',
    'repetition':'不要复制近期回答或重新完整定义已验证基础；简短回顾后进入当前困难点。',
    'goal_drift':'先回答原问题，再联系当前知识点与教学目标；压缩旁支内容。',
    'unsupported_certainty':'明确无法确认具体细节，只解释可确定的稳定知识；不要虚构引用、实验、作者或阅读全文。',
}

class TutorQualityController:
    def __init__(self,policy=None):
        self.policy = policy if policy is not None else POLICY
        if self.policy['max_retry'] != 1 or not 1 <= self.policy['max_history_context'] <= 10:
            raise ValueError('质量策略必须共用 P6 的一次重试，历史最多十轮')
    def evaluate(self,response,context,strategy,history,message='',action=None,search=None):
        flags=[]
        if self.policy['depth']['enabled']:
            result=DepthChecker().check(response,context,strategy,message,action)
            flags += [k for k in ('too_deep','too_basic') if result[k]]
        if self.policy['repetition']['enabled'] and RepetitionChecker().check(response,context,strategy,history,message,self.policy['max_history_context'])['duplicate']:
            flags.append('repetition')
        if self.policy['alignment']['enabled'] and not AlignmentChecker().check(response,context,strategy,message)['aligned']:
            flags.append('goal_drift')
        if self.policy['confidence']['enabled'] and not ConfidenceChecker().check(response,context,strategy,message,search)['approved']:
            flags.append('unsupported_certainty')
        return {'approved':not flags,'adjustments':[ADJUSTMENTS[f] for f in flags],
                'final_response':response if not flags else None,'quality_flags':flags}
