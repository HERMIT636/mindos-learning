"""Owned resources + many-to-many mappings, separate from learner state and graph."""
import json,os,secrets
from pathlib import Path
from ..tutor.storage import now
from .protocol import POLICY,TYPES,SOURCES,ROLES,DEFAULT_ROLES,content,text,digest,resource_text
from .processing import identify,pdf_pages,extract_pdf
SCHEMA='''
CREATE TABLE IF NOT EXISTS knowledge_resources (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,resource_type TEXT NOT NULL,title TEXT NOT NULL,
 source_type TEXT NOT NULL,source_uri TEXT,local_path TEXT,mime_type TEXT,content_hash TEXT NOT NULL,
 status TEXT NOT NULL,metadata_json TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS resource_owner ON knowledge_resources(user_id,id);
CREATE TABLE IF NOT EXISTS atom_resource_mappings (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
 atom_id TEXT NOT NULL,resource_id TEXT NOT NULL REFERENCES knowledge_resources(id) ON DELETE CASCADE,
 role TEXT NOT NULL,relevance REAL NOT NULL,status TEXT NOT NULL,source TEXT NOT NULL,created_at TEXT NOT NULL,
 UNIQUE(user_id,course_id,atom_id,resource_id)
);
CREATE INDEX IF NOT EXISTS resource_atom ON atom_resource_mappings(user_id,course_id,atom_id);
'''
def migrate(db):db.executescript(SCHEMA)

