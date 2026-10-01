// Optional source-production regression against tests/browser_fixture.py.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try {
 const page=await browser.newPage({viewport:{width:1440,height:960}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.context().addCookies([{name:'mindos_session',value:process.env.MINDOS_TEST_COOKIE,url:process.env.MINDOS_TEST_URL,httpOnly:true,sameSite:'Strict'}]);
 const idle=()=>page.waitForFunction(()=>!state.busy && document.getElementById('notice').hidden);
 await page.goto(process.env.MINDOS_TEST_URL);await page.locator('#course-list button').first().click();
 await page.locator('#mode-map').click();if(await page.locator('#graph-build').isVisible()){await page.locator('#graph-build').click();await idle();}
 const count=await page.locator('.map-node').count();
 await page.locator('#production-panel summary').first().click();
 await page.locator('#source-title').fill('浏览器原文资料');
 await page.locator('#source-text').fill('# 基础概念\n\n定义：概念是一类事物的共同属性，使用实例能够帮助初学者逐步理解。\n\n## 实例\n\n例子：观察生活中的物品并描述其共同属性。');
 await page.locator('#source-text-form button').click();await idle();
 await page.locator('#production-process').waitFor({state:'visible'});
 assert.match(await page.locator('#source-detail').textContent(),/基础概念/);
 await page.locator('#production-process').click();await idle();
 assert.equal(await page.locator('.map-node').count(),count);
 assert.match(await page.locator('#production-batches').textContent(),/尚未交叉核验/);
 await page.getByRole('button',{name:'确认选中候选，加入知识地图'}).click();await idle();
 await page.waitForFunction(()=>document.getElementById('production-batches').textContent.includes('已审查导入'));
 assert.equal(await page.locator('.map-node').count(),count+1);
 await page.locator('#knowledge-sections button').filter({hasText:'资料知识点'}).click();
 await page.locator('#atom-panel').waitFor({state:'visible'});
 assert.match(await page.locator('#atom-sources').textContent(),/浏览器原文资料.*定义：/s);
 await page.locator('#source-file').setInputFiles({name:'结构笔记.md',mimeType:'text/markdown',buffer:Buffer.from('# 标题\n\n定义：这份上传资料保留完整段落，不能被普通字符切片替代。')});
 await page.locator('#source-file-form button').click();await idle();
 assert.match(await page.locator('#source-detail').textContent(),/用户上传/);
 await page.reload();await page.locator('#course-list button').first().click();
 await page.locator('#production-panel summary').first().click();
 await page.waitForFunction(()=>document.getElementById('source-list').textContent.includes('结构笔记'));
 assert.match(await page.locator('#production-batches').textContent(),/已审查导入/);
 await page.setViewportSize({width:390,height:844});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 assert.deepEqual(errors,[]);
 console.log('PASS: text/upload -> structure -> candidates -> explicit import -> source trace -> reload -> 390px mobile; no browser errors');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
