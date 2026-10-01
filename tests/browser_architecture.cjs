const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({headless:true,channel:'msedge'});try{
 const page=await browser.newPage({viewport:{width:1440,height:960}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.context().addCookies([{name:'mindos_session',value:process.env.MINDOS_TEST_COOKIE,url:process.env.MINDOS_TEST_URL,httpOnly:true,sameSite:'Strict'}]);
 await page.goto(process.env.MINDOS_TEST_URL);await page.waitForFunction(()=>state.courses.length===2);
 const ids=await page.evaluate(()=>Object.fromEntries(state.courses.map(c=>[c.title,c.id])));const a=ids['响应保护课程A'],b=ids['响应保护课程B'];
 const open=id=>page.evaluate(id=>openCourse(id),id);
 const idle=()=>page.waitForFunction(()=>!state.busy);
 async function defer(pattern){
  let resolveSeen,release;const seen=new Promise(r=>resolveSeen=r);const gate=new Promise(r=>release=r);
  await page.route(pattern,async route=>{const response=await route.fetch();resolveSeen();await gate;await route.fulfill({response});});
  return {seen,release,remove:()=>page.unroute(pattern)};
 }
 await open(a);
 let delayed=await defer('**/api/sections/lesson');await page.locator('#lesson-generate').click();await delayed.seen;await open(b);delayed.release();await idle();await delayed.remove();
 assert.equal(await page.evaluate(()=>state.courseId),b);assert.equal(await page.locator('#course-title').textContent(),'响应保护课程B');
 assert.equal(await page.evaluate(async a=>(await fetch('/api/course?course_id='+a).then(r=>r.json())).section.lesson!==null,a),true);
 await open(a);delayed=await defer('**/api/sections/ask');await page.locator('#ask-input').fill('再解释一下');await page.locator('#ask-form button').click();await delayed.seen;await page.locator('#home-link').click();delayed.release();await idle();await delayed.remove();
 assert.equal(await page.evaluate(()=>state.page),'dashboard');assert.equal(await page.locator('#learning-dashboard').isVisible(),true);assert.equal(await page.locator('#notice').isVisible(),false);
 delayed=await defer('**/api/course?course_id='+a);await page.evaluate(a=>{openCourse(a);},a);await delayed.seen;await open(b);delayed.release();await page.waitForTimeout(250);await delayed.remove();assert.equal(await page.evaluate(()=>state.courseId),b);
 await open(a);await page.locator('#mode-map').click();await page.locator('#knowledge-sections button').filter({hasText:'概念 1'}).first().click();await page.waitForFunction(()=>state.atomDetail?.atom.id==='a1');
 delayed=await defer('**/api/atoms/lesson');await page.locator('#atom-quick').click();await delayed.seen;await open(b);delayed.release();await idle();await delayed.remove();assert.equal(await page.evaluate(()=>state.courseId),b);assert.equal(await page.evaluate(()=>state.atomDetail),null);
 await page.locator('#lesson-generate').click();await idle();const old=await page.evaluate(()=>state.data.section.lesson);
 await page.evaluate(async b=>{const r=await fetch('/api/courses/'+b,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({goal:'掌握考试技巧',level:'基础'})});if(!r.ok)throw new Error(await r.text());},b);
 await open(b);assert.match(await page.locator('#lesson-version-note').textContent(),/基于旧版/);assert.equal(await page.locator('#lesson-generate').isVisible(),true);
 await page.locator('#lesson-generate').click();await idle();assert.equal(await page.locator('#lesson-version-note').textContent(),'');assert.equal(await page.locator('#lesson-history details').count(),1);assert.equal(await page.evaluate(()=>state.data.lesson_history[0].snapshot.lesson),old);
 assert.equal(await page.evaluate(()=>state.data.course.current_ordinal),1);assert.equal(await page.evaluate(()=>state.data.mastery.overall_rate),null);
 await open(a);await page.locator('#mode-map').click();await page.locator('#production-panel summary').first().click();await page.locator('.candidate-merge').waitFor();assert.match(await page.locator('#production-batches').textContent(),/已有定义/);
 await page.locator('.candidate-merge').selectOption('keep');await page.getByRole('button',{name:'确认选中候选，加入知识地图'}).click();await idle();assert.equal(await page.evaluate(()=>state.data.knowledge.atoms.find(a=>a.id==='a1').summary),'一句话定义');assert.equal(await page.evaluate(()=>state.data.knowledge.atoms.find(a=>a.id==='a1').quality_status),'candidate');
 assert.deepEqual(errors,[]);console.log('PASS: delayed lesson/course/atom responses, home navigation, explicit duplicate-definition choice, stale lesson warning, regeneration with old version and unchanged mastery');
 }finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
