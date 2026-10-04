import io,struct,zlib
from test_universe_p7 import make_course
from tutor_fixture import packet

def png():
 def chunk(tag,data):return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data)&0xffffffff)
 return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',2,2,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\x00'+b'\x6e\x92\xc0'*2)*2))+chunk(b'IEND',b'')
def pdf():
 from pypdf import PdfWriter
 from pypdf.generic import DecodedStreamObject,DictionaryObject,NameObject
 w=PdfWriter()
 for word in ['FIRST selected matching explanation','SECOND distinct unrelated document page','THIRD should not be sent unless selected']:
  p=w.add_blank_page(width=300,height=300);font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')});p[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):w._add_object(font)})});s=DecodedStreamObject();s.set_data(('BT /F1 12 Tf 20 200 Td ('+word+') Tj ET').encode());p[NameObject('/Contents')]=w._add_object(s)
 out=io.BytesIO();w.write(out);return out.getvalue()
class ResourceModel:
 chat_model='test-only'
 def __init__(self):self.calls=[]
 def resource_tutor_json(self,payload,repair_reason=''):
  import copy
  self.calls.append(copy.deepcopy(payload));v=packet(payload);sources=payload['context']['resource_context']['resources'];answerability='supported' if sources else 'insufficient'
  if not sources:v['blocks'][0]['content']='当前资料无法读取，没有足够信息回答这个问题。请提供可读的选页片段，再一起理解。'
  else:v['blocks'][0]['content']+='材料用于帮助理解当前问题，引用不等于事实认证。'
  return {'response':v,'resource_citations':[{'resource_id':sources[0]['resource_id'],'quote':sources[0]['text'][:40]}] if sources else [],'answerability':answerability}
 def resource_json(self,payload):
  self.calls.append(payload);kind=payload['type'];return {'title':'辅助材料','payload':PAYLOADS[kind]}
PAYLOADS={
 'text':{'text':'第一段介绍矩阵信息。\n\n第二段提供直观例子。'},
 'formula':{'expression':r'\operatorname{softmax}(QK^{T}/\sqrt{d_k})V','format':'latex','explanation':'缩放后匹配与加权。','variables':{'Q':'查询','K':'键','V':'内容','d_k':'向量维数'}},
 'code':{'language':'python','code':'def match(q, k):\n    return sum(a*b for a,b in zip(q,k))','description':'示例仅阅读，不执行。','runnable':False},
 'image':{'alt':'两列矩阵','caption':'用表格组织信息'},
 'diagram':{'nodes':[{'id':'q','label':'查询 Q 表达需求'},{'id':'k','label':'键 K 提供匹配特征'},{'id':'s','label':'相似度代表匹配程度'}],'edges':[{'from':'q','to':'s','label':'比对'},{'from':'k','to':'s','label':'比对'}],'explanation':'查询和键比对表达匹配程度。'},
 'paper_excerpt':{'text':'从原文实际提取的片段，不是全文。'},
 'reference':{'url':'https://en.wikipedia.org/wiki/Attention_(machine_learning)','description':'参考链接，未读取全文'},
 'practice':{'task_type':'explanation','prompt':'用自己的话解释为什么需要匹配信息。','expected_time':8}
}
