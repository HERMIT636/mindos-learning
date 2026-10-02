"""Derived personal snapshots and teaching-only priors. No KnowledgeState writes."""
import json,secrets,math
from .canonical import POLICY,KnowledgeMappingEngine,atom_context,normalized
from .final import fingerprint
from .policy import clock,date,iso
SCHEMA='''
CREATE TABLE IF NOT EXISTS personal_knowledge_profiles (
 user_id TEXT NOT NULL,canonical_atom_id TEXT NOT NULL REFERENCES canonical_knowledge_atoms(id),profile_json TEXT NOT NULL,
 source_hash TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(user_id,canonical_atom_id)
);
CREATE TABLE IF NOT EXISTS inherited_knowledge_priors (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,course_id TEXT NOT NULL REFERENCES courses(id),course_atom_id TEXT NOT NULL,
 canonical_atom_id TEXT NOT NULL REFERENCES canonical_knowledge_atoms(id),mapping_id TEXT NOT NULL REFERENCES course_atom_mappings(id),
 profile_snapshot_json TEXT NOT NULL,prior_strength TEXT NOT NULL,status TEXT NOT NULL,reason_codes_json TEXT NOT NULL,
 source_courses_json TEXT NOT NULL,scope_json TEXT NOT NULL,source_hash TEXT NOT NULL,quiz_id TEXT,
 created_at TEXT NOT NULL,verified_at TEXT,invalidated_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS current_inherited_prior ON inherited_knowledge_priors(user_id,course_id,course_atom_id) WHERE status!='invalidated';
CREATE INDEX IF NOT EXISTS prior_user ON inherited_knowledge_priors(user_id,canonical_atom_id,status);
'''
def migrate(db):db.executescript(SCHEMA)
LABELS={'unknown':'待验证','weak':'已有学习记录','moderate':'已有基础','strong':'较稳定','conflicted':'存在冲突','stale':'需要复习'}

