"""Bounds unsupported claims, not a fact verifier or a numeric confidence score."""
import re
from .common import text

UNCERTAIN = re.compile(r'无法确认|不能确认|不能核实|尚未核实|不确定|没有.*(?:原文|资料|可靠)|未取得|需要.*(?:原文|来源)|无法核实|cannot confirm|not verified',re.I)
RESEARCH = re.compile(r'论文|paper|arxiv|最新|版本|新闻|发布日期|作者|API变化',re.I)
SPECIFIC = re.compile(r'(?:该|这篇|此|这项)(?:论文|研究|模型).{0,12}(?:提出|证明|表明|发现|发表|提升)|(?:作者是|发表于|实验结果|准确率.{0,8}\d|(?:提升|提高).{0,8}\d|发布日期是)|\d+(?:\.\d+)?\s*(?:%|个百分点|倍)|版本(?:号)?(?:为|是|：|:)\s*v?\d',re.I)

class ConfidenceChecker:
    def check(self,response,context,strategy,message='',search=None):
        search = search or {'status':'not_needed','sources':[]}
        content = text(response)
        sources = search.get('sources',[]) if search.get('status') == 'ok' else []
        urls = re.findall(r'https?://[^\s<>"）)]+',content)
        # A user-supplied link can be repeated without claiming its contents were read.
        provided = {s.get('url') for s in sources} | set(re.findall(r'https?://[^\s<>"）)]+',message))
        fabricated = any(url.rstrip('。,.') not in provided for url in urls)
        full_read = bool(re.search(r'我(?:已|已经)?(?:阅读|读过|核验).*全文|阅读全文(?:后|可知)|全文证明',content))
        risky = bool(RESEARCH.search(message))
        cautious = bool(UNCERTAIN.search(content))
        # Titles/snippets do not substantiate unknown experimental details, even with a disclaimer.
        claims = [sentence for sentence in re.split(r'[。！？\n]',content) if SPECIFIC.search(sentence)]
        unsupported_detail = risky and any(not any(normalize_detail(claim) in normalize_detail(s.get('description',''))
            for s in sources if s.get('description')) for claim in claims)
        missing_caution = risky and not sources and not cautious
        unsafe = fabricated or full_read or unsupported_detail or missing_caution
        return {'confidence':'low' if unsafe or (risky and not sources) else 'bounded',
                'approved':not unsafe,'suggest':'state_uncertainty_and_explain_only_stable_knowledge' if unsafe else ''}

def normalize_detail(value):
    return re.sub(r'\s+','',value)
