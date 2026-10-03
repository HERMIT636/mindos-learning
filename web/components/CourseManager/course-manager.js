/* Native DOM components for course management; no framework dependency. */
const CourseManager = (() => {
  let courses = [], filter = 'all', draggedId = null, editing = null, deleting = null;
  const labels = {active:'学习中', paused:'暂停', completed:'已完成', archived:'归档'};
  async function request(path, method='GET', body) {
    const options={method};
    if(body!==undefined){options.headers={'Content-Type':'application/json'};options.body=JSON.stringify(body);}
    const response=await fetch(path,options);const data=await response.json();
    if(!response.ok)throw new Error(data.error || '课程操作失败');MindOSKnowledgeUniverse.notifyChange(path,method);return data;
  }
  function button(text, callback, className='button secondary') {
    const item=node('button',text,className);item.type='button';item.addEventListener('click',callback);return item;
  }
  function CourseEditor(course) {
    editing=course;$('manager-edit-error').textContent='';
    for(const key of ['title','description','cover','goal','level','status'])$('manager-edit-'+key).value=course[key] || '';
    $('manager-edit-tags').value=(course.tags || []).join('、');
    $('course-editor').showModal();$('manager-edit-title').focus();
  }
  function DeleteConfirm(course, permanent=false) {
    deleting={course,permanent};$('manager-delete-error').textContent='';$('manager-delete-title').textContent=permanent?'永久删除课程':'移入回收站';
    $('manager-delete-note').textContent=permanent?`永久删除“${course.title}”及全部学习记录、资料与知识关系，此操作无法恢复。请填写完整课程名称确认。`:`“${course.title}”将移入回收站。学习记录、资料和知识关系都会保留，可随时恢复。`;
    $('manager-delete-check').hidden=!permanent;$('manager-delete-input').value='';
    $('manager-delete-submit').textContent=permanent?'永久删除':'移入回收站';$('course-delete-confirm').showModal();
  }
  async function mutate(course, operation, body={}) {
    await request(`/api/courses/${course.id}/${operation}`,'POST',body);await load();
  }
  function CourseMenu(course, trash=false) {
    const menu=node('details','','course-menu');const summary=node('summary','⋮');summary.setAttribute('aria-label',`管理 ${course.title}`);menu.append(summary);
    const actions=node('div','','course-menu-actions');menu.append(actions);
    if(trash){
      actions.append(button('恢复课程',e=>action(e.currentTarget,'正在恢复课程…',()=>mutate(course,'restore'))));
      actions.append(button('永久删除',()=>DeleteConfirm(course,true),'button quiet-button'));return menu;
    }
    actions.append(button('进入学习',()=>{menu.open=false;openCourse(course.id);}));
    actions.append(button('编辑课程',()=>{menu.open=false;CourseEditor(course);}));
    actions.append(button('调整排序',()=>{menu.open=false;$('manager-filter').value='all';filter='all';CourseList();$('manager-sort-hint').focus();}));
    actions.append(button('重命名',()=>{menu.open=false;CourseEditor(course);}));
    actions.append(button('复制课程',e=>action(e.currentTarget,'正在复制课程结构…',()=>mutate(course,'copy'))));
    const status=course.status==='archived'?'active':'archived';
    actions.append(button(course.status==='archived'?'取消归档':'归档',e=>action(e.currentTarget,'正在更新课程状态…',async()=>{
      await request(`/api/courses/${course.id}/status`,'PUT',{status});await load();
    })));
    actions.append(button('删除课程',()=>{menu.open=false;DeleteConfirm(course);},'button quiet-button'));return menu;
  }
  function CourseCard(course, trash=false) {
    const card=node('article','','card manager-course-card');card.dataset.courseId=course.id;
    const head=node('div','','section-head');head.append(node('h2',course.title),CourseMenu(course,trash));card.append(head);
    if(course.cover){const image=node('img','','manager-cover');image.src=course.cover;image.alt=course.title+'的课程封面';image.loading='lazy';image.referrerPolicy='no-referrer';image.addEventListener('error',()=>{image.replaceWith(node('p','封面暂时无法显示','muted'));});card.prepend(image);}
    card.append(node('p',course.description || course.goal || '暂未填写课程简介','muted'));
    const info=node('div','','manager-card-info');info.append(node('span','管理状态：'+labels[course.status]),node('span',course.level),node('span',`知识点 ${course.knowledge_count} 个`));card.append(info);
    if(course.course_mastery?.label)card.append(node('p',course.course_mastery.label,'final-state'));
    const progress=node('p',`学习进度 ${course.progress}% · 共 ${course.section_count} 节`);progress.title=course.progress_note;card.append(progress);
    const meter=node('progress');meter.max=100;meter.value=course.progress;meter.setAttribute('aria-label','学习进度');card.append(meter);
    card.append(node('p',course.last_study_at?`最近学习：${new Date(course.last_study_at).toLocaleString('zh-CN')}`:'最近学习：尚无学习记录','muted'));
    if(course.tags.length)card.append(node('p',course.tags.join(' · '),'muted'));
    if(!trash){const row=node('div','','action-row');row.append(button('进入学习',()=>openCourse(course.id),'button primary'));card.append(row);}
    if(filter==='all')SortableCourseList(card,course);
    return card;
  }
  async function saveOrder(ordered) {
    await request('/api/courses/order','PUT',ordered.map((course,i)=>({id:course.id,sort_order:i+1})));await load();
  }
  function SortableCourseList(card,course) {
    const handle=node('div','','manager-sort-actions');const grip=node('span','☰ 拖动调整顺序','manager-drag');grip.draggable=true;grip.tabIndex=0;grip.setAttribute('aria-label',`拖动 ${course.title} 调整排序`);
    grip.addEventListener('dragstart',event=>{draggedId=course.id;event.dataTransfer.setData('text/plain',course.id);event.dataTransfer.effectAllowed='move';});
    grip.addEventListener('dragend',()=>{draggedId=null;document.querySelectorAll('.drag-over').forEach(item=>item.classList.remove('drag-over'));});
    card.addEventListener('dragover',event=>{if(draggedId){event.preventDefault();card.classList.add('drag-over');}});
    card.addEventListener('dragleave',()=>card.classList.remove('drag-over'));
    card.addEventListener('drop',event=>{event.preventDefault();card.classList.remove('drag-over');if(!draggedId || draggedId===course.id)return;
      const ordered=courses.filter(c=>c.id!==draggedId);const source=courses.find(c=>c.id===draggedId);draggedId=null;
      if(source){ordered.splice(ordered.findIndex(c=>c.id===course.id),0,source);action(null,'正在保存课程顺序…',()=>saveOrder(ordered));}
    });
    handle.append(grip);
    for(const [label,offset] of [['上移',-1],['下移',1]]){
      const control=button(label,event=>action(event.currentTarget,'正在保存课程顺序…',async()=>{
        const ordered=[...courses];const index=ordered.findIndex(c=>c.id===course.id);const target=index+offset;
        if(target<0 || target>=ordered.length)return;[ordered[index],ordered[target]]=[ordered[target],ordered[index]];await saveOrder(ordered);
      }),'button secondary manager-sort-button');
      control.disabled=courses.indexOf(course)+offset<0 || courses.indexOf(course)+offset>=courses.length;handle.append(control);
    }
    card.append(handle);
  }
  function CourseList() {
    const list=$('manager-course-list');list.replaceChildren();
    const visible=filter==='all' || filter==='deleted'?courses:courses.filter(c=>c.status===filter);
    $('manager-count').textContent=`${visible.length} 门课程`;
    $('manager-sort-hint').textContent=filter==='all'?'拖动 ☰ 可排序，也可用上移、下移按钮。顺序会保存。学习进度不代表掌握率。':'切换“全部课程”可排序。归档、暂停和已完成课程仍可进入学习；回收站课程须先恢复。';
    if(!visible.length)list.append(node('p',filter==='deleted'?'回收站为空。':'这里还没有课程。可以新建课程，或更换筛选。','muted'));
    visible.forEach(c=>list.append(CourseCard(c,filter==='deleted')));
  }
  function dashboard() {
    const box=$('dashboard-courses');box.replaceChildren();
    const active=state.courses.filter(c=>(c.status || 'active')==='active');
    if(active.length){box.append(node('h2','继续学习'));active.forEach(c=>box.append(button(c.title,()=>openCourse(c.id),'button secondary')));}
  }
  async function load() {
    const data=await request('/api/courses'+(filter==='deleted'?'?deleted=true':''));courses=data.courses;
    const live=filter==='deleted'?(await request('/api/courses')).courses:courses;
    state.courses=live;renderSidebar();dashboard();CourseList();
  }
  async function open() {
    if(state.busy)return;
    invalidateNavigation();
    MindOSUniverse.hideStandalone();MindOSUniverse.navigation('courses');
    state.courseId=null;state.data=null;state.draft=null;
    for(const id of ['welcome','review-view','course-view'])$(id).hidden=true;
    $('course-management').hidden=false;$('breadcrumb').textContent='课程管理 · 我的课程';
    await action(null,'正在读取课程…',load);
  }
  $('course-manager-open').addEventListener('click',open);
  $('manager-new').addEventListener('click',()=>{showWelcome();$('course-title-input').focus();});
  $('manager-filter').addEventListener('change',event=>{if(state.busy){event.target.value=filter;return;}filter=event.target.value;action(null,'正在读取课程…',load);});
  $('manager-edit-cancel').addEventListener('click',()=>$('course-editor').close());
  $('course-editor-form').addEventListener('submit',event=>{event.preventDefault();if(!editing)return;
    action($('manager-edit-save'),'正在保存课程信息…',async()=>{
      const body={};for(const key of ['title','description','cover','goal','level','status'])body[key]=$('manager-edit-'+key).value;
      body.tags=$('manager-edit-tags').value.split(/[、,，]/).map(s=>s.trim()).filter(Boolean);
      try{await request(`/api/courses/${editing.id}`,'PUT',body);}catch(error){$('manager-edit-error').textContent=error.message;throw error;}$('course-editor').close();await load();
    });
  });
  $('manager-delete-cancel').addEventListener('click',()=>$('course-delete-confirm').close());
  $('manager-delete-form').addEventListener('submit',event=>{event.preventDefault();if(!deleting)return;
    const {course,permanent}=deleting;action($('manager-delete-submit'),'正在更新回收站…',async()=>{
      try{await request(`/api/courses/${course.id}`+(permanent?'/permanent':''),'DELETE',permanent?{confirm_title:$('manager-delete-input').value}:undefined);}catch(error){$('manager-delete-error').textContent=error.message;throw error;}
      $('course-delete-confirm').close();await load();
    });
  });
  return {open,dashboard};
})();
