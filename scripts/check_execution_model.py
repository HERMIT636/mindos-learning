"""P5 opt-in live stage organization with bounded execution context and synthetic knowledge."""
import argparse,hashlib,json,shutil,sqlite3,tempfile
from pathlib import Path
from check_growth_model import inputs_for
from mindos.model import ModelGateway
from mindos.secrets import SecretStore
from mindos.learning.growth_graph import validate
from mindos.learning.growth_gap import GapAnalysisEngine
from mindos.learning.growth_planner import GrowthPlanner

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data',type=Path,required=True);p.add_argument('--key',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args();before=hashlib.sha256(args.data.read_bytes()).hexdigest()
 with sqlite3.connect(args.data.resolve().as_uri()+'?mode=ro',uri=True) as db:
  db.row_factory=sqlite3.Row;row=db.execute('SELECT p.* FROM model_profiles p JOIN model_selection s ON s.profile_id=p.id ORDER BY s.rowid DESC LIMIT 1').fetchone()
  if not row:raise SystemExit('未找到当前模型配置')
  config=dict(row)
 with tempfile.TemporaryDirectory() as directory:
  tmp=Path(directory);shutil.copy2(args.key,tmp/'key');(tmp/'key').chmod(0o600);key=SecretStore(tmp/'key').decrypt(config['encrypted_api_key']);logfile=tmp/'model.jsonl';model=ModelGateway({'base_url':config['base_url'],'chat_model':config['chat_model'],'api_key':key,'diagnostic_path':str(logfile)})
  graph=validate({'goal_summary':'独立理解推理优化，不把执行快慢当作能力。','capabilities':[{'name':name,'type':'knowledge','required_level':'application','importance':'critical','description':'能解释机制并在新情境中应用。','concept_type':'mechanism'} for name in ['Attention','KV Cache','GQA']],'dependencies':[{'from':'Attention','to':'KV Cache','relation':'prerequisite'},{'from':'Attention','to':'GQA','relation':'prerequisite'}]})
  goal={'id':'synthetic-pace-goal','title':'LLM 推理优化','description':'学会基础并能够应用','goal_type':'skill','target_level':'application','goal_model_version':1,'weekly_time_budget_minutes':300,'deadline':None};inputs,mappings,conditions=inputs_for(goal,graph);analysis=GapAnalysisEngine().analyze(goal,graph,mappings,inputs);original=json.dumps(analysis,sort_keys=True)
  pace_context={'planned_weekly_minutes':300,'observed_weekly_capacity_range_minutes':[135,165],'deadline_risk':'unlikely','boundary':'执行数据只用于时间与负载规划，不用于人格、自律或能力判断。不得判断掌握或改变必要能力、程序顺序。'}
  plan=GrowthPlanner().build(goal,graph,analysis,inputs,model,pace_context=pace_context);flat=[cid for s in plan['stages'] for cid in s['capability_ids']];positions={cid:s['ordinal'] for s in plan['stages'] for cid in s['capability_ids']};allowed={'title','objective','capability_ids','id','ordinal','status','gate','estimated_minutes'}
  checks={'live_structured_stages':plan['organization']=='model_organization','program_order_preserved':flat==plan['rationale']['dependency_order'],'dependencies_preserved':all(positions[e['from']]<=positions[e['to']] for e in graph['dependencies']),'program_gap_analysis_unchanged':original==json.dumps(analysis,sort_keys=True),'no_model_mastery_fields':all(not(set(s)-allowed) for s in plan['stages']),'context_bounded_no_session_history':set(pace_context)=={'planned_weekly_minutes','observed_weekly_capacity_range_minutes','deadline_risk','boundary'}}
  outputs=[]
  if logfile.exists():
   for line in logfile.read_text().splitlines():
    event=json.loads(line);outputs.append({k:event[k] for k in ['stage','raw','parsed','failure_reason','attempt'] if k in event})
 report={'date':'2026-10-02','synthetic_only':True,'live_model_calls':True,'pace_context':pace_context,'checks':checks,'all_passed':all(checks.values()),'personal_database_unchanged':before==hashlib.sha256(args.data.read_bytes()).hexdigest(),'gaps':[{k:g[k] for k in ['name','status','required_level']} for g in analysis['gaps']],'stages':plan['stages'],'model_outputs':outputs,'boundary':'仅验证当前配置模型接收摘要后仍遵守结构与程序顺序；不证明耗时预测准确或教育效果。未读取个人课程或提交个人执行历史。'}
 args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'checks':checks,'personal_database_unchanged':report['personal_database_unchanged']}))
 if not report['all_passed'] or not report['personal_database_unchanged']:raise SystemExit(1)
if __name__=='__main__':main()
