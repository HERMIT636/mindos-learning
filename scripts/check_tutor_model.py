"""Opt-in P6 live model acceptance using only synthetic course/evidence and read-only config."""
import argparse,hashlib,json,shutil,sqlite3,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from mindos.storage import Storage
from mindos.model import ModelGateway
from mindos.secrets import SecretStore
from mindos.tutor.service import TutorService
from final_fixture import grade

def protected(store):
 with store.connect() as db:return {t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in ['knowledge_states','learning_evidence','learning_misconceptions','study_sessions','task_execution_events','pace_snapshots','growth_tasks']}
def main():
 p=argparse.ArgumentParser();p.add_argument('--data',required=True,type=Path);p.add_argument('--key',required=True,type=Path);p.add_argument('--output',required=True,type=Path);args=p.parse_args();before=hashlib.sha256(args.data.read_bytes()).hexdigest()
 with sqlite3.connect(args.data.resolve().as_uri()+'?mode=ro',uri=True) as db:
  db.row_factory=sqlite3.Row;r=db.execute('SELECT p.* FROM model_profiles p JOIN model_selection s ON s.profile_id=p.id ORDER BY s.rowid DESC LIMIT 1').fetchone()
  if not r:raise SystemExit('未找到当前模型配置')
  config=dict(r)
 with tempfile.TemporaryDirectory() as td:
  tmp=Path(td);shutil.copy2(args.key,tmp/'key');(tmp/'key').chmod(0o600);secret=SecretStore(tmp/'key').decrypt(config['encrypted_api_key']);logs=tmp/'model.jsonl'
  captured=[]
  class RecordingGateway(ModelGateway):
   def tutor_json(self,payload,repair_reason=''):
    captured.append({'course':payload['context']['course']['title'],'context_characters':len(json.dumps(payload['context'],ensure_ascii=False)),'known_concepts':payload['strategy']['known_concepts'],'avoid_repeating_basics':payload['strategy']['avoid_repeating_basics'],'state_source':payload['context']['user_state']['cognitive_state']['source']})
    return super().tutor_json(payload,repair_reason)
  model=RecordingGateway({'base_url':config['base_url'],'chat_model':config['chat_model'],'api_key':secret,'diagnostic_path':str(logs)})
  store=Storage(tmp/'synthetic.db');draft=store.save_draft('owner','Transformer原理','理解QKV基础，重点理解Attention的设计原因','',{'sections':[{'title':'Attention机制','objective':'理解匹配与加权的设计原因','teaching_depth':'detailed'}]},[]);c=store.confirm_draft('owner',draft['id'],1);cid=c['id'];graph={'atoms':[{'id':'same-local-id','section':1,'title':'QKV','summary':'查询表达需求，键提供匹配特征，值提供汇总内容。','why':'理解角色分工','type':'mechanism','depth':2}],'edges':[]}
  graph['atoms'].append({'id':'attention','section':1,'title':'Attention','summary':'根据当前需求匹配相关信息，再按权重汇总内容。','why':'理解注意力机制为什么需要匹配与加权','type':'mechanism','depth':2});graph['edges']=[{'from':'same-local-id','to':'attention','type':'prerequisite'}];store.save_graph('owner',cid,graph);store.save_lesson('owner',cid,c['sections'][0]['id'],'已讲过查询、键和值的职责。本节关注Attention为什么需要匹配与加权。')
  for i in range(9):grade(store,c,'same-local-id',kind=['concept','application','concept'][i%3])
  svc=TutorService(store);protected_before=protected(store);questions=['我已经理解QKV各自的职责，但有时仍会把Q当成K。为什么Attention需要先匹配再加权汇总？','Q和K的作用有什么区别？','我不理解softmax，能引导我想清楚吗？'];responses=[]
  for i,q in enumerate(questions):
   r=svc.chat('owner',{'context_id':cid,'message':q,'request_id':'live-'+str(i),'current_context':{'section_ordinal':1,'knowledge_atom_id':'attention' if i==0 else 'same-local-id'}},model,None)
   responses.append({k:r[k] for k in ['answer','blocks','strategy','fallback','attempts','search','observations']})
  events=[json.loads(line) for line in logs.read_text().splitlines()] if logs.exists() else []
  # The saved diagnostics contain model outputs, never request context or keys.
  outputs=[{k:e[k] for k in ['stage','raw','parsed','failure_reason','failure_type','attempt'] if k in e} for e in events]
  checks={'all_live_answers_schema_valid':all(not r['fallback'] for r in responses),'question_specific_strategy':[r['strategy'] for r in responses]==['step_by_step','comparison','socratic'],'correct_course_context_sent':all(c['course']=='Transformer原理' for c in captured),'verified_basics_not_forced_to_relearn':captured[0]['avoid_repeating_basics'] and 'same-local-id' in captured[0]['known_concepts'],'context_bounded':all(c['context_characters']<24000 for c in captured),'first_answer_focuses_on_reason':any(w in responses[0]['answer'] for w in ['相关','匹配','需求','权重']),'comparison_visible':any(b['type']=='comparison' for b in responses[1]['blocks']),'single_socratic_question':sum(b['type']=='question' for b in responses[2]['blocks'])==1,'learning_and_execution_unchanged':protected_before==protected(store)}
 report={'date':'2026-10-03','synthetic_only':True,'live_model_calls':True,'checks':checks,'all_passed':all(checks.values()),'personal_database_unchanged':before==hashlib.sha256(args.data.read_bytes()).hexdigest(),'context_checks':captured,'responses':responses,'model_outputs':outputs,'boundary':'使用临时合成课程和经原有小测提交的基础证据，只读取真实模型配置；这是有限场景的运行验证，不证明一般教学效果或误区诊断准确率。'}
 args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'checks':checks,'personal_database_unchanged':report['personal_database_unchanged']}))
 if not report['all_passed'] or not report['personal_database_unchanged']:raise SystemExit(1)
if __name__=='__main__':main()
