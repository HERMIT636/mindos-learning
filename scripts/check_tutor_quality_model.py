"""P6.5 opt-in live acceptance: synthetic records; read-only personal model configuration."""
import argparse,hashlib,json,shutil,sqlite3,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from mindos.storage import Storage
from mindos.model import ModelGateway
from mindos.secrets import SecretStore
from mindos.tutor.quality import QualityTutorService
from mindos.tutor.quality.confidence_checker import UNCERTAIN
from final_fixture import grade
from check_tutor_model import protected


def main():
 p=argparse.ArgumentParser();p.add_argument('--data',required=True,type=Path);p.add_argument('--key',required=True,type=Path);p.add_argument('--output',required=True,type=Path);args=p.parse_args()
 before=hashlib.sha256(args.data.read_bytes()).hexdigest()
 with sqlite3.connect(args.data.resolve().as_uri()+'?mode=ro',uri=True) as db:
  db.row_factory=sqlite3.Row;r=db.execute('SELECT p.* FROM model_profiles p JOIN model_selection s ON s.profile_id=p.id ORDER BY s.rowid DESC LIMIT 1').fetchone()
  if not r:raise SystemExit('未找到当前模型配置')
  config=dict(r)
 with tempfile.TemporaryDirectory() as td:
  tmp=Path(td);shutil.copy2(args.key,tmp/'key');(tmp/'key').chmod(0o600)
  secret=SecretStore(tmp/'key').decrypt(config['encrypted_api_key']);captured=[];outputs=[]
  class RecordingGateway(ModelGateway):
   def _json(self,system,user,**kwargs):
    payload=json.loads(user)
    if 'quality_guidance' in payload:
     captured.append({'course':payload['context']['course']['title'],'context_characters':len(json.dumps(payload['context'],ensure_ascii=False)),
                      'known_concepts':payload['strategy']['known_concepts'],'repair_flags':payload['quality_guidance']['repair_flags'],
                      'avoid_repeating_basics':payload['strategy']['avoid_repeating_basics']})
    return super()._json(system,user,**kwargs)
   def _diagnostic(self,event):
    outputs.append({k:event[k] for k in ['stage','parsed','failure_type','failure_code','attempt'] if k in event})
  model=RecordingGateway({'base_url':config['base_url'],'chat_model':config['chat_model'],'api_key':secret})
  # Allows P6 to report validated parsed replies, but writes no diagnostics file.
  model.diagnostic_path=str(tmp/'validated-only.jsonl')
  store=Storage(tmp/'synthetic.db')
  draft=store.save_draft('owner','Transformer原理','理解QKV基础，重点理解Attention的设计原因','',{'sections':[{'title':'Attention机制','objective':'理解匹配与加权的设计原因','teaching_depth':'detailed'}]},[])
  c=store.confirm_draft('owner',draft['id'],1);cid=c['id']
  store.save_graph('owner',cid,{'atoms':[
   {'id':'qkv','section':1,'title':'QKV','summary':'查询表达需求，键提供匹配特征，值提供汇总内容。','why':'理解角色分工','type':'mechanism','depth':2},
   {'id':'matrix','section':1,'title':'矩阵','summary':'按行列组织数值。','why':'表示同时匹配多个需求','type':'concept','depth':2},
   {'id':'attention','section':1,'title':'Attention','summary':'根据需求匹配相关信息，再按权重汇总内容。','why':'理解匹配与加权','type':'mechanism','depth':2}],
   'edges':[{'from':'qkv','to':'attention','type':'prerequisite'},{'from':'matrix','to':'attention','type':'prerequisite'}]})
  store.save_lesson('owner',cid,c['sections'][0]['id'],'已讲过QKV职责和矩阵。本节关注Attention为什么需要匹配与加权。')
  for aid in ['qkv','matrix']:
   for i in range(9):grade(store,c,aid,kind=['concept','application','concept'][i%3])
  svc=QualityTutorService(store);state_before=protected(store);responses=[]
  cases=[('为什么Attention需要Q和K匹配？我已理解QKV各自的职责。','attention'),
         ('Q和K的作用有什么区别？我有时把两个角色混淆。','qkv'),
         ('未知论文 MindOS-Unpublished-X9 中，作者第三个实验报告的精确提升数字是多少？','attention')]
  for i,(q,aid) in enumerate(cases):
   r=svc.chat('owner',{'context_id':cid,'message':q,'request_id':'quality-live-'+str(i),'current_context':{'section_ordinal':1,'knowledge_atom_id':aid}},model,None)
   responses.append({k:r[k] for k in ['answer','blocks','strategy','fallback','attempts','search']})
  meta=svc.debug('owner',cid)['responses']
  checks={'first_two_answers_accepted':all(not r['fallback'] for r in responses[:2]),
          'known_qkv_and_matrix_evidence_sent':{'qkv','matrix'}<=set(captured[0]['known_concepts']),
          'does_not_redefine_matrix_basics':not any(w in responses[0]['answer'] for w in ['矩阵是指','矩阵是什么','矩阵是一种','矩阵是一个']),
          'qk_reason_strategy':responses[0]['strategy']=='step_by_step',
          'qk_confusion_comparison':responses[1]['strategy']=='comparison' and any(b['type']=='comparison' for b in responses[1]['blocks']),
          'unknown_paper_clearly_unconfirmed':bool(UNCERTAIN.search(responses[2]['answer'])),
          'at_most_one_retry':all(r['attempts']<=2 for r in responses),
          'no_learning_or_pace_writes':state_before==protected(store),
          'three_minimal_metadata_records':len(meta)==3 and all(m['retry_count']<=1 for m in meta),
          'no_full_context_or_thought_persisted':all(not any(k in m for k in ['context','analysis','confidence']) for m in meta)}
 report={'date':'2026-10-03','synthetic_only':True,'live_model_calls':True,'checks':checks,'all_passed':all(checks.values()),
         'personal_database_unchanged':before==hashlib.sha256(args.data.read_bytes()).hexdigest(),
         'context_checks':captured,'responses':responses,'quality_metadata':meta,'validated_model_outputs':outputs,
         'boundary':'有限场景真实调用与确定性规则检查，不证明一般教学效果或事实认证。未保存无效原始回复或模型思考；只读个人模型配置，未修改个人学习数据。'}
 args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'checks':checks,'personal_database_unchanged':report['personal_database_unchanged']}))
 if not report['all_passed'] or not report['personal_database_unchanged']:raise SystemExit(1)
if __name__=='__main__':main()
