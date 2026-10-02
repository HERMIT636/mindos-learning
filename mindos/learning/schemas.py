"""Schemas for new model outputs; graph IDs receive additional semantic checks."""
CHECK_SCHEMA={'type':'object','required':['questions'],'additionalProperties':False,'properties':{'questions':{'type':'array','minItems':2,'maxItems':2,'items':{
 'type':'object','required':['prompt','choices','answer','explanation','atom_ids','assessment_type'],'additionalProperties':False,
 'properties':{'prompt':{'type':'string','minLength':8,'maxLength':800},'choices':{'type':'object','required':['a','b','c','d'],'additionalProperties':False,'properties':{k:{'type':'string','minLength':1,'maxLength':1000} for k in 'abcd'}},
 'answer':{'enum':['a','b','c','d']},'explanation':{'type':'string','minLength':1,'maxLength':2000},'atom_ids':{'type':'array','minItems':1,'maxItems':2,'items':{'type':'string'}},'assessment_type':{'enum':['concept','application','reasoning','math','transfer']},
 'misconceptions':{'type':'object','maxProperties':3,'additionalProperties':{'type':'object','required':['code','description'],'additionalProperties':False,'properties':{'code':{'type':'string','pattern':'^[A-Z][A-Z0-9_]{2,60}$'},'description':{'type':'string','minLength':1,'maxLength':400}}}}}
}}}}
