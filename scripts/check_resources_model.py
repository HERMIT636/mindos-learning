"""P8 opt-in real model acceptance; synthetic courses, personal config read-only."""
import argparse,hashlib,json,re,shutil,sqlite3,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(ROOT/'scripts')]
from mindos.storage import Storage
from mindos.model import ModelGateway
from mindos.secrets import SecretStore
from mindos.resources.service import ResourceService
from mindos.resources.tutor import ResourceTutorService
from resource_fixture import PAYLOADS
from final_fixture import grade
from check_tutor_model import protected

def main():
 p=argparse.ArgumentParser();p.add_argument('--data',required=True,type=Path);p.add_argument('--key',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args();dbhash=hashlib.sha256(a.data.read_bytes()).hexdigest();keyhash=hashlib.sha256(a.key.read_bytes()).hexdigest()
 with sqlite3.connect(a.data.resolve().as_uri()+'?mode=ro',uri=True) as db:
  db.row_factory=sqlite3.Row;row=db.execute('SELECT p.* FROM model_profiles p JOIN model_selection s ON s.profile_id=p.id ORDER BY s.rowid DESC LIMIT 1').fetchone()
  if not row:raise SystemExit('未找到已选模型配置')
  config=dict(row)
 captured=[];cases=[];validation=[]
 with tempfile.TemporaryDirectory() as td:
  tmp=Path(td);shutil.copy2(a.key,tmp/'key');(tmp/'key').chmod(0o600);secret=SecretStore(tmp/'key').decrypt(config['encrypted_api_key'])
  class Gateway(ModelGateway):
   def _json(self,system,user,**kwargs):
    q=json.loads(user);rc=q.get('context',{}).get('resource_context',{})
    if rc:captured.append({'course':q['context']['course']['title'],'atom':q['context']['current_context']['knowledge_atom_id'],'resource_ids':[r['resource_id'] for r in rc['resources']],'resource_types':[r['type'] for r in rc['resources']],'mode':rc['mode'],'allow_formulas':q['teaching_action']['allow_formulas'],'allowed_depth':q['teaching_action']['allowed_depth'],'required_blocks':q['strategy']['required_blocks'],'request_characters':len(user),'quality_guidance_present':'quality_guidance' in q,'question':q['message']})
    return super()._json(system,user,**kwargs)
   def _resource_diagnostic(self,event):validation.append(event)
   def _diagnostic(self,event):pass # Never save invalid raw replies or private configuration.
  gateway=Gateway({'base_url':config['base_url'],'chat_model':config['chat_model'],'api_key':secret})
  store=Storage(tmp/'synthetic.db');s=ResourceService(store)
  for index,(kind,question) in enumerate([('diagram','为什么 Q 和 K 要计算相似度？请结合当前图示解释。'),('formula','为什么要除以根号 d_k？请结合这个公式，先解释直觉。'),('text','这份我上传的笔记说“Q就是Value，K不参与匹配”，这种表述有什么问题？'),('failed','这份 PDF 讲了哪些内容？请只根据材料回答。')]):
   draft=store.save_draft('owner','Transformer材料验收 '+str(index+1),'理解 Attention 的匹配与缩放原因','',{'sections':[{'title':'Attention机制','objective':'理解 QKV 分工、匹配和缩放原因','teaching_depth':'detailed'}]},[]);c=store.confirm_draft('owner',draft['id'],1);cid=c['id'];store.save_graph('owner',cid,{'atoms':[{'id':'attention','section':1,'title':'Attention','summary':'匹配相关信息并加权汇总内容。','why':'理解匹配与汇总原因','type':'mechanism','depth':2}],'edges':[]});store.save_lesson('owner',cid,c['sections'][0]['id'],'当前小节学习 Attention 的匹配与缩放设计，先解释直觉。')
   # Actual independent evidence is produced only by the original grade submission.
   grade(store,c,'attention',answer='b');store.save_teaching_preferences('owner',cid,{'math_level':'advanced','preferred_style':['example']})
   if kind=='failed':r=s.upload('owner','Attention秘密推导.pdf',b'%PDF-broken')
   elif kind=='text':r=s.upload('owner','我的笔记.txt','Q就是Value，K不参与匹配。'.encode())
   else:r=s.create('owner',kind,'QKV匹配图' if kind=='diagram' else '缩放点积公式',PAYLOADS[kind],'manual')
   s.link('owner',cid,'attention',r['id']);before=protected(store);start=len(captured)
   answer=ResourceTutorService(store).chat('owner',{'context_id':cid,'current_context':{'section_ordinal':1,'knowledge_atom_id':'attention'},'focused_resource_id':r['id'],'resource_grounded':kind=='failed','message':question,'request_id':'p8-live-'+str(index)},gateway,None)
   text=answer['answer'];checks={'valid_answer_through_p65' if kind!='failed' else 'quality_path_and_safe_unreadable_response':not answer['fallback'] if kind!='failed' else answer['attempts'] in {1,2} and (not answer['fallback'] or not answer['saved']),'attempts_bounded':answer['attempts']<=2,'actual_selected_resource_context':all(x['atom']=='attention' and (r['id'] in x['resource_ids'] if kind!='failed' else not x['resource_ids']) for x in captured[start:]),'request_bounded':all(x['request_characters']<=26000 for x in captured[start:]),'quality_guidance_present':all(x['quality_guidance_present'] for x in captured[start:]),'learning_state_unchanged':before==protected(store)}
   if kind!='failed':checks['actual_quote_citation']=bool(answer['resource_citations'])
   if kind=='text':checks['uploaded_claim_not_auto_authority']=bool(re.search('错误|不对|不准确|不正确|不等|不是|不能|问题|应当|应该|实际上',text))
   if kind=='failed':checks['explicit_unreadable_not_filename_guess']=bool(re.search('无法读取|未能读取|没有足够|不能读取|没有.*正文|解析失败|未.*读取',text)) and not answer['resource_citations'];checks['no_search_fallback']=answer['search']['status']=='not_needed'
   cases.append({'case':kind,'checks':checks,'all_passed':all(checks.values()),'quality_meta':__import__('mindos.tutor.quality.integration',fromlist=['QualityTutorService']).QualityTutorService(store).debug('owner',cid),'response':{k:answer[k] for k in ['answer','blocks','strategy','attempts','fallback','resource_citations','resource_mode']}});print(json.dumps({'case':kind,'checks':checks},ensure_ascii=False),flush=True)
 report={'date':'2026-10-04','live_model_calls':True,'synthetic_only':True,'all_passed':all(c['all_passed'] for c in cases),'cases':cases,'context_checks':captured,'resource_validation':validation,'personal_database_unchanged':dbhash==hashlib.sha256(a.data.read_bytes()).hexdigest(),'personal_key_unchanged':keyhash==hashlib.sha256(a.key.read_bytes()).hexdigest(),'boundary':'四个临时合成材料场景，使用现有 ModelGateway 和 P6.5，实际小测提交生成基础证据。个人课程、配置、密钥均只读。不是一般教学效果、事实认证、图像理解或扫描 PDF OCR 的证明；不保存密钥、思考或无效原始回复。'}
 a.output.parent.mkdir(parents=True,exist_ok=True)
 history=a.output.with_name('learning-loop-p8-real-attempts-2026-10-04.json')
 trials=json.loads(history.read_text()) if history.exists() else []
 if a.output.exists():
  old=json.loads(a.output.read_text());summary={'cases':[{k:c[k] for k in ['case','checks','all_passed']} for c in old['cases']],'resource_validation':old.get('resource_validation',[]),'all_passed':old['all_passed']}
  if not trials or trials[-1]!=summary:trials.append(summary)
  history.write_text(json.dumps(trials,ensure_ascii=False,indent=2)+'\n')
 a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 if not report['all_passed'] or not report['personal_database_unchanged'] or not report['personal_key_unchanged']:raise SystemExit(1)
if __name__=='__main__':main()
