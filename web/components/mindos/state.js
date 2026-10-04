/* One observable state object shared with the existing course APIs and components. */
(() => {
 const listeners=new Set();let value=null,scheduled=false;const changed=new Set();
 function create(initial){value=new Proxy(initial,{set(target,key,next){if(target[key]===next)return true;target[key]=next;changed.add(key);if(!scheduled){scheduled=true;queueMicrotask(()=>{scheduled=false;const keys=[...changed];changed.clear();for(const listener of listeners)listener(snapshot(),keys);});}return true;}});return value;}
 function snapshot(){if(!value)return {};if(value.page==='universe'){const s=value.universeSelection;return {page:'universe',currentCourse:s?.course||null,currentGalaxy:s?.course||null,currentNebula:s?.section||null,currentKnowledgeAtom:s?.star||null,userKnowledgeState:s?{mastery_state:s.star.mastery_state,basis:s.star.state_basis}:null,aiTutorState:value.aiTutorState||{},learningProgress:{}};}const data=['course','dashboard','growth','mission'].includes(value.page)&&value.courseId===value.data?.course.id?value.data:null,atom=data&&value.courseMode==='map'?value.atomDetail?.atom:null;return {
  page:value.page,currentCourse:data?.course||null,currentGalaxy:data?.course||null,currentNebula:atom?data?.course.sections.find(s=>s.ordinal===atom.section):data?.section||null,
  currentKnowledgeAtom:atom||null,userKnowledgeState:atom?value.atomDetail.learning_state||null:data?.learning_state||null,aiTutorState:value.aiTutorState||{},
  learningProgress:{sections:data?.mastery||null,knowledge:data?.knowledge||null},courseView:value.courseView||'learn'};}
 window.MindOSStore={create,getSnapshot:snapshot,subscribe(listener){listeners.add(listener);return ()=>listeners.delete(listener);}};
})();
