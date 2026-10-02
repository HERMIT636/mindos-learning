"""Opt-in P4 model validation: read credential config only, use synthetic P3 inputs."""
import argparse,concurrent.futures,hashlib,json,shutil,sqlite3,sys,tempfile
from datetime import timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from mindos.model import ModelGateway
from mindos.secrets import SecretStore
from mindos.learning.growth_graph import TargetCapabilityGenerator,order
from mindos.learning.growth_planner import GrowthPlanner
from mindos.learning.growth_gap import GapAnalysisEngine
from mindos.learning.personal import PersonalKnowledgeProfileBuilder
from mindos.learning.state import empty
from mindos.learning.policy import clock,iso

def inputs_for(goal,graph):
    inputs={k:{} for k in ['canonical','profiles','courses','graphs','states','coverage','finals']}
    inputs.update(priors=[],misconceptions=[],authentic=[],reviews=[],mappings=[])
    maps=[];conditions={};builder=PersonalKnowledgeProfileBuilder(None);now=iso(clock())
    knowledge=[c for c in graph['capabilities'] if c['type'] in {'knowledge','application','transfer'}]
    for i,cap in enumerate(knowledge[:3]):
        canonical='synthetic-canonical-'+str(i)
        identity={'id':canonical,'canonical_name':cap['name'],'domain':'machine_learning','semantic_fingerprint':'synthetic-'+str(i)}
        inputs['canonical'][canonical]=identity;sources=[]
        condition=['strong','partial','conflicted'][i];conditions[cap['name']]=condition
        for n in range(3):
            cid=f'synthetic-course-{i}-{n}';atom='a'
            value=.93 if condition=='strong' else .45 if condition=='partial' else .93 if n==0 else .2
            state=empty(atom);state.update(mastery=value,understanding=value,application=value,transfer=None,confidence=.92,evidence_count=24,graded_evidence_count=24,last_graded_evidence_at=now,last_independent_success_at=now,last_success_at=now,next_review_at=iso(clock()+timedelta(days=365)),version=24)
            inputs['courses'][cid]={'id':cid,'title':cap['name']+' 合成课程','status':'active','sort_order':n,'deleted_at':None,'content_revision':1,'current_ordinal':1}
            inputs['graphs'][cid]={'atoms':[{'id':atom,'depth':3}]};inputs['states'][cid]={atom:state}
            inputs['finals'][cid]={'completion':{'eligible':False},'mastery_state':{'status':'not_assessed'}}
            inputs['coverage'].setdefault(canonical,[]).append({'course_id':cid,'atom_id':atom,'section':1,'title':inputs['courses'][cid]['title'],'course_status':'active','deleted':False,'unlocked':True})
            sources.append({'course_id':cid,'course_title':inputs['courses'][cid]['title'],'course_atom_id':atom,'depth':3,'source_course_deleted':False,'mapping_id':'m'+cid,'mapping_confidence':1,'state':state,'independent_evidence':24})
        inputs['profiles'][canonical]=builder.compute(identity,sources,{})
        maps.append({'id':'map'+str(i),'capability_id':cap['id'],'canonical_atom_id':canonical,'canonical_fingerprint':identity['semantic_fingerprint'],'status':'verified'})
    return inputs,maps,conditions

