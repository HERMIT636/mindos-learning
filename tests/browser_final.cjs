const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({headless:true,channel:'msedge'});try{
 const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.context().addCookies([{name:'mindos_session',value:process.env.MINDOS_TEST_COOKIE,url:process.env.MINDOS_TEST_URL,httpOnly:true,sameSite:'Strict'}]);
 const idle=()=>page.waitForFunction(()=>!state.busy);
 const panel=page.locator('#course-final-panel');
 const open=async title=>{if(page.viewportSize().width<800){await page.locator('#course-manager-open').click();const card=page.locator('.manager-course-card').filter({hasText:title});await card.locator('.action-row').getByRole('button',{name:'进入学习',exact:true}).click();}else await page.locator('#course-list').getByRole('button',{name:new RegExp(title)}).click();await page.waitForFunction(t=>state.page==='course'&&state.data?.course.title===t,title);};
 const click=async(name,area=panel)=>{await area.getByRole('button',{name,exact:true}).click();await idle();};
 const answer=async(value='a',short=false)=>{const form=page.locator(short?'#learning-loop-panel .loop-assessment form':'#course-final-panel .final-question');await form.waitFor();for(const input of await form.locator(`input[value="${value}"]`).all())await input.check({force:true});for(const select of await form.locator('[data-confidence-index]').all())await select.selectOption('high');await form.getByRole('button',{name:short?'提交短检测':'提交这道题',exact:true}).click();await idle();};
 const completeFinal=async()=>{for(let i=0;i<12;i++){if(await page.evaluate(()=>state.data.course_final.plan.status!=='active'))return;if(await page.locator('.final-question').count()===0)await click('继续下一道检测题');if(await page.locator('.final-question').count())await answer();}throw Error('Final plan did not end within policy bound');};
 await page.goto(process.env.MINDOS_TEST_URL);await open('终局闭环演示课程');assert.equal(await page.evaluate(()=>state.data.course.current_ordinal),3);
 await click('课程内容已学完');assert.equal(await page.evaluate(()=>state.data.course_final.mastery_state.mastery_score),null);await click('开始课程掌握检测');await click('继续下一道检测题');const first=await page.evaluate(()=>state.data.course_final.current_quiz.id),planId=await page.evaluate(()=>state.data.course_final.plan.id);
 await page.locator('#assistant-toggle').click();assert.match(await page.locator('#assistant-context').textContent(),/课程掌握检测/);await page.locator('#assistant-close').click();
 await page.reload();await open('终局闭环演示课程');assert.equal(await page.evaluate(()=>state.data.course_final.plan.id),planId);assert.equal(await page.evaluate(()=>state.data.course_final.current_quiz.id),first);await answer();await completeFinal();
 await panel.getByRole('heading',{name:'这门课学到了什么？'}).waitFor();assert.equal(await page.evaluate(()=>state.data.course_final.mastery_state.status),'needs_reinforcement');assert.match(await panel.textContent(),/长期记忆仍需/);
 if(process.env.MINDOS_SCREENSHOTS)await panel.screenshot({path:'docs/validation/learning-loop-p1-report-desktop.png'});
 await click('只补强当前缺口');assert.equal(await page.evaluate(()=>state.data.course_final.repair_plan.status),'active');
 for(let i=0;i<5;i++){
  if(await page.evaluate(()=>state.data.course_final.repair_plan.status==='needs_verification'))break;
  await panel.getByRole('button',{name:'进入短时补强',exact:true}).first().click();await idle();const loop=page.locator('#learning-loop-panel');await click('开始短诊断',loop);
  if(i===0){await answer('b',true);await click('看短讲解与例子',loop);assert(await loop.locator('.teaching-block').count()>0);await click('做补强检测',loop);await answer('a',true);}else await answer('a',true);
 }
 assert.equal(await page.evaluate(()=>state.data.course_final.repair_plan.status),'needs_verification');assert.notEqual(await page.evaluate(()=>state.data.course_final.mastery_state.status),'mastered');await click('补强完成，用新题重新验证');await completeFinal();assert.equal(await page.evaluate(()=>state.data.course_final.plan.status),'completed');assert.equal(await page.evaluate(()=>state.data.course.current_ordinal),3);
 await click('生成一段通俗说明');assert.match(await panel.textContent(),/能力判断仍以独立答题/);
 await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 if(process.env.MINDOS_SCREENSHOTS)await panel.screenshot({path:'docs/validation/learning-loop-p1-report-mobile.png'});
 await open('稍后检测课程');await click('课程内容已学完');await click('开始课程掌握检测');await click('继续下一道检测题');const old=await page.evaluate(()=>state.data.course_final.current_quiz.id);await click('先结束课程，保留待巩固知识');assert.equal(await page.evaluate(()=>state.data.course_final.mastery_state.status),'completed_with_gaps');const rejected=await page.evaluate(async q=>{const r=await fetch('/api/quizzes/submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({course_id:state.courseId,quiz_id:q,answers:['a']})});return r.status;},old);assert.equal(rejected,400);
 await page.reload();await open('稍后检测课程');assert.match(await panel.textContent(),/仍有待巩固知识/);assert.deepEqual(errors,[]);console.log('PASS: final content completion separate from mastery; planning, independent concept/application/novel scenario questions, persisted pending plan/question; unknown long-term memory, immutable report; P0 diagnosis/micro teaching/check and full targeted reassessment; report explanation; defer with gaps and stale submit rejection; desktop/mobile no overflow.');
 }finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1);});