class PersonalKnowledgeProfileBuilder:
 def __init__(self,store):self.store=store
 def _inputs(self,db,user):
  identities=[dict(r) for r in db.execute("SELECT * FROM canonical_knowledge_atoms WHERE user_id=? AND status='active'",(user,))]
  courses={r['id']:dict(r) for r in db.execute('SELECT * FROM courses WHERE session_id=?',(user,))}
  graphs={r['course_id']:json.loads(r['graph_json']) for r in db.execute('SELECT g.* FROM course_graphs g JOIN courses c ON c.id=g.course_id WHERE c.session_id=?',(user,))}
  sections={}
  for r in db.execute('SELECT s.* FROM sections s JOIN courses c ON c.id=s.course_id WHERE c.session_id=? ORDER BY s.ordinal',(user,)):sections.setdefault(r['course_id'],[]).append(dict(r))
  for c in courses.values():c['sections']=sections.get(c['id'],[])
  mappings=[dict(r) for r in db.execute("SELECT m.*,s.state_json,s.version FROM course_atom_mappings m LEFT JOIN knowledge_states s ON s.user_id=m.user_id AND s.course_id=m.course_id AND s.atom_id=m.course_atom_id WHERE m.user_id=? AND m.status='verified'",(user,))]
  evidence={}
  for r in db.execute("SELECT course_id,atom_id,COUNT(*) AS amount FROM learning_evidence WHERE user_id=? AND result IN ('correct','wrong') AND hint_used=0 AND COALESCE(json_extract(metadata_json,'$.reused_question'),0)=0 GROUP BY course_id,atom_id",(user,)):evidence[(r['course_id'],r['atom_id'])]=r['amount']
  calibrations={r['scope_id']:json.loads(r['result_json']) for r in db.execute("SELECT * FROM calibration_snapshots WHERE user_id=? AND scope_type='course' AND calibration_policy_version='calibration-v1'",(user,))}
  return identities,courses,graphs,mappings,evidence,calibrations
 def compute(self,identity,sources,calibrations,at=None):
  at=at or clock().replace(hour=0,minute=0,second=0,microsecond=0);config=POLICY['profile'];weighted=[];course_masses={};conflict=False
  for src in sources:
   s=src['state'];coverage=sum(s.get(k) is not None for k in ['understanding','application','transfer','retention'])/4
   age=(at-date(s['last_graded_evidence_at'])).total_seconds()/86400 if s.get('last_graded_evidence_at') else 99999
   src['age_days']=max(0,age);src['calibration_status']='insufficient_future_evidence'
   # Consume sufficient independent calibration only; model shadow does not certify trust.
   data=calibrations.get(src['course_id'],{}).get('versions',{}).get(s.get('policy_version','weighted-evidence-v1'),{}).get('atoms',{}).get(src['course_atom_id'],{} )
   labels=[v.get('independent_mcq',{}).get('classification') for v in data.values()]
   if 'state_overestimation' in labels:src['calibration_status']='state_overestimation'
   elif 'well_aligned' in labels:src['calibration_status']='well_aligned'
   src['independent_evidence']=src.get('independent_evidence',0)
   mass=min(config['per_course_contribution_cap'],s.get('confidence',0)*min(1,src['independent_evidence']/config['evidence_scale'])*(.5+.5*coverage)*math.exp(-max(0,age)/config['recency_days'])*src['mapping_confidence'])
   course_masses[src['course_id']]=max(course_masses.get(src['course_id'],0),mass)
   weighted.append((src,mass))
  # Multiple mapped atoms in one course share a capped contribution; duplicates add no trust.
  for cid in course_masses:
   total_mass=sum(m for src,m in weighted if src['course_id']==cid)
   weighted=[(src,m*course_masses[cid]/total_mass if src['course_id']==cid and total_mass else m) for src,m in weighted]
  measured=[src for src in sources if src['state'].get('mastery') is not None and src['independent_evidence']]
  values=[s['state']['mastery'] for s in measured]
  course_values={cid:sum(src['state']['mastery']*mass for src,mass in weighted if src['course_id']==cid and src['state'].get('mastery') is not None)/sum(mass for src,mass in weighted if src['course_id']==cid and src['state'].get('mastery') is not None) for cid in course_masses if sum(mass for src,mass in weighted if src['course_id']==cid and src['state'].get('mastery') is not None)>0}
  conflict=len(course_values)>1 and max(course_values.values())-min(course_values.values())>=config['conflict_gap']
  def estimate(key):
   items=[(src['state'][key],mass) for src,mass in weighted if src['state'].get(key) is not None and mass>0];total=sum(m for _,m in items)
   return round(sum(v*m for v,m in items)/total,4) if total else None
  total=sum(m for _,m in weighted);count=len({s['course_id'] for s in measured});coverage=sum(estimate(k) is not None for k in ['understanding','application','transfer','retention'])/4
  confidence=(1-math.exp(-total))*(.5+.5*coverage)
  # Diverse independently tested courses support trust; no course can contribute > cap.
  if count>1 and not conflict:confidence=min(1,confidence+.12*min(count-1,2))
  over=any(s['calibration_status']=='state_overestimation' for s in sources)
  if over:confidence*=config['calibration_trust_multiplier']
  newest=max((s['state']['last_graded_evidence_at'] for s in measured if s['state'].get('last_graded_evidence_at')),default=None)
  stale=bool(newest and (at-date(newest)).total_seconds()>config['stale_days']*86400)
  if conflict:confidence*=.5
  level='conflicted' if conflict else 'stale' if stale else 'unknown' if not values else 'strong' if confidence>=config['strong_confidence_threshold'] else 'moderate' if confidence>=config['moderate_confidence_threshold'] else 'weak'
  return {'canonical_atom_id':identity['id'],'name':identity['canonical_name'],'domain':identity['domain'],'mastery_estimate':estimate('mastery'),**{k+'_estimate':estimate(k) for k in ['understanding','application','transfer','retention']},'confidence':round(confidence,4),'support_level':level,'label':LABELS[level],'cross_course_conflict':conflict,'course_count':count,'source_course_ids':list(dict.fromkeys(s['course_id'] for s in sources)),'sources':sources,'state_versions':[(s['course_id'],s['course_atom_id'],s['state']['version']) for s in sources],'calibration_status':'state_overestimation' if over else 'well_aligned' if any(s['calibration_status']=='well_aligned' for s in sources) else 'insufficient_future_evidence','last_verified_at':newest,'policy_version':POLICY['version'],'boundary':'长期知识画像来自已确认关联与历史答题，不是当前课程掌握证明。'}
 def rebuild(self,user):
  # Reuse P2's incremental cursors, outside the profile write transaction.
  # Refresh only courses with new evidence/predictions; never change P2 semantics.
  from .calibration import CalibrationService
  with self.store.connect() as db:
   cursors={r['course_id']:r['cursor'] for r in db.execute('SELECT course_id,MAX(rowid) AS cursor FROM learning_evidence WHERE user_id=? GROUP BY course_id',(user,))}
   predictions={r['course_id']:r['cursor'] for r in db.execute('SELECT course_id,MAX(rowid) AS cursor FROM learning_prediction_snapshots WHERE user_id=? GROUP BY course_id',(user,))}
   cached={r['scope_id']:json.loads(r['result_json']) for r in db.execute("SELECT scope_id,result_json FROM calibration_snapshots WHERE user_id=? AND scope_type='course' AND policy_version='all-separated'",(user,))}
   changed=[r['id'] for r in db.execute('SELECT id FROM courses WHERE session_id=? AND deleted_at IS NULL',(user,)) if cursors.get(r['id'],0)!=cached.get(r['id'],{}).get('source_cursor',0) or predictions.get(r['id'],0)!=cached.get(r['id'],{}).get('prediction_cursor',0)]
  for cid in changed:CalibrationService(self.store).course(user,cid,debug=True)
  with self.store.connect() as db:
   db.execute('BEGIN IMMEDIATE');identities,courses,graphs,mappings,evidence,calibrations=self._inputs(db,user)
   grouped={a['id']:[] for a in identities};invalid=[]
   for m in mappings:
    course=courses.get(m['course_id']);g=graphs.get(m['course_id'],{'atoms':[],'edges':[]});a=next((a for a in g['atoms'] if a['id']==m['course_atom_id'] and a.get('quality_status')!='deprecated'),None)
    if not course or not a or fingerprint(atom_context(course,g,a))!=m['atom_hash']:invalid.append(m['id']);continue
    if m['canonical_atom_id'] not in grouped or not m['state_json']:continue
    state=json.loads(m['state_json'])
    grouped[m['canonical_atom_id']].append({'course_id':course['id'],'course_title':course['title'],'course_atom_id':a['id'],'depth':a['depth'],'source_course_deleted':bool(course['deleted_at']),'mapping_id':m['id'],'mapping_confidence':m['mapping_confidence'],'state':state,'independent_evidence':evidence.get((course['id'],a['id']),0)})
   if invalid:
    for mid in invalid:db.execute("UPDATE inherited_knowledge_priors SET status='invalidated',invalidated_at=? WHERE mapping_id=? AND status!='invalidated'",(iso(clock()),mid))
   cached={r['canonical_atom_id']:r['source_hash'] for r in db.execute('SELECT canonical_atom_id,source_hash FROM personal_knowledge_profiles WHERE user_id=?',(user,))}
   for identity in identities:
    sources=grouped[identity['id']];digest=fingerprint({'sources':sources,'calibration':{s['course_id']:calibrations.get(s['course_id'],{}).get('versions',{}) for s in sources},'policy':POLICY,'day':clock().date().isoformat()})
    if cached.get(identity['id'])==digest:continue
    profile=self.compute(identity,sources,calibrations)
    db.execute('INSERT INTO personal_knowledge_profiles VALUES(?,?,?,?,?) ON CONFLICT(user_id,canonical_atom_id) DO UPDATE SET profile_json=excluded.profile_json,source_hash=excluded.source_hash,updated_at=excluded.updated_at',(user,identity['id'],json.dumps(profile,ensure_ascii=False),digest,iso(clock())))
    if profile['support_level'] in {'conflicted','stale','unknown'}:
     db.execute("UPDATE inherited_knowledge_priors SET status='invalidated',invalidated_at=? WHERE user_id=? AND canonical_atom_id=? AND status!='invalidated'",(iso(clock()),user,identity['id']))
   db.execute("DELETE FROM personal_knowledge_profiles WHERE user_id=? AND canonical_atom_id IN (SELECT id FROM canonical_knowledge_atoms WHERE user_id=? AND status!='active')",(user,user))
  return self.profiles(user,rebuild=False)
 def profiles(self,user,search='',domain='',status='',debug=False,rebuild=True):
  if rebuild:self.rebuild(user)
  with self.store.connect() as db:rows=[json.loads(r[0]) for r in db.execute('SELECT profile_json FROM personal_knowledge_profiles WHERE user_id=?',(user,))]
  result=[]
  for p in rows:
   if search and normalized(search) not in normalized(p['name']) or domain and p['domain']!=domain or status and p['support_level']!=status:continue
   if not debug:
    for key in ['mastery_estimate','understanding_estimate','application_estimate','transfer_estimate','retention_estimate','confidence','state_versions']:p.pop(key,None)
    p['sources']=[{k:s[k] for k in ['course_id','course_title','course_atom_id','depth','source_course_deleted','independent_evidence']}|{'dimensions':[k for k in ['understanding','application','transfer','retention'] if s['state'].get(k) is not None],'last_verified_at':s['state'].get('last_graded_evidence_at')} for s in p['sources']]
   result.append(p)
  return {'profiles':result,'boundary':'关联确认与历史基础不代表在新课程已经掌握；课程状态仍由本课程真实答题产生。'}

