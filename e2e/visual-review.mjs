import {chromium,request} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import {spawn} from 'node:child_process';

const root=path.resolve(import.meta.dirname,'..'),out=path.join(root,'test-results','screenshots');
const port=8890,base=`http://127.0.0.1:${port}`,run=Date.now();
await fs.mkdir(out,{recursive:true});
const server=spawn(path.join(root,'.venv','Scripts','python.exe'),['scripts/serve.py','--port',String(port),'--parent',String(process.pid)],{cwd:root,windowsHide:true,stdio:'ignore',env:{...process.env,SCHEDULE_BUILDER_DB:path.join(root,'test-results',`visual-${run}.sqlite`),SCHEDULE_BUILDER_ROUTE_CACHE:path.join(root,'test-results',`visual-routes-${run}.sqlite`),SCHEDULE_BUILDER_OFFLINE:'1'}});
let browser;
const results=[];
try{
 let ready=false;for(let n=0;n<100;n++){try{ready=(await fetch(`${base}/health`)).ok;if(ready)break}catch{}await new Promise(r=>setTimeout(r,200))}if(!ready)throw Error('Visual review server did not start');
 const client=await request.newContext({baseURL:base});
 const demo=await client.post('/api/demo');if(!demo.ok())throw Error(await demo.text());
 const tomorrow=new Date(Date.now()+86400000).toLocaleDateString('en-CA',{timeZone:'America/Toronto'});
 const generated=await client.post('/api/schedules/generate',{data:{date:tomorrow,mode:'balanced'},timeout:45000});if(!generated.ok())throw Error(await generated.text());
 console.log('Visual seed solver:',(await generated.json()).status);
 browser=await chromium.launch({channel:'msedge',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1000}});const page=await context.newPage();
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('https://tile.openstreetmap.org/**',r=>r.fulfill({status:200,contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j85sAAAAASUVORK5CYII=','base64')}));
 await page.goto(base);await page.getByRole('button',{name:'Generate My Schedule',exact:true}).waitFor();
 async function nav(text){const toggle=page.getByRole('button',{name:'Open navigation',exact:true});if(await toggle.isVisible()&&!await page.locator('.sidebar').evaluate(e=>e.classList.contains('open')))await toggle.click();await page.locator('.nav-item').filter({hasText:text}).first().click()}
 async function capture(name){await page.screenshot({path:path.join(out,`${name}.png`),fullPage:true,animations:'disabled'});const axe=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);results.push({name,overflow,violations:axe.violations.map(v=>({id:v.id,impact:v.impact,description:v.description,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}))});console.log(name,JSON.stringify(results.at(-1)))}
 for(const theme of ['light','dark','midnight','warm']){
  await page.setViewportSize({width:1440,height:1000});await nav('Overview');await page.getByLabel('Theme',{exact:true}).selectOption(theme);await capture(`review-overview-${theme}`);
  await nav('Daily planner');await capture(`review-planner-${theme}`);
  await page.setViewportSize({width:390,height:844});await capture(`review-mobile-${theme}`);
 }
 await page.setViewportSize({width:768,height:1024});await capture('review-tablet-warm');
 await page.setViewportSize({width:1440,height:1000});await nav('Tasks & deadlines');await page.locator('.task-card-title').first().click();await capture('review-dialog-warm');
 await fs.writeFile(path.join(root,'test-results','visual-review.json'),JSON.stringify({results,errors},null,2));
 if(errors.length||results.some(r=>r.overflow||r.violations.length))process.exitCode=1;
 await client.dispose();
}catch(e){console.error(e);process.exitCode=1}finally{if(browser)await browser.close();server.kill()}


