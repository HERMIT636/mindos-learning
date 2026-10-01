"""Interpret explicit requests as feedback, never assessment evidence."""
import re

def feedback_from_message(message):
    for kind,pattern in [
        ('formula_confusing',r'(?:公式|数学|推导).{0,12}(?:不懂|困惑|看不懂|难)|(?:不懂|看不懂).{0,12}(?:公式|推导)'),
        ('confused',r'不理解|没理解|没懂|不明白|听不懂'),
        ('visual',r'画图|图示|用图|流程图'),('example',r'例子|举例|案例'),
        ('rephrase',r'换个说法|换一种|重新解释'),('backtrack',r'补.*基础|前置知识|回到基础'),
        ('check',r'自查|检查理解|考考我'),('challenge',r'挑战|难一点'),
        ('review',r'复习|回顾'),('deepen',r'深入|推导|详细计算'),
    ]:
        if re.search(pattern,message):return kind
    return None
