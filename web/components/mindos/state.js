/* One observable state object shared with the existing course APIs and components. */
(() => {
 const listeners=new Set();let value=null,scheduled=false;const changed=new Set();
 function create(initial){value=new Proxy(initial,{set(target,key,next){if(target[key]===next)return true;target[key]=next;changed.add(key);if(!scheduled){scheduled=true;queueMicrotask(()=>{scheduled=false;const keys=[...changed];changed.clear();for(const listener of listeners)listener(snapshot(),keys);});}return true;}});return value;}
 function snapshot(){if(!value)return {};const data=['course','dashboard','growth'].includes(value.page)&&value.courseId===value.data?.course.id?value.data:null,atom=data&&value.courseMode==='map'?value.atomDetail?.atom:null;return {
  page:value.page,currentCourse:data?.course||null,currentGalaxy:atom?data?.course.sections.find(s=>s.ordinal===atom.section):data?.section||null,
  currentKnowledgeAtom:atom||null,userKnowledgeState:atom?value.atomDetail.learning_state||null:data?.learning_state||null,aiTutorState:value.aiTutorState||{},
  learningProgress:{sections:data?.mastery||null,knowledge:data?.knowledge||null},courseView:value.courseView||'learn'};}
 window.MindOSStore={create,getSnapshot:snapshot,subscribe(listener){listeners.add(listener);return ()=>listeners.delete(listener);}};
})();
