/* Source acquisition and explicitly reviewed knowledge production. */
let productionCourse = null;
let productionRevision = 0;
let discoveryTimer=null;
const qualityLabels = {source_authority:'来源权威性',content_completeness:'文字完整性',freshness:'时效性',multi_source_consistency:'多来源一致性',user_feedback:'审查反馈'};
const sourceOrigins={user_upload:'用户上传',web_search:'网页检索',direct_input:'直接提供'};
const sourceTypes={pdf:'PDF 文档',docx:'Word 文档',pptx:'演示文稿',markdown:'Markdown 文档',txt:'纯文本文件',text:'粘贴文字',web:'网页文字'};
const blockKinds={heading:'标题',paragraph:'段落',formula:'公式',example:'例子',caption:'图表说明',definition:'定义',table:'表格'};
const sourceStatuses = {ready:'待处理',processing:'正在理解',failed:'处理失败，可重试',candidate:'待审查',verified:'已审查导入',deprecated:'已弃用'};
function renderSourceReferences(target, references) {
  target.replaceChildren();
  if (!references.length) { target.append(node('p','AI 课程索引：尚无可核对的资料引用。','muted')); return; }
  target.append(node('p','以下为实际资料中的引用位置。用户审查通过不代表独立事实认证。','muted'));
  for (const ref of references) {
    const box=node('div','','source-reference');
    const location=[ref.page && `第 ${ref.page} 页`,ref.slide && `幻灯片 ${ref.slide}`,ref.paragraph && `段落 ${ref.paragraph}`,ref.line && `行 ${ref.line}`,(ref.section_path || []).join(' / ')].filter(Boolean).join(' · ');
    box.append(node('strong',`${ref.document} · ${location || ref.block_id}`),node('blockquote',ref.quote));
    if (ref.url && /^https?:\/\//.test(ref.url)) {const link=node('a','打开来源网页');link.href=ref.url;link.target='_blank';link.rel='noopener noreferrer';box.append(link);}
    target.append(box);
  }
}
async function refreshProduction(courseId) {
  const revision=++productionRevision;
  clearTimeout(discoveryTimer);
  if(productionCourse!==courseId) {productionCourse=courseId;$('source-detail').hidden=true;$('source-search-results').replaceChildren();['source-title','source-text','source-url','source-query','source-file'].forEach(id=>$(id).value='');}
  try {
    const data=await api(`/api/sources?course_id=${encodeURIComponent(courseId)}`);
    if(state.courseId!==courseId || revision!==productionRevision)return;
    const list=$('source-list');list.replaceChildren();
    if(!data.sources.length)list.append(node('p','尚未导入资料。','muted'));
    data.sources.forEach(source=>{const button=node('button',`${source.title} · ${sourceStatuses[source.processing_status] || source.processing_status}`,'button secondary');button.type='button';button.onclick=()=>action(button,'正在读取资料…',()=>openSource(courseId,source.id));list.append(button);});
    if(!(document.activeElement?.matches('input,textarea,select')&&document.activeElement.closest('#production-batches')))renderProductionBatches(courseId,data.batches);
    state.data.course.source_conflicts=data.conflicts || [];
    renderDiscovery(courseId,data.discovery,data.conflicts || []);
    if(data.discovery?.status==='running')discoveryTimer=setTimeout(()=>{if(state.courseId===courseId)refreshProduction(courseId);},2000);
  } catch(error) {if(state.courseId===courseId)$('source-list').textContent=error.message;}
}
async function openSource(courseId,sourceId) {
  const {source}=await api(`/api/source?${new URLSearchParams({course_id:courseId,source_id:sourceId})}`);
  if(state.courseId!==courseId)return;
  const box=$('source-detail');box.hidden=false;box.replaceChildren(node('h3',source.title));
  box.append(node('p',`${sourceTypes[source.source_type] || source.source_type} · ${sourceOrigins[source.origin] || source.origin} · 获取时间 ${source.created_time}（不是发布时间）`,'muted'));
  (source.metadata.warnings || []).forEach(w=>box.append(node('p',w,'muted')));
  const form=node('form'); const label=node('label','候选所属章节');const select=node('select');select.id='production-section';
  state.data.course.sections.forEach(section=>{const option=node('option',`第 ${section.ordinal} 节 · ${section.title}`);option.value=section.ordinal;select.append(option);});label.append(select);form.append(label);
  form.append(node('p','按标题、页码或幻灯片选择完整文字块。本次最多理解 2.4 万字，不会悄悄截断全文。','muted'));
  let total=0;
  source.metadata.blocks.forEach(block=>{const wrap=node('details','','source-block');const summary=node('summary');const check=node('input');check.type='checkbox';check.value=block.id;check.checked=total+block.text.length<=24000;total+=block.text.length;check.setAttribute('aria-label',`选择 ${block.id}`);summary.append(check,node('span',` ${block.id} · ${blockKinds[block.kind] || block.kind} · ${block.page ? '页 '+block.page : block.slide ? '幻灯片 '+block.slide : (block.section_path||[]).join(' / ')} · ${block.text.length} 字`));wrap.append(summary,node('pre',block.text));form.append(wrap);});
  const button=node('button','理解选定原文并抽取候选','button primary');button.id='production-process';form.append(button);
  form.onsubmit=event=>{event.preventDefault();action(button,'正在理解资料结构、抽取带引用的候选…',async()=>{await api('/api/sources/process',{course_id:courseId,source_id:sourceId,section:Number(select.value),block_ids:Array.from(form.querySelectorAll('input:checked')).map(i=>i.value)});if(state.courseId===courseId)await refreshProduction(courseId);});};box.append(form);
}
function renderProductionBatches(courseId,batches) {
  const list=$('production-batches');list.replaceChildren();
  if(!batches.length)list.append(node('p','处理资料后，会在这里显示待审查的知识候选。','muted'));
  for(const batch of batches) {
    const box=node('section','','source-block');box.append(node('h3',`第 ${batch.section} 节 · ${sourceStatuses[batch.status]}`),node('p',batch.result.understanding));
    if(batch.result.source_policy)box.append(node('p',`生成时来源偏好：${batch.result.source_policy==='user_material_first'?'以我的资料为准':'综合资料'} · 当前水平：${batch.result.learner_level}`,'muted'));
    if(batch.result.imported_count!==undefined)box.append(node('p',`本批采用 ${batch.result.imported_count} 个候选；保留原定义 ${batch.result.retained_count||0} 个。`,'muted'));
    const form=node('form');
    batch.result.candidates.forEach(c=>{
      const wrap=node('div');const label=node('label');const check=node('input');check.type='checkbox';check.value=c.id;check.checked=c.quality.grounded;check.disabled=batch.status!=='candidate'||!c.quality.grounded;check.className='candidate-select';label.append(check,node('strong',` ${c.title} · ${atomTypes[c.type]} · ${sourceStatuses[c.quality_status]}`));wrap.append(label,node('p',c.summary),node('p',`用途：${c.why}`));
      const existing=state.data.knowledge.atoms.find(a=>a.title.toLocaleLowerCase()===c.title.toLocaleLowerCase());
      if(batch.status==='candidate'&&existing&&existing.summary.trim()!==c.summary.trim()){
        wrap.append(node('p','已有定义：'+existing.summary),node('p','新候选定义：'+c.summary));
        const choice=node('select');choice.dataset.candidateId=c.id;choice.className='candidate-merge';
        for(const [value,text] of [['','请选择如何处理不同定义'],['replace','采用新定义（原讲解和学习记录保留）'],['keep','保留原定义，不把新引用认证到原定义']]){const option=node('option',text);option.value=value;choice.append(option);}
        wrap.append(choice);
      }
      Object.entries(qualityLabels).forEach(([key,label])=>wrap.append(node('p',`${label}：${c.quality[key]}`,'muted')));
      c.quality.issues.forEach(issue=>wrap.append(node('p',`不可导入：${issue}`)));const refs=node('div');renderSourceReferences(refs,c.source_reference);wrap.append(refs);form.append(wrap);
    });
    const titles=new Map([...state.data.knowledge.atoms,...batch.result.candidates].map(a=>[a.id,a.title]));
    if(batch.result.relations.length)form.append(node('p',`候选关系：${batch.result.relations.map(r=>`${titles.get(r.from)||r.from} → ${titles.get(r.to)||r.to}（${relationTypes[r.type]}）`).join('；')}`,'muted'));
    if(batch.status==='candidate') {
      const feedback=node('textarea');feedback.rows=2;feedback.maxLength=500;feedback.placeholder='审查备注：准确性、缺失信息或不采纳原因';feedback.setAttribute('aria-label','审查备注');form.append(feedback);
      for(const [reviewAction,text] of [['verify','确认选中候选，加入知识地图'],['deprecate','弃用本批候选']]) {
        const button=node('button',text,'button secondary');button.type='button';button.onclick=()=>action(button,'正在保存审查结果…',async()=>{await api('/api/sources/review',{course_id:courseId,batch_id:batch.id,action:reviewAction,selected:Array.from(form.querySelectorAll('.candidate-select:checked')).map(i=>i.value),feedback:feedback.value,merge_choices:Object.fromEntries(Array.from(form.querySelectorAll('.candidate-merge')).map(i=>[i.dataset.candidateId,i.value]))});if(state.courseId===courseId)renderCourse(await api(`/api/course?course_id=${encodeURIComponent(courseId)}`));});form.append(button);
      }
    } else form.append(node('p',`审查备注：${batch.feedback || '无'}`,'muted'));
    box.append(form);list.append(box);
  }
}
function sourceForm(id,message,work) {
  $(id).onsubmit=event=>{event.preventDefault();const courseId=state.courseId;action($(id).querySelector('button'),message,async()=>{const result=await work(courseId);if(state.courseId===courseId){await refreshProduction(courseId);if(result?.source)await openSource(courseId,result.source.id);}});};
}
sourceForm('source-text-form','正在保存原文…',courseId=>api('/api/sources/text',{course_id:courseId,title:$('source-title').value,text:$('source-text').value}));
sourceForm('source-file-form','正在解析资料结构…',async courseId=>{const file=$('source-file').files[0];if(!file||file.size>6*1024*1024)throw new Error('请选择不超过 6 MB 的资料');const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));return api('/api/sources/upload',{course_id:courseId,filename:file.name,content_base64:btoa(binary)});});
sourceForm('source-url-form','正在获取公开网页正文…',courseId=>api('/api/sources/url',{course_id:courseId,url:$('source-url').value,search_mode:$('source-fetch-mode').value}));
sourceForm('source-search-form','正在检索资料标题与摘要…',async courseId=>{
  const mode=$('source-search-mode').value;const data=await api('/api/sources/search',{course_id:courseId,query:$('source-query').value,search_mode:mode});if(state.courseId!==courseId)return;
  const list=$('source-search-results');list.replaceChildren(node('p',data.note,'muted'));
  data.results.forEach(result=>{const row=node('div','','source-reference');row.append(node('strong',result.title),node('p',result.description || result.content || '无摘要'),node('p',result.url,'muted'));const button=node('button','获取正文，保存为课程资料','button secondary');button.type='button';button.onclick=()=>action(button,'正在获取正文…',async()=>{const saved=await api('/api/sources/url',{course_id:courseId,url:result.url,title:result.title.slice(0,150),search_mode:mode});if(state.courseId===courseId){await refreshProduction(courseId);await openSource(courseId,saved.source.id);}});row.append(button);list.append(row);});
});

