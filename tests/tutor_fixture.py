"""Deterministic P6 output for tests, not a production teaching fallback."""
def packet(payload):
    ctx=payload['context'];strategy=payload['strategy']['name'];kind=payload['strategy']['required_blocks']
    text=f"这是 {ctx['course']['title']} 中 {ctx['current_context']['section_title']} 的问题。先理解问题的含义，再结合当前例子。"
    blocks=[]
    for t in kind:
        if t=='diagram':blocks.append({'type':'diagram','data':{'nodes':[{'id':'input','label':'当前问题'},{'id':'output','label':'理解联系'}],'edges':[{'from':'input','to':'output','label':'结合例子'}]}})
        elif t=='steps':blocks.append({'type':'steps','steps':['先明确当前问题要比较的对象。','再用一个简单例子理解联系。']})
        elif t=='comparison':blocks.append({'type':'comparison','columns':['对象','作用'],'rows':[['Q','表示要寻找的信息'],['K','表示可以匹配的信息']]})
        elif t=='example':blocks.append({'type':'example','content':'例如查找一本书：先确定需要的信息，再比较标签，最后选择对应内容。这能帮助理解当前知识的用途。'})
        elif t=='question':blocks.append({'type':'question','content':'先想一想：你希望从当前输入中找到什么信息？'})
    blocks.insert(0,{'type':'paragraph','content':text})
    return {'learning_relevant':True,'strategy':strategy,'message_type':'hint' if strategy=='socratic' else 'explanation','blocks':blocks,
            'related_atom_ids':[a['id'] for a in ctx['knowledge_atoms'][:1]],'observations':[],'memories':[]}
