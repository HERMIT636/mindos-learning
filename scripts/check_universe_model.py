"""P7 live star-to-tutor acceptance; personal configuration is opened read-only."""
import argparse,hashlib,json,re,shutil,sqlite3,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from mindos.storage import Storage
from mindos.model import ModelGateway
from mindos.secrets import SecretStore
from mindos.tutor.quality import QualityTutorService
from mindos.universe import KnowledgeUniverseAdapter
from mindos.universe.universe_graph import star_id
from final_fixture import grade
from check_tutor_model import protected

def main():
 p=argparse.ArgumentParser();p.add_argument('--data',required=True,type=Path);p.add_argument('--key',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args();original=hashlib.sha256(a.data.read_bytes()).hexdigest()
 with sqlite3.connect(a.data.resolve().as_uri()+'?mode=ro',uri=True) as db:
  db.row_factory=sqlite3.Row;r=db.execute('SELECT p.* FROM model_profiles p JOIN model_selection s ON s.profile_id=p.id ORDER BY s.rowid DESC LIMIT 1').fetchone()
  if not r:raise SystemExit('未找到已选模型配置')
  config=dict(r)
 with tempfile.TemporaryDirectory() as td:
  tmp=Path(td);shutil.copy2(a.key,tmp/'key');(tmp/'key').chmod(0o600);secret=SecretStore(tmp/'key').decrypt(config['encrypted_api_key']);captured=[];outputs=[]
  class Gateway(ModelGateway):
   def _json(self,system,user,**kwargs):
    payload=json.loads(user)
    if 'quality_guidance' in payload:
     ctx=payload['context'];known=payload['strategy']['known_concepts'];atoms=ctx['knowledge_atoms']
     captured.append({'course':ctx['course']['title'],'selected_atom':ctx['current_context']['knowledge_atom_id'],'known_concepts':known,'context_bounded':len(json.dumps(ctx))<24000,'actual_target_evidence_count':next(x['knowledge_state']['graded_evidence_count'] for x in atoms if x['id']=='attention'),'actual_target_state':next(x['knowledge_state']['state'] for x in atoms if x['id']=='attention'),'misconceptions_from_independent_check':any(x['atom_id']=='attention' and x['status']=='confirmed' for x in ctx['misconceptions'])})
    return super()._json(system,user,**kwargs)
   def _diagnostic(self,event):
    outputs.append({k:event[k] for k in ['stage','parsed','failure_type','failure_code','attempt'] if k in event})
  model=Gateway({'base_url':config['base_url'],'chat_model':config['chat_model'],'api_key':secret});model.diagnostic_path=str(tmp/'validated-only')
  store=Storage(tmp/'synthetic.db');d=store.save_draft('owner','Transformer原理','理解Attention为什么先匹配再加权','',{'sections':[{'title':'Attention机制','objective':'先区分角色，再理解匹配与汇总原因','teaching_depth':'detailed'}]},[]);c=store.confirm_draft('owner',d['id'],1)
  store.save_graph('owner',c['id'],{'atoms':[{'id':'qkv','section':1,'title':'QKV','summary':'查询表示需求，键用于匹配，值提供内容。','why':'理解三个角色','type':'mechanism','depth':2},{'id':'attention','section':1,'title':'Attention','summary':'匹配需求与内容特征，再按权重汇总值。','why':'理解匹配与汇总设计','type':'mechanism','depth':2}],'edges':[{'from':'qkv','to':'attention','type':'prerequisite'}]});store.save_lesson('owner',c['id'],c['sections'][0]['id'],'已经介绍QKV职责，本节理解Attention匹配与加权的设计原因。')
  for i in range(9):grade(store,c,'qkv',kind=['concept','application','concept'][i%3])
  for i in range(3):grade(store,c,'attention',answer='b')
  universe=KnowledgeUniverseAdapter(store);before=protected(store);detail=universe.detail('owner',star_id(c['id'],'attention'))
  answer=QualityTutorService(store).chat('owner',{**detail['tutor_context'],'message':'请结合我当前的独立答题记录，说明哪些基础已有证据，哪些需要继续练习，再解释为什么Attention需要先匹配再加权。','request_id':'p7-live-attention'},model,None)
  text=answer['answer'];checks={'valid_live_answer':not answer['fallback'],'star_selected_attention':all(x['selected_atom']=='attention' and x['course']=='Transformer原理' for x in captured),'qkv_actual_known_sent':bool(captured) and 'qkv' in captured[0]['known_concepts'],'weak_target_independent_evidence_sent':bool(captured) and captured[0]['actual_target_evidence_count']==3 and captured[0]['misconceptions_from_independent_check'],'answer_acknowledges_existing_basics':'QKV' in text and bool(re.search('已经|已有|基础|通过|掌握',text)),'answer_identifies_need_for_practice':bool(re.search('练习|补强|混淆|不稳|回顾|继续',text)),'context_bounded':all(x['context_bounded'] for x in captured),'at_most_one_retry':answer['attempts']<=2,'read_and_tutor_do_not_change_learning':before==protected(store),'visual_state_only_qualitative':detail['mastery_state']=='unstable' and 'mastery' not in detail['atom']}
  report={'date':'2026-10-03','synthetic_only':True,'live_model_calls':True,'all_passed':all(checks.values()),'checks':checks,'context_checks':captured,'response':{k:answer[k] for k in ['answer','blocks','strategy','fallback','attempts','search']},'validated_model_outputs':outputs,'personal_database_unchanged':original==hashlib.sha256(a.data.read_bytes()).hexdigest(),'boundary':'临时合成课程，证据通过原有小测提交，个人数据库和模型配置只读。仅验证一个真实模型场景的上下文及运行结果，不证明一般教学效果。未保存密钥、模型思考或无效原始回复。'}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'checks':checks,'personal_database_unchanged':report['personal_database_unchanged']}))
 if not report['all_passed'] or not report['personal_database_unchanged']:raise SystemExit(1)
if __name__=='__main__':main()