class InheritedKnowledgePrior:
 def __init__(self,store):self.store=store
 def refresh(self,user,cid):
  course=self.store._knowledge_course(user,cid);builder=PersonalKnowledgeProfileBuilder(self.store);builder.rebuild(user)
  with self.store.connect() as db:
   db.execute('BEGIN IMMEDIATE');self.store._manage_owned(db,user,cid)
   graph=self.store.graph(user,cid) or {'atoms':[]};atoms={a['id']:a for a in graph['atoms'] if a.get('quality_status')!='deprecated'}
   profiles={r['canonical_atom_id']:json.loads(r['profile_json']) for r in db.execute('SELECT * FROM personal_knowledge_profiles WHERE user_id=?',(user,))}
   mappings=[dict(r) for r in db.execute("SELECT * FROM course_atom_mappings WHERE user_id=? AND course_id=? AND status='verified'",(user,cid))]
   mappings=[m for m in mappings if m['course_atom_id'] in atoms and fingerprint(atom_context(course,graph,atoms[m['course_atom_id']]))==m['atom_hash']]
   active={r['course_atom_id']:dict(r) for r in db.execute("SELECT * FROM inherited_knowledge_priors WHERE user_id=? AND course_id=? AND status!='invalidated'",(user,cid))}
   valid_ids={m['id'] for m in mappings}
   for old in active.values():
    if old['mapping_id'] not in valid_ids or old['course_atom_id'] not in atoms:db.execute("UPDATE inherited_knowledge_priors SET status='invalidated',invalidated_at=? WHERE id=?",(iso(clock()),old['id']))
   for m in mappings:
    atom=atoms.get(m['course_atom_id']);p=profiles.get(m['canonical_atom_id'])
    if not atom or not p:continue
    # Exclude target course entirely: never feed its own state back as history.
    sources=[s for s in p['sources'] if s['course_id']!=cid]
    if not sources:continue
    identity={'id':p['canonical_atom_id'],'canonical_name':p['name'],'domain':p['domain']}
    relevant=builder.compute(identity,json.loads(json.dumps(sources)),{})
    # Preserve calibrated trust from source-only contributions.
    if any(s['calibration_status']=='state_overestimation' for s in sources):relevant['confidence']*=POLICY['profile']['calibration_trust_multiplier'];relevant['calibration_status']='state_overestimation'
    depth=max(s['depth'] for s in sources);higher=atom['depth']>depth;mastery=relevant['mastery_estimate'];retention=relevant['retention_estimate'];transfer=relevant['transfer_estimate']
    stale=relevant['support_level']=='stale';conflict=p['cross_course_conflict'];strength='none' if mastery is None else 'strong' if mastery>=POLICY['prior']['strong_threshold'] and relevant['confidence']>=POLICY['profile']['moderate_confidence_threshold'] else 'moderate' if mastery>=POLICY['prior']['moderate_threshold'] else 'weak'
    if higher or atom['depth']>=3 and transfer is None or retention is not None and retention<.6 or relevant['calibration_status']=='state_overestimation':
     if strength=='strong':strength='moderate'
    if conflict:strength='conflicted'
    if stale:strength='weak'
    covered=[d for d in ['understanding','application','transfer','retention'] if relevant[d+'_estimate'] is not None and (not higher or d=='understanding')]
    scope={'target_depth_relation':'higher' if higher else 'same' if atom['depth']==depth else 'lower','covered_dimensions':covered,'not_assumed':['advanced_application','implementation','transfer'] if higher else [d for d in ['understanding','application','transfer','retention'] if d not in covered],'target_depth':atom['depth'],'source_depth':depth}
    stable=json.loads(json.dumps(relevant))
    for source in stable['sources']:source.pop('age_days',None)
    digest=fingerprint([m['id'],stable,scope,p['cross_course_conflict'],POLICY['prior'],clock().date().isoformat()]);old=active.get(atom['id'])
    if old and old['source_hash']==digest:continue
    if old:db.execute("UPDATE inherited_knowledge_priors SET status='invalidated',invalidated_at=? WHERE id=?",(iso(clock()),old['id']))
    # Preserve verified result when only ordinary new evidence updated the profile;
    # re-checking belongs to a user action, never silently copy mastery.
    state='conflicted' if conflict else 'stale' if stale else 'usable' if strength=='strong' else 'needs_verification'
    pid=secrets.token_urlsafe(16);db.execute('INSERT INTO inherited_knowledge_priors VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(pid,user,cid,atom['id'],m['canonical_atom_id'],m['id'],json.dumps(relevant,ensure_ascii=False),strength,state,json.dumps(['PRIOR_CONFLICT' if conflict else 'PERSONAL_KNOWLEDGE_STALE' if stale else 'PRIOR_NEEDS_VERIFICATION']),json.dumps(list(dict.fromkeys(s['course_id'] for s in sources))),json.dumps(scope),digest,None,iso(clock()),None,None))
  return self.list(user,cid,refresh=False)
 def list(self,user,cid,atom_ids=None,refresh=True,debug=False):
  if refresh:self.refresh(user,cid)
  self.store._knowledge_course(user,cid)
  with self.store.connect() as db:
   rows=[dict(r) for r in db.execute("SELECT p.*,a.canonical_name FROM inherited_knowledge_priors p JOIN canonical_knowledge_atoms a ON a.id=p.canonical_atom_id WHERE p.user_id=? AND p.course_id=? AND p.status!='invalidated'",(user,cid))]
   quizzes={r['id']:self.store._quiz_public(dict(r)) for r in db.execute('SELECT * FROM quizzes WHERE course_id=? AND id IN (SELECT quiz_id FROM inherited_knowledge_priors WHERE user_id=? AND course_id=? AND status!=?)',(cid,user,cid,'invalidated'))}
  result=[]
  for r in rows:
   if atom_ids is not None and r['course_atom_id'] not in atom_ids:continue
   p=json.loads(r['profile_snapshot_json']);scope=json.loads(r['scope_json'])
   v={'id':r['id'],'course_atom_id':r['course_atom_id'],'canonical_atom_id':r['canonical_atom_id'],'canonical_atom':r['canonical_name'],'prior_strength':r['prior_strength'],'status':r['status'],'needs_verification':r['status']!='verified_in_course','reason_codes':json.loads(r['reason_codes_json']),'source_courses':[{'id':s['course_id'],'title':s['course_title'],'deleted':s['source_course_deleted']} for s in p['sources']],'verified_courses':p['course_count'],'scope':scope,'quiz_id':r['quiz_id'],'boundary':'历史相关基础仅用于教学建议，不是当前课程已掌握。'}
   if r['quiz_id'] in quizzes:v['quiz']=quizzes[r['quiz_id']]
   if debug:v['profile_snapshot']=p;v['source_hash']=r['source_hash']
   result.append(v)
  return {'priors':result}
 def relevant(self,user,cid,ids):return self.list(user,cid,ids)['priors'][:6]