def run_case(title,kind,index,config,key,directory):
    logfile=directory/f'model-{index}.jsonl'
    model=ModelGateway({'base_url':config['base_url'],'chat_model':config['chat_model'],'api_key':key,'diagnostic_path':str(logfile)})
    goal={'id':'synthetic-goal-'+str(index),'title':title,'description':'希望独立理解与应用；只拆分目标所需能力，不推测用户现状。','goal_type':kind,'target_level':'application','goal_model_version':1,'weekly_time_budget_minutes':120,'deadline':None}
    graph=TargetCapabilityGenerator().generate(goal,model);order(graph)
    inputs,maps,conditions=inputs_for(goal,graph);analysis=GapAnalysisEngine().analyze(goal,graph,maps,inputs)
    plan=GrowthPlanner().build(goal,graph,analysis,inputs,model)
    positions={cid:s['ordinal'] for s in plan['stages'] for cid in s['capability_ids']}
    gaps={g['name']:g for g in analysis['gaps']};tasks={t['capability_id']:t for t in plan['tasks']}
    checks={'structured_capability_graph':graph['source']=='model_requirement',
        'hard_dependencies_valid':all(positions[e['from']]<=positions[e['to']] for e in graph['dependencies'] if e['relation']=='prerequisite'),
        'program_order_preserved':[cid for s in plan['stages'] for cid in s['capability_ids']]==plan['rationale']['dependency_order'],
        'required_critical_exists':any(c['importance']=='critical' for c in graph['capabilities']),
        'supporting_distinguished':any(c['importance']!='critical' for c in graph['capabilities']),
        'practice_explicit':kind!='competition' or any(c['type']=='practice' and c['importance']=='critical' for c in graph['capabilities']),
        'structured_stages':plan['organization']=='model_organization',
        'no_learner_scores_in_requirements':all(not any(k in c for k in ['mastery','confidence','current_level']) for c in graph['capabilities']),
        'program_gaps_from_synthetic_p3':len(conditions)==3 and all(gaps[name]['status']=={'strong':'sufficient','partial':'partial','conflicted':'conflicted'}[status] for name,status in conditions.items()),
        'strong_basics_not_relearned':all(tasks[gaps[name]['capability_id']]['status']=='completed' for name,status in conditions.items() if status=='strong'),
        'existing_course_reused':all(tasks[gaps[name]['capability_id']]['task_type']!='create_course' for name in conditions),
        'conflict_schedules_verification':all(tasks[gaps[name]['capability_id']]['task_type']=='cross_course_verify' for name,status in conditions.items() if status=='conflicted')}
    outputs=[]
    if logfile.exists():
        for line in logfile.read_text().splitlines():
            event=json.loads(line);outputs.append({k:event[k] for k in ['stage','raw','parsed','failure_reason','attempt'] if k in event})
    return {'goal':title,'checks':checks,'passed':all(checks.values()),'synthetic_conditions':conditions,'graph':graph,
        'gaps':[{k:g[k] for k in ['name','status','required_level','reason_code']} for g in analysis['gaps']],
        'stages':plan['stages'],'program_order':plan['rationale']['dependency_order'],
        'tasks':[{k:t[k] for k in ['title','task_type','status','reason_code']} for t in plan['tasks']],'model_outputs':outputs}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data',type=Path,required=True);p.add_argument('--key',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--profile-id');args=p.parse_args()
    before=hashlib.sha256(args.data.read_bytes()).hexdigest()
    with sqlite3.connect(args.data.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        row=db.execute('SELECT * FROM model_profiles WHERE id=?',(args.profile_id,)).fetchone() if args.profile_id else db.execute('SELECT p.* FROM model_profiles p JOIN model_selection s ON s.profile_id=p.id ORDER BY s.rowid DESC LIMIT 1').fetchone()
        if row is None and not args.profile_id:row=db.execute('SELECT * FROM model_profiles LIMIT 1').fetchone()
        if row is None:raise SystemExit('没有可读取的模型配置。')
        config=dict(row)
    with tempfile.TemporaryDirectory() as td:
        tmp=Path(td);shutil.copy2(args.key,tmp/'key');(tmp/'key').chmod(0o600)
        key=SecretStore(tmp/'key').decrypt(config['encrypted_api_key'])
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            jobs=[executor.submit(run_case,title,kind,index,config,key,tmp) for title,kind,index in [('掌握 LLM 推理优化','skill',1),('准备机器学习比赛','competition',2)]]
            results=[job.result() for job in jobs]
    report={'date':'2026-10-02','synthetic_only':True,'live_model_calls':True,'cases':results,'all_passed':all(r['passed'] for r in results),'personal_database_unchanged':before==hashlib.sha256(args.data.read_bytes()).hexdigest(),
        'boundaries':['只读模型配置，未读取个人课程或答题。','合成P3状态通过原有聚合函数计算，不写入个人数据库。','模型只分解要求与组织阶段；程序判断缺口、依赖、任务及完成。','能力路线不是职业或教育认证，也未证明是最优教育路径。']}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'all_passed':report['all_passed'],'checks':[r['checks'] for r in results],'personal_database_unchanged':report['personal_database_unchanged']},ensure_ascii=False))
    if not report['all_passed'] or not report['personal_database_unchanged']:raise SystemExit(1)
if __name__=='__main__':main()