$('course-materials').addEventListener('change',()=>{$('course-policy-field').hidden=!$('course-materials').files.length;if(!$('course-materials').files.length)document.querySelector('input[name="source-policy"][value="balanced"]').checked=true;});
async function prepareCourseUploads() {
 const files=Array.from($('course-materials').files);if(files.length>3||files.reduce((total,f)=>total+f.size,0)>6*1024*1024)throw new Error('创建课程最多3份资料，总计6 MB');
 const result=[];for(const file of files){const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));result.push({filename:file.name,content_base64:btoa(binary)});}return result;
}
function renderDiscovery(courseId,run,conflicts) {
 const course=state.data.course;$('course-policy').value=course.source_policy || 'balanced';$('policy-save').disabled=run?.status==='running';$('discovery-retry').disabled=run?.status==='running';
 const statuses={running:'正在自动发现',complete:'自动发现完成，候选等待审查',partial:'自动发现部分完成，请查看失败说明',failed:'自动发现失败，可重试',interrupted:'上次发现已失去响应，可重试'};
 $('discovery-banner').textContent=run ? `${statuses[run.status] || run.status} · ${run.report.stage || '正在启动'} · 仅生成候选，不自动写入地图` : '可自动分析资料与知识缺口，再生成待审查候选。';
 const unresolved=conflicts.filter(c=>!c.confirmed).length;if(unresolved)$('discovery-banner').textContent+=` · 有 ${unresolved} 条未确认来源冲突，请展开资料与知识生产核对`;
 const box=$('discovery-report');box.replaceChildren();
 if(run){
  if(run.report.unexamined_documents?.length)box.append(node('p',`本次预算未查看 ${run.report.unexamined_documents.length} 份资料；未查看不等于未覆盖。`,'muted'));
  (run.report.material_scope || []).forEach(s=>box.append(node('p',`用户资料抽取范围：${s.selected_blocks.length}/${s.total_blocks} 个完整结构块`,'muted')));
  if(run.report.plan){const plan=run.report.plan;box.append(node('h3','已有覆盖与知识缺口（模型分析，需核对）'));plan.requirements.forEach(r=>box.append(node('p',`${r.title} · ${r.covered?'资料中有原文证据':'尚无选定资料证据'} · ${r.reason}${r.query?'；缺口检索词：'+r.query:''}`)));box.append(node('p',`本次最多执行3个搜索词；剩余检索词 ${plan.remaining_queries.length} 项。分析仅覆盖选定完整结构块，不把未查看的范围当作缺失。`,'muted'));plan.scope.forEach(s=>box.append(node('p',`资料分析范围：${s.selected_blocks.length}/${s.total_blocks} 个结构块`,'muted')));}
  if(run.report.plan?.search_tasks){
   const plan=run.report.plan;box.append(node('h3','为知识缺口安排的资料任务'));
   plan.search_tasks.forEach(task=>box.append(node('p',`${task.knowledge_target} · ${task.purpose} · 搜索词：${task.queries.join(' / ')} · 优先参考：${task.preferred_sources.join('、')}${task.generation_origin!=='llm'?' · 使用课程需求补充检索':''}`)));
   if(plan.diagnostics?.requirement_origin!=='llm')box.append(node('p','模型需求分析未完成，已按课程小节检查已有原文并补充规划；覆盖程度仍需你审查。','muted'));
  }
  (run.report.acquisitions || []).forEach(a=>box.append(node('p',`${a.query} · ${a.status==='complete'?'已获取正文并生成候选':a.status==='already_done'?'此前已完成，未重复搜索':'没有取得新的可用正文'}`,'muted')));
  (run.report.errors || []).forEach(e=>box.append(node('p',`${e.stage}：${e.message}`)));
 }
 const list=$('source-conflicts');
 if(document.activeElement?.matches('input,textarea,select')&&document.activeElement.closest('#source-conflicts'))return;
 list.replaceChildren();
 if(!conflicts.length)list.append(node('p','尚无已记录的明显冲突；这不代表已完成事实认证。','muted'));
 conflicts.forEach(conflict=>{
  const item=node('section','','source-block');item.append(node('h3',`${conflict.content.topic} · ${conflict.confirmed?'用户已确认教学表达':'外部资料存在不同表述/事实冲突'}`),node('p',conflict.content.description));
  for(const key of ['source_a','source_b']){const ref=conflict.content[key];item.append(node('p',`${key==='source_a'?'来源 A':'来源 B'} · ${sourceOrigins[ref.origin]||ref.origin} · ${sourceTypes[ref.type]||ref.type}`,'muted'));const refs=node('div');renderSourceReferences(refs,[ref]);item.append(refs);}
  item.append(node('p',`当前课程拟采用的教学表达：${conflict.teaching_expression}`),node('p','确认只记录教学选择；不代表独立事实认证，不会覆盖已保存讲义或改变掌握率。','muted'));
  const input=node('textarea');input.rows=3;input.maxLength=600;input.value=conflict.teaching_expression;input.setAttribute('aria-label','本课程采用的教学表达');
  const button=node('button','确认教学表达并保留冲突记录','button secondary');button.type='button';button.onclick=()=>action(button,'正在保存冲突审查…',async()=>{await api('/api/conflicts/confirm',{course_id:courseId,conflict_id:conflict.id,teaching_expression:input.value});if(state.courseId===courseId)await refreshProduction(courseId);});item.append(input,button);list.append(item);
 });
}
$('policy-save').onclick=()=>action($('policy-save'),'正在保存课程来源偏好…',async()=>{const cid=state.courseId;const latest=await api('/api/courses/source-policy',{course_id:cid,source_policy:$('course-policy').value});if(state.courseId===cid)renderCourse(latest);});
$('discovery-retry').onclick=()=>action($('discovery-retry'),'正在重新分析已有资料与知识缺口…',async()=>{const cid=state.courseId;await api('/api/discovery/start',{course_id:cid});if(state.courseId===cid)await refreshProduction(cid);});