class ResourceService:
 def __init__(self,store):self.store=store;self.directory=store.path.parent/'resources'
 def atom(self,user,cid,aid):
  atom=self.store.atom(user,cid,aid,unlocked=True)
  if atom.get('quality_status')=='deprecated':raise ValueError('已弃用知识点不能关联学习材料')
  return atom
 def fingerprint(self,user,cid,aid):
  a=self.atom(user,cid,aid);c=self.store._knowledge_course(user,cid)
  return digest({'course':cid,'revision':c['content_revision'],'atom':{k:a.get(k) for k in ['id','title','summary','section','type','depth','quality_status']}})
 def _root(self):
  if self.directory.is_symlink() or self.directory.resolve().parent!=self.store.path.parent.resolve():raise ValueError('资料目录路径无效')
  return self.directory.resolve()
 def _public(self,row,user,cid=None,aid=None,fingerprint=None):
  r=dict(row);meta=json.loads(r.pop('metadata_json'));r['payload']=meta.pop('payload',{});r['metadata']=meta
  r.pop('local_path',None)
  r['file_url']='/api/resources/'+r['id']+'/file' if row['local_path'] else None
  r['needs_review']=bool(meta.get('needs_review'))
  if cid and aid and r['source_type']=='generated':r['needs_review']=bool(meta.get('needs_review')) or meta.get('context_fingerprint')!=(fingerprint or self.fingerprint(user,cid,aid))
  if r['needs_review']:r['metadata']['needs_review']=True
  return r
 def get(self,user,rid):
  with self.store.connect() as db:row=db.execute('SELECT * FROM knowledge_resources WHERE id=? AND user_id=?',(rid,user)).fetchone()
  if not row:raise ValueError('资料不存在或不属于你')
  return self._public(row,user)
 def create(self,user,kind,title,payload,source='manual',metadata=None,source_uri=None,local_path=None,mime=None,status='ready',hash_value=None):
  if source not in SOURCES or status not in {'ready','pending','failed','archived'}:raise ValueError('资料来源或状态无效')
  value=content(kind,payload);title=text(title,150);meta=dict(metadata or {});meta['payload']=value
  rid=secrets.token_urlsafe(18);ts=now()
  with self.store.connect() as db:db.execute('INSERT INTO knowledge_resources VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(rid,user,kind,title,source,source_uri,local_path,mime,hash_value or digest(value),status,json.dumps(meta,ensure_ascii=False),ts,ts))
  return self.get(user,rid)
 def create_for_atom(self,user,cid,aid,request):
  self.atom(user,cid,aid)
  if not isinstance(request,dict) or set(request)-{'type','title','payload','role','source_resource_id'}:raise ValueError('资料请求字段无效')
  kind=request.get('type');parent=request.get('source_resource_id');metadata={}
  if parent:metadata['derived_from_resource_id']=self.get(user,parent)['id']
  role=request.get('role',DEFAULT_ROLES.get(kind))
  if role not in ROLES:raise ValueError('关联用途无效')
  r=self.create(user,kind,request.get('title'),request.get('payload'),metadata=metadata)
  try:self.link(user,cid,aid,r['id'],role)
  except Exception:self.delete(user,r['id'],True);raise
  return r
 def upload(self,user,filename,data,alt='',caption=''):
  # Original names are display text only. Never use them in filesystem paths.
  filename=text(filename,150)
  if '/' in filename or '\\' in filename or filename in {'.','..'}:raise ValueError('文件名无效')
  kind,mime,suffix=identify(data);ext=Path(filename).suffix.lower()
  expected={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.pdf':'application/pdf','.txt':'text/plain; charset=utf-8','.md':'text/plain; charset=utf-8'}
  if ext not in expected or expected[ext]!=mime:raise ValueError('文件扩展名与实际格式不一致，或类型不支持')
  metadata={};status='ready'
  if kind=='text':payload={'text':data.decode('utf-8-sig'),'language':'text'};metadata['headings']=[line.lstrip('# ').strip()[:150] for line in payload['text'].splitlines() if line.startswith('#')][:100]
  elif kind=='image':payload={'alt':alt,'caption':caption,'source':'用户上传'}
  else:
   payload={'document':True,'description':'原 PDF；请选择页码生成可阅读片段'};metadata['document']=True;status='pending'
   try:metadata['page_count']=len(pdf_pages(data).pages)
   except Exception:status='failed';metadata['failure']='PDF 无法解析；可以重试、删除，或手动提供选中页面的文字。'
  # Text uploads are bounded separately; allow 5 MB storage, tutor still clips excerpts.
  if kind=='text' and len(payload['text'])>30000:
   metadata['original_text_chars']=len(payload['text']);payload['text']=payload['text'][:30000];metadata['display_truncated']=True
  r=self.create(user,kind,filename,payload,'user_uploaded',metadata,mime=mime,status=status,hash_value=digest(data))
  try:
   self._root();self.directory.mkdir(parents=True,exist_ok=True);path=self._root()/(r['id']+suffix)
   with path.open('xb') as f:f.write(data)
   with self.store.connect() as db:db.execute('UPDATE knowledge_resources SET local_path=? WHERE id=?',(path.name,r['id']))
  except Exception:
   self.delete(user,r['id'],True);raise
  return self.get(user,r['id'])
 def file(self,user,rid):
  self.get(user,rid)
  with self.store.connect() as db:row=db.execute('SELECT local_path,mime_type FROM knowledge_resources WHERE user_id=? AND id=?',(user,rid)).fetchone()
  name=row['local_path']
  if not name or Path(name).name!=name or name not in {rid+ext for ext in ['.pdf','.png','.jpg','.txt']}:raise ValueError('本地资料路径无效')
  root=self._root();p=root/name
  if p.is_symlink() or p.resolve().parent!=root or not p.is_file():raise ValueError('本地资料不存在')
  return p,row['mime_type']
 def extract(self,user,rid,pages):
  r=self.get(user,rid)
  if not r['metadata'].get('document'):raise ValueError('请先选择 PDF 原文件')
  p,_=self.file(user,rid)
  try:value=extract_pdf(p.read_bytes(),pages)
  except Exception as exc:
   if isinstance(exc,ValueError):reason=str(exc)
   else:reason='PDF 解析失败，未推断任何正文。可以重试或手动提供文字。'
   self._status(user,rid,'failed',{'failure':reason});raise ValueError(reason) from None
  child=self.create(user,'paper_excerpt',r['title']+' · 选页片段',{'text':value},'user_uploaded',{'derived_from_resource_id':rid,'pages':sorted(pages)},source_uri=r['source_uri'])
  self._status(user,rid,'pending',{'failure':None,'page_count':len(pdf_pages(p.read_bytes()).pages)})
  return child
 def _status(self,user,rid,status,patch):
  with self.store.connect() as db:
   row=db.execute('SELECT metadata_json FROM knowledge_resources WHERE user_id=? AND id=?',(user,rid)).fetchone();meta=json.loads(row[0]);meta.update(patch);db.execute('UPDATE knowledge_resources SET status=?,metadata_json=?,updated_at=? WHERE user_id=? AND id=?',(status,json.dumps(meta,ensure_ascii=False),now(),user,rid))
 def link(self,user,cid,aid,rid,role=None):
  self.atom(user,cid,aid);r=self.get(user,rid);role=role or DEFAULT_ROLES[r['resource_type']]
  if role not in ROLES:raise ValueError('关联用途无效')
  if r['status']=='archived':raise ValueError('归档资料不能新增关联')
  with self.store.connect() as db:
   self.store._manage_owned(db,user,cid)
   db.execute('INSERT INTO atom_resource_mappings VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,course_id,atom_id,resource_id) DO UPDATE SET role=excluded.role,status=excluded.status',(secrets.token_urlsafe(18),user,cid,aid,rid,role,1.0,'active',r['source_type'],now()))
  return self.get(user,rid)
 def unlink(self,user,cid,aid,rid):
  self.atom(user,cid,aid);self.get(user,rid)
  with self.store.connect() as db:db.execute('DELETE FROM atom_resource_mappings WHERE user_id=? AND course_id=? AND atom_id=? AND resource_id=?',(user,cid,aid,rid))
 def list(self,user,cid,aid,offset=0,search='',kind=None):
  self.atom(user,cid,aid)
  if type(offset) is not int or not 0<=offset<=100000:raise ValueError('资料页码无效')
  if kind and kind not in TYPES:raise ValueError('资料类型无效')
  search=text(search,100,True);limit=POLICY['display']['max_default_resources']
  with self.store.connect() as db:
   rows=db.execute('SELECT r.*,m.role FROM knowledge_resources r JOIN atom_resource_mappings m ON m.resource_id=r.id WHERE r.user_id=? AND m.user_id=? AND m.course_id=? AND m.atom_id=? AND m.status=\'active\' AND (?=\'\' OR instr(lower(r.title),lower(?))>0) AND (? IS NULL OR r.resource_type=?) ORDER BY r.created_at DESC LIMIT ? OFFSET ?',(user,user,cid,aid,search,search,kind,kind,limit+1,offset)).fetchall()
   counts={r[0]:r[1] for r in db.execute('SELECT r.resource_type,count(*) FROM knowledge_resources r JOIN atom_resource_mappings m ON m.resource_id=r.id WHERE r.user_id=? AND m.user_id=? AND m.course_id=? AND m.atom_id=? AND m.status=\'active\' GROUP BY r.resource_type',(user,user,cid,aid))}
  fp=self.fingerprint(user,cid,aid) if any(r['source_type']=='generated' for r in rows[:limit]) else None
  with self.store.connect() as db:roles={r[0]:r[1] for r in db.execute("SELECT role,count(*) FROM atom_resource_mappings WHERE user_id=? AND course_id=? AND atom_id=? AND status='active' GROUP BY role",(user,cid,aid))}
  return {'role_counts':roles,'resources':[self._public(r,user,cid,aid,fp) for r in rows[:limit]],'has_more':len(rows)>limit,'next_offset':offset+limit,'counts':counts}
 def mapped(self,user,cid,aid,rid):
  self.atom(user,cid,aid)
  with self.store.connect() as db:row=db.execute('SELECT role FROM atom_resource_mappings WHERE user_id=? AND course_id=? AND atom_id=? AND resource_id=? AND status=\'active\'',(user,cid,aid,rid)).fetchone()
  if not row:raise ValueError('资料没有关联当前课程的这个知识点')
  r=self.get(user,rid);r['role']=row[0];return r
 def delete(self,user,rid,confirm=False):
  self.get(user,rid)
  if confirm is not True:raise ValueError('永久删除资料需要明确确认；关联和派生情况可先查看')
  with self.store.connect() as db:
   db.execute('BEGIN IMMEDIATE');children=db.execute("SELECT id FROM knowledge_resources WHERE user_id=? AND json_extract(metadata_json,'$.derived_from_resource_id')=?",(user,rid)).fetchall()
   if children:raise ValueError('资料仍有派生片段或摘要，请先删除派生资料')
   row=db.execute('SELECT local_path FROM knowledge_resources WHERE user_id=? AND id=?',(user,rid)).fetchone()
   name=row[0];p=None
   if name:p,_=self.file(user,rid)
   db.execute('DELETE FROM knowledge_resources WHERE user_id=? AND id=?',(user,rid))
   if p:p.unlink(missing_ok=True)
  return {'deleted':True}
 def inspect(self,user,rid):
  r=self.get(user,rid)
  with self.store.connect() as db:
   links=[dict(x) for x in db.execute('SELECT course_id,atom_id,role FROM atom_resource_mappings WHERE user_id=? AND resource_id=?',(user,rid))];children=[x[0] for x in db.execute("SELECT id FROM knowledge_resources WHERE user_id=? AND json_extract(metadata_json,'$.derived_from_resource_id')=?",(user,rid))]
  return {'resource':r,'mappings':links,'derivatives':children,'tutor_eligible':bool(resource_text(r)),'reason':'仅 ready 的可读材料进入上下文；PDF 原文件不自动发送正文。'}
 def copy_links(self,user,old,new):
  self.store._knowledge_course(user,old);self.store._knowledge_course(user,new)
  with self.store.connect() as db:
   rows=db.execute("SELECT m.*,r.source_type FROM atom_resource_mappings m JOIN knowledge_resources r ON m.resource_id=r.id WHERE m.user_id=? AND m.course_id=? AND r.user_id=? AND r.source_type='generated' AND m.role<>'personal_note'",(user,old,user)).fetchall()
   for r in rows:db.execute('INSERT OR IGNORE INTO atom_resource_mappings VALUES(?,?,?,?,?,?,?,?,?,?)',(secrets.token_urlsafe(18),user,new,r['atom_id'],r['resource_id'],r['role'],r['relevance'],r['status'],r['source'],now()))
 def course_resource_ids(self,user,cid):
  with self.store.connect() as db:return [r[0] for r in db.execute('SELECT resource_id FROM atom_resource_mappings WHERE user_id=? AND course_id=?',(user,cid))]
 def cleanup(self,user,candidates=None):
  # Only resources associated with the purged course at the boundary; never sweep another course.
  while True:
   with self.store.connect() as db:ids=[r[0] for r in db.execute("SELECT id FROM knowledge_resources WHERE user_id=? AND source_type='generated' AND id NOT IN (SELECT resource_id FROM atom_resource_mappings) AND id NOT IN (SELECT json_extract(metadata_json,'$.derived_from_resource_id') FROM knowledge_resources WHERE json_extract(metadata_json,'$.derived_from_resource_id') IS NOT NULL)",(user,))]
   if candidates is not None:ids=[rid for rid in ids if rid in candidates]
   if not ids:break
   for rid in ids:self.delete(user,rid,True)
