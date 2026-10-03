/* Developer-only metadata. No full context, model analysis or confidence numbers. */
const MindOSTutorQuality=(()=>{
 let enabled=false,key='',generation=0,root=null;
 function enable(value){enabled=value===true;if(!enabled&&root){root.remove();root=null;}key='';}
 async function render(cid,signature){
  if(!enabled)return;
  const next=cid+':'+signature;if(key===next)return;key=next;const version=++generation;
  if(!root){root=node('details','','tutor-quality-debug');root.id='tutor-quality-debug';$('assistant-chat-form').before(root);}
  root.replaceChildren(node('summary','导师质量记录（开发模式）'));
  if(!cid)return;
  try{
   const response=await fetch('/api/tutor/quality-debug?context_id='+encodeURIComponent(cid));
   const data=await response.json();if(version!==generation||!enabled)return;
   if(!response.ok){root.hidden=true;return;}
   root.hidden=false;const last=data.responses[0];
   if(last)root.append(node('p',`strategy: ${last.strategy} · quality: ${last.approved?'passed':'fallback'} · retry: ${last.retry_count}`,'muted'));
   else root.append(node('p','暂无回答质量记录。','muted'));
  }catch(_){if(version===generation&&root)root.hidden=true;}
 }
 return {enable,render};
})();
