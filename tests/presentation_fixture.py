"""Readable deterministic teaching for presentation acceptance, not learner evidence."""

def presentation_reply(payload):
    action=payload['teaching_action'];mode=payload['mode']
    if action['action']=='VISUALIZE':forms=['diagram','concept','checkpoint']
    elif action['action']=='EXAMPLE':forms=['question','example','diagram','concept','checkpoint']
    elif mode=='lesson':forms=['question','diagram','concept','example','checkpoint']
    else:forms=['analogy','diagram','concept','example','checkpoint']
    blocks=[]
    for kind in forms:
        block={'type':kind}
        if kind=='question':block.update(title='两个人喜欢同一门课，关系怎么表示？',content='先想一想：小明和小红都喜欢数学。我们能用同一张图，清楚地表示这两件事吗？')
        elif kind=='diagram':block.update(title='把关系画出来',content='从人连向课程，每条线都表示一个“喜欢”的关系。\n\n图中的线有方向：小明喜欢数学，并不意味着数学也会喜欢小明。',data={
            'nodes':[{'id':'person1','label':'小明'},{'id':'math','label':'数学课'},{'id':'person2','label':'小红'},{'id':'pair','label':'有序对（小红，数学）'}],
            'edges':[{'from':'person1','to':'math','label':'喜欢'},{'from':'person2','to':'math','label':'喜欢'},{'from':'person2','to':'pair','label':'记录这条关系'}]})
        elif kind=='concept':block.update(title='关系是一份有方向的配对记录',content='集合用来描述“有哪些对象”。例如，学生集合里有小明和小红，课程集合里有数学和英语。\n\n关系用来描述“哪些对象之间存在某种联系”。如果小明喜欢数学，就把（小明，数学）记下来。\n\n这样的配对叫有序对。前面的位置是学生，后面的位置是课程；交换顺序后，含义就变了。这正是理解关系时要先弄清楚的地方。')
        elif kind=='example':block.update(title='用两条真实关系来练习',content='学生集合：小明、小红。课程集合：数学、英语。\n\n如果只有小明喜欢数学、小红喜欢英语，那么实际关系只有这两条记录。\n\n1. （小明，数学）表示小明喜欢数学。\n2. （小红，英语）表示小红喜欢英语。\n\n不要把“可能组成的所有配对”与“实际发生的关系”混在一起。先看具体的联系，再决定记录哪些有序对。')
        elif kind=='analogy':block.update(title='换成点餐的例子想一想',content='你可以把关系想成点餐记录。\n\n菜单列出所有可选的菜，记录单只写顾客真正点过的菜。顾客和菜之间可以有很多可能的配对，真正留下来的只是其中一部分。')
        else:block.update(content='请用自己的话回答这两个问题：\n\n1. 如果小明喜欢数学，为什么要把学生写在有序对的前面？\n2. 可能的配对和实际发生的关系有什么区别？')
        blocks.append(block)
    return {'presentation_plan':{'intent':'relationship','reason':'用有方向的连线和点餐实例说明关系，避免只用定义解释','forms':forms},'blocks':blocks}
