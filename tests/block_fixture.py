"""Deterministic protocol fixture, not a teaching quality substitute."""
def make_blocks(action,content='从零开始，先理解概念，再看一个具体例子。'):
    result=[]
    for kind in action['presentation']:
        block={'type':kind,'content':content,'title':'从零开始' if kind=='concept' else '当前知识'}
        if kind=='diagram':block['data']={'nodes':[{'id':'n1','label':'当前问题'},{'id':'n2','label':'理解原因'}],'edges':[{'from':'n1','to':'n2','label':'逐步解释'}]}
        if kind=='flow':block['data']={'steps':[{'label':'输入'},{'label':'处理'},{'label':'输出'}]}
        if kind=='comparison':block['data']={'columns':['方式一','方式二'],'rows':[{'label':'重点','values':['建立直觉','解释原理']}]}
        if kind=='formula':block.update(content='y = 2x',data={'symbols':[{'symbol':'x','meaning':'输入量'}],'steps':['将输入量乘以二']})
        if kind=='checkpoint':block['content']='请用自己的话说明当前概念有什么作用？'
        result.append(block)
    return result
