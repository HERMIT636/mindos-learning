"""User outputs are not learning resources or learning evidence."""
from pathlib import Path
from ..safe_files import SafeFiles
from ..resources.processing import identify,extract_pdf
from ..resources.service import ResourceService
from .service import MissionService,uid,now,encode,row_json
from .protocol import *

TEXT_EXTENSIONS={'.txt','.md','.py','.cu','.c','.cpp','.h','.rs','.java','.js','.ts','.json','.csv','.log','.yaml','.yml','.toml','.ini','.cfg','.sql','.sh','.r','.ipynb'}
MODEL_EXTENSIONS={'.bin','.pt','.pth','.onnx','.safetensors','.gguf'}
class ArtifactService:
 def __init__(self,store):self.store=store;self.missions=MissionService(store);self.files=SafeFiles(store,'artifacts')
 def _owned(self,db,user,mid,aid):
  self.missions._owned(db,user,mid);r=db.execute('SELECT * FROM mission_artifacts WHERE id=? AND user_id=? AND mission_id=?',(aid,user,mid)).fetchone()
  if not r:raise ValueError('实践产出不存在或不属于当前项目')
  return r
 def public(self,row):
  r=row_json(row);r.pop('local_path',None);r['experiment_id']=r['task_id'] if r['metadata'].get('experiment') else None;r['file_url']=f"/api/missions/{r['mission_id']}/artifacts/{r['id']}/file";return r
 def get(self,user,mid,aid):
  with self.store.connect() as db:return self.public(self._owned(db,user,mid,aid))
 def list(self,user,mid):
  with self.store.connect() as db:
   self.missions._owned(db,user,mid);rows=db.execute('SELECT * FROM mission_artifacts WHERE user_id=? AND mission_id=? ORDER BY created_at DESC LIMIT 200',(user,mid)).fetchall();total=db.execute('SELECT count(*) FROM mission_artifacts WHERE user_id=? AND mission_id=?',(user,mid)).fetchone()[0]
  return {'artifacts':[self.public(r) for r in rows],'total':total,'boundary':'实践产出单独保存；只有明确选择“保存为学习资料”才创建 P8 材料。'}
 def upload(self,user,mid,p,data):
  fields(p,{'filename','title','artifact_type','task_id','experiment_id','run_id','parent_artifact_id','caption','repository_url'})
  filename=text(p.get('filename'),150)
  if '/' in filename or '\\' in filename or filename in {'.','..'}:raise ValueError('文件名无效')
  kind=enum(p.get('artifact_type','other'),ARTIFACT_TYPES,'产出类型');ext=Path(filename).suffix.lower()
  if not isinstance(data,bytes) or not data or len(data)>POLICY['uploads']['max_bytes']:raise ValueError('产出为空或超过 30 MB；大日志请先截取相关片段')
  if kind=='model':
   if ext not in MODEL_EXTENSIONS:raise ValueError('模型文件扩展名不支持')
   detected,mime,suffix='binary','application/octet-stream','.bin'
  else:
   detected,mime,suffix=identify(data)
   valid=(detected=='text' and ext in TEXT_EXTENSIONS) or (mime=='image/png' and ext=='.png') or (mime=='image/jpeg' and ext in {'.jpg','.jpeg'}) or (mime=='application/pdf' and ext=='.pdf')
   if not valid:raise ValueError('产出扩展名与实际格式不一致或不支持')
   if kind=='image' and detected!='image':raise ValueError('图片产出必须是真实 PNG/JPEG')
  tid=p.get('task_id') or p.get('experiment_id');run_id=p.get('run_id');parent=p.get('parent_artifact_id');version=1;aid=uid();ts=now()
  metadata={'filename':filename,'format':detected,'caption':text(p.get('caption',''),1500,True),'preview_truncated':detected=='text' and len(data)>POLICY['uploads']['preview_chars'],'warning':'请勿上传密钥、令牌或其他敏感配置。文件仅保存和预览，不会运行。'}
  if p.get('repository_url'):
   from ..resources.protocol import content
   metadata['repository_url']=content('reference',{'url':p['repository_url']})['url']
  with self.store.connect() as db:
   self.missions._owned(db,user,mid)
   if tid:
    t=self.missions._task(db,user,mid,tid);metadata['experiment']=t['task_type']=='experiment'
    if p.get('experiment_id') and t['task_type']!='experiment':raise ValueError('关联任务不是实验')
   if run_id:
    run=db.execute('SELECT task_id FROM mission_experiment_runs WHERE id=? AND mission_id=?',(run_id,mid)).fetchone()
    if not run or tid and tid!=run[0]:raise ValueError('运行记录不属于当前实验')
    tid=run[0]
   if parent:
    old=self._owned(db,user,mid,parent)
    if old['artifact_type']!=kind or old['task_id']!=tid:raise ValueError('版本的类型和任务必须与父产出一致')
    version=old['version']+1
  path=self.files.write(aid,suffix,data)
  try:
   with self.store.connect() as db:
    db.execute('BEGIN IMMEDIATE');self.missions._owned(db,user,mid)
    self.missions._touch(db,mid);db.execute('INSERT INTO mission_artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(aid,user,mid,tid,run_id,kind,text(p.get('title') or filename,150),path.name,mime,digest(data),version,parent,encode(metadata),ts,ts))
    if run_id:
     r=db.execute('SELECT artifact_ids_json FROM mission_experiment_runs WHERE id=?',(run_id,)).fetchone();ids=json.loads(r[0]);ids.append(aid);db.execute('UPDATE mission_experiment_runs SET artifact_ids_json=? WHERE id=?',(encode(ids),run_id))
  except Exception:path.unlink(missing_ok=True);raise
  return self.get(user,mid,aid)
 def file(self,user,mid,aid):
  with self.store.connect() as db:r=self._owned(db,user,mid,aid)
  path=self.files.file(aid,r['local_path'],{'.txt','.png','.jpg','.pdf','.bin'})
  return path,r['mime_type']
 def preview(self,user,mid,aid,p=None):
  p=p or {};fields(p,{'pages'});r=self.get(user,mid,aid);path,mime=self.file(user,mid,aid);mode=r['metadata']['format'];value='';note=''
  if mode=='text':
   with path.open('rb') as stream:data=stream.read(POLICY['uploads']['preview_chars']*4)
   value=data.decode('utf-8-sig',errors='ignore')[:POLICY['uploads']['preview_chars']];note='显示有限片段，原文件仍保留。'
  elif mime=='application/pdf':
   if p.get('pages'):value=extract_pdf(path.read_bytes(),p['pages']);note='仅所选页码实际提取的文字，不代表已读取全文。'
   else:note='尚未读取 PDF 正文；请选择页码，扫描文件不做 OCR。'
  elif mode=='image':note='图片可以预览；文字导师只读取你填写的说明，未识别图片内容。';value=r['metadata']['caption']
  else:note='二进制模型仅记录元数据与哈希，无法读取模型结构或判断质量。'
  return {'artifact':r,'text':value,'note':note,'pages':p.get('pages',[]),'truncated':mode=='text' and path.stat().st_size>len(value.encode())}
 def delete(self,user,mid,aid,p):
  fields(p,{'confirm'})
  if p.get('confirm') is not True:raise ValueError('永久删除产出需要明确确认')
  with self.store.connect() as db:
   db.execute('BEGIN IMMEDIATE');r=self._owned(db,user,mid,aid)
   if db.execute('SELECT 1 FROM mission_artifacts WHERE parent_artifact_id=?',(aid,)).fetchone():raise ValueError('产出仍有后续版本，请先删除后续版本')
   if r['run_id']:raise ValueError('产出属于实际实验运行，请保留历史或先调整运行关联')
   for table in ['mission_experiment_runs','mission_reflections','project_evidence_candidates']:
    if any(aid in json.loads(x[0]) for x in db.execute('SELECT artifact_ids_json FROM '+table+' WHERE mission_id=?',(mid,))):raise ValueError('产出仍被实验、复盘或评估候选引用，不能删除')
   if db.execute("SELECT 1 FROM knowledge_resources WHERE user_id=? AND json_extract(metadata_json,'$.derived_from_artifact_id')=?",(user,aid)).fetchone():raise ValueError('产出已有派生学习资料，请先删除派生资料')
   if r['task_id']:
    t=self.missions._task(db,user,mid,r['task_id']);meta=json.loads(t['metadata_json'])
    if t['status']=='completed' and r['artifact_type'] in meta.get('artifact_types',[]):raise ValueError('产出是已完成任务的必要交付，请保留完成依据')
   path,_=self.file(user,mid,aid);db.execute('DELETE FROM mission_artifacts WHERE id=?',(aid,));path.unlink()
  return {'deleted':True}
 def promote(self,user,mid,aid,p):
  fields(p,{'confirm','course_id','atom_id','pages'})
  if p.get('confirm') is not True:raise ValueError('请明确确认将产出保存为学习资料')
  cid=p.get('course_id');atom=p.get('atom_id');resources=ResourceService(self.store);resources.atom(user,cid,atom);preview=self.preview(user,mid,aid,{'pages':p.get('pages',[])});r=preview['artifact'];meta={'derived_from_artifact_id':aid,'mission_id':mid,'original_hash':r['content_hash'],'excerpt_truncated':preview['truncated']}
  if not preview['text']:raise ValueError('产出没有可读取的文字；请先选 PDF 页码或提供图片说明')
  if r['artifact_type']=='code':kind='code';payload={'code':preview['text'],'language':{'.py':'python','.js':'javascript','.json':'json','.cu':'cpp','.c':'cpp','.h':'cpp','.cpp':'cpp','.sql':'sql','.sh':'bash'}.get(Path(r['metadata']['filename']).suffix.lower(),'text'),'description':'用户明确保存的实践产出片段，仅阅读，不运行。','runnable':False}
  else:kind='text';payload={'text':preview['text'][:30000]}
  derived=resources.create(user,kind,r['title']+' · 学习资料',payload,'manual',meta)
  try:resources.link(user,cid,atom,derived['id'])
  except Exception:resources.delete(user,derived['id'],True);raise
  return {'resource':resources.get(user,derived['id']),'boundary':'这是一条独立的派生学习资料记录；原产出和知识掌握均未改变。'}
