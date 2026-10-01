const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
 const page=await browser.newPage({viewport:{width:1440,height:960}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.context().addCookies([{name:'mindos_session',value:process.env.MINDOS_TEST_COOKIE,url:process.env.MINDOS_TEST_URL,httpOnly:true,sameSite:'Strict'}]);
 const open=async(name)=>{await page.locator('#course-list').getByRole('button',{name:new RegExp(name)}).click();await page.locator('#assistant-toggle').waitFor({state:'visible'});};
 const chat=async(text)=>{await page.locator('#assistant-question').fill(text);await page.locator('#assistant-send').click();await page.waitForFunction(()=>!document.getElementById('assistant-send').disabled);assert.equal(await page.locator('#assistant-error').textContent(),'');};
 await page.goto(process.env.MINDOS_TEST_URL);await page.locator('#assistant-toggle').waitFor({state:'visible'});
 await open('Attention课程');const firstCid=await page.evaluate(()=>state.courseId);
 await page.evaluate(()=>window.scrollTo(0,900));const rect=await page.locator('#assistant-toggle').boundingBox();assert(rect.y>=0&&rect.y<960);
 const initial=await page.locator('#assistant-toggle').boundingBox();await page.mouse.move(initial.x+28,initial.y+28);await page.mouse.down();await page.mouse.move(350,650,{steps:8});await page.mouse.up();
 const moved=await page.locator('#assistant-toggle').boundingBox();assert(Math.abs(moved.x-initial.x)>100);
 await page.waitForFunction(async cid=>{const result=await fetch(`/api/courses/${cid}/assistant/history`).then(r=>r.json());return !!result.position;},firstCid);
 await page.reload();await open('Attention课程');await page.waitForFunction(()=>!document.getElementById('assistant-question').disabled);
 const saved=await page.locator('#assistant-toggle').boundingBox();assert(Math.abs(saved.x-moved.x)<2);assert(Math.abs(saved.y-moved.y)<2);
 await page.locator('#assistant-toggle').click();assert.equal(await page.locator('#assistant-panel').isVisible(),true);
 assert.match(await page.locator('#assistant-context').textContent(),/Attention基础/);await chat('什么是 Attention？');
 assert.match(await page.locator('#assistant-messages').textContent(),/Attention课程/);
 assert.equal(await page.evaluate(()=>state.data.knowledge.tested_count),0);assert.equal(await page.evaluate(()=>state.data.course.current_ordinal),1);
 await page.locator('#assistant-messages button[data-atom-id="a1"]').first().click();await page.waitForFunction(()=>state.atomDetail?.atom.id==='a1');
 await page.locator('#assistant-toggle').click();assert.match(await page.locator('#assistant-context').textContent(),/知识点：Attention/);await chat('为什么要关注不同信息？');
 await chat('最新软件版本有什么更新？');assert.match(await page.locator('#assistant-messages').textContent(),/未阅读全文/);assert.equal(await page.locator('#assistant-messages a.assistant-source').count(),1);
 await page.locator('#assistant-close').click();await page.reload();await open('Attention课程');await page.waitForFunction(()=>!document.getElementById('assistant-question').disabled);await page.locator('#assistant-toggle').click();assert.equal(await page.locator('.assistant-chat-message').count(),6);
 await page.locator('#assistant-close').click();await open('独立图论课程');await page.waitForFunction(()=>!document.getElementById('assistant-question').disabled);await page.locator('#assistant-toggle').click();assert.equal(await page.locator('.assistant-chat-message').count(),0);await chat('请解释这门课程');assert.match(await page.locator('#assistant-messages').textContent(),/独立图论课程/);assert.doesNotMatch(await page.locator('#assistant-messages').textContent(),/最新软件版本/);
 await page.setViewportSize({width:390,height:844});await page.locator('#assistant-panel').waitFor({state:'visible'});const panel=await page.locator('#assistant-panel').boundingBox();assert(panel.x>=0&&panel.x+panel.width<=390);assert(panel.y>=0&&panel.y+panel.height<=844);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 await page.locator('#assistant-close').click();await page.locator('#course-manager-open').click();await page.waitForFunction(()=>!state.busy);assert.equal(await page.locator('#assistant-toggle').isVisible(),true);await page.locator('#assistant-toggle').click();assert.equal(await page.locator('#assistant-question').isDisabled(),true);assert.equal(await page.locator('.assistant-chat-message').count(),0);
 assert.deepEqual(errors,[]);console.log('PASS: floating drag and refresh, history, course/atom context, related jump, dynamic source disclosure, course isolation, no mastery/progression changes, mobile, global entry with no course leakage');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
