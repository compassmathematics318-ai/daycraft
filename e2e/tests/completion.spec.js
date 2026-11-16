import {test,expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {sundayOf,addDays,weekTab} from '../task-helpers.js';

// All plans below are seeded saved-plan fixtures, never claimed as solver output.
const root=path.resolve(import.meta.dirname,'../..');
const prefix=process.env.DAYCRAFT_QA_RUN||'completion';
async function json(request,url,method='get',data){const response=await request[method](url,{data,...(url.includes('/schedules/generate')?{timeout:45000}:{})});expect(response.ok(),await response.text()).toBeTruthy();return response.status()===204?null:response.json()}
const state=request=>json(request,'/api/state');
const week=(request,date)=>json(request,`/api/task-week?week_start=${sundayOf(date)}`);
const assignment=async(request,date,id)=>(await week(request,date)).assignments.find(a=>a.task_definition_id===id);
const endpoint=(plan,block)=>`/api/schedules/${plan.id}/blocks/${block.id}/completion`;
const complete=(request,plan,block,completed=true)=>json(request,endpoint(plan,block),'post',{completed});
async function nav(page,text='Daily planner'){const toggle=page.getByRole('button',{name:'Open navigation',exact:true});if(await toggle.isVisible()&&!await page.locator('.sidebar').evaluate(e=>e.classList.contains('open')))await toggle.click();await page.locator('.nav-item').filter({hasText:text}).first().click()}
async function planner(page,date){await nav(page,'Overview');await page.getByLabel('Planning date',{exact:true}).fill(date);await nav(page)}
async function openBlock(page,block){await page.locator('.timeline-block').filter({hasText:block.title}).click();await expect(page.getByRole('dialog')).toBeVisible()}
async function fixture(request,{date,title,minutes=60,chunks=[60],definition,recurring=false,status='todo',kind='project',mode='balanced'}){
 const task=definition??await json(request,'/api/task-definitions','post',{title,session_minutes:minutes,min_sessions_per_week:1,allow_splitting:chunks.length>1,min_chunk_minutes:Math.min(...chunks),...(recurring?{recurrence:{start_week:sundayOf(date)}}:{})});
 let target=await assignment(request,date,task.id);
 if(!target||target.is_virtual)target=await json(request,'/api/task-weeks','post',{task_definition_id:task.id,week_start:sundayOf(date),session_minutes:minutes,min_sessions_per_week:1});
 const sid=randomUUID(),plan={id:randomUUID(),date,mode,status:'feasible',solver_status:'SEEDED_QA_FIXTURE_NOT_GENERATED',blocks:[],conflicts:[],unallocated:[],explanations:['Explicit seeded saved-plan QA fixture; no generation performed.'],stats:{}};
 let time=Date.parse(`${date}T09:00:00-05:00`);
 plan.blocks=chunks.map((length,i)=>{const start=new Date(time).toISOString();time+=(length+10)*60000;return {id:randomUUID(),title:`${title} chunk ${i+1}`,kind,start,end:new Date(time-10*60000).toISOString(),task_id:task.id,task_definition_id:task.id,task_assignment_id:target.id,logical_session_id:sid,chunk_index:i,location_id:null,location_mode:'unspecified',locked:false,status,rationale:'Seeded saved-plan fixture',estimated:false}});
 execFileSync(path.join(root,'.venv/Scripts/python.exe'),[path.join(root,'e2e/completion-fixture.py'),process.env.DAYCRAFT_COMPLETION_DB],{cwd:root,input:JSON.stringify({plans:[plan],sessions:[{id:sid,assignment_id:target.id,index:(target.sessions??[]).length,target_minutes:minutes}]}),windowsHide:true});
 return {plan,task,target,sid};
}
async function audit(page,name){const dir=`../test-results/${prefix}-screenshots`;await fs.mkdir(dir,{recursive:true});await expect(page.locator('.toast')).toHaveCount(0);await page.screenshot({path:`${dir}/${name}.png`,fullPage:true,animations:'disabled'});const result=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();await fs.writeFile(`${dir}/${name}.axe.json`,JSON.stringify(result.violations,null,2));expect(result.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}))).toEqual([]);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);if(await page.getByRole('dialog').count())expect(await page.getByRole('dialog').evaluate(e=>e.scrollWidth<=e.clientWidth+1)).toBe(true);const heroSelect=page.locator('.hero .workload-control select');if(await heroSelect.count())expect(await heroSelect.evaluate(select=>{const box=select.getBoundingClientRect(),hero=select.closest('.hero').getBoundingClientRect();return box.left>=hero.left+16&&box.right<=hero.right-16}),`Workload select must fit inside hero padding (${name})`).toBe(true)}

test('elapsed saved-plan work confirms once, persists through refresh, and undoes exactly once',async({page,request})=>{
 const {plan,task}=await fixture(request,{date:'2020-02-03',title:'QA completion elapsed'}),block=plan.blocks[0];
 expect(await assignment(request,plan.date,task.id)).toMatchObject({completed_minutes:0,completed_sessions:0});
 await page.goto('/');await planner(page,plan.date);await openBlock(page,block);
 await expect(page.getByRole('button',{name:'Mark Session Completed',exact:true})).toBeEnabled();
 expect(await page.getByLabel('Activity status',{exact:true}).locator('option').allTextContents()).not.toContain('Completed');
 await page.getByRole('button',{name:'Mark Session Completed',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
 await expect(page.locator('.timeline-block').filter({hasText:block.title})).toContainText('Session completed');
 const first=await complete(request,plan,block),confirmed=first.blocks.find(b=>b.id===block.id);
 expect(confirmed).toMatchObject({status:'completed',completion_verified:true});expect(confirmed.completion_confirmed_at).toBeTruthy();
 expect(await assignment(request,plan.date,task.id)).toMatchObject({completed_minutes:60,completed_sessions:1});
 const repeated=await complete(request,plan,block);expect(repeated.blocks.find(b=>b.id===block.id).completion_confirmed_at).toBe(confirmed.completion_confirmed_at);
 await page.reload();await planner(page,plan.date);await openBlock(page,block);await expect(page.getByRole('button',{name:'Undo Completion',exact:true})).toBeEnabled();await page.getByRole('button',{name:'Undo Completion',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
 await complete(request,plan,block,false);expect(await assignment(request,plan.date,task.id)).toMatchObject({completed_minutes:0,completed_sessions:0});
 expect((await state(request)).task_definitions.find(t=>t.id===task.id).status).toBe('active');
});

test('future saved-plan work cannot be completed through details or either status API',async({page,request})=>{
 const {plan,task}=await fixture(request,{date:'2040-02-06',title:'QA completion future'}),block=plan.blocks[0];
 await page.goto('/');await planner(page,plan.date);await openBlock(page,block);await expect(page.getByRole('button',{name:'Mark Session Completed',exact:true})).toBeDisabled();
 const denied=await request.post(endpoint(plan,block),{data:{completed:true}});expect(denied.status()).toBe(409);
 const generic=await request.put(`/api/schedules/${plan.id}`,{data:{blocks:plan.blocks.map(b=>({...b,status:'completed'}))}});expect(generic.ok()).toBe(false);expect(await generic.text()).toMatch(/completion|ended|end|future/i);
 expect(await assignment(request,plan.date,task.id)).toMatchObject({completed_minutes:0,completed_sessions:0});
});

test('completed history reversal restores only the selected started chunk and persists across refresh',async({page,request})=>{
 const {plan,task}=await fixture(request,{date:'2020-08-03',title:'QA history targeted reversal',chunks:[20,40],status:'in_progress',recurring:true});
 const later=await fixture(request,{date:addDays(plan.date,7),title:'QA history independent next week',definition:task});
 const unrelated=await fixture(request,{date:'2020-08-04',title:'QA history unrelated work'});
 for(const block of plan.blocks)await complete(request,plan,block);
 await complete(request,unrelated.plan,unrelated.plan.blocks[0]);
 const laterBefore=await assignment(request,later.plan.date,task.id),unrelatedBefore=await assignment(request,unrelated.plan.date,unrelated.task.id);
 const detached=await json(request,'/api/schedule-archives','post',{schedule_id:plan.id});
 const detachedBefore=await json(request,`/api/schedule-archives/${detached.id}`);
 await json(request,'/api/schedule-archives','post',{schedule_id:plan.id,new_version:true});
 const saved=await json(request,'/api/schedule-archives','post',{schedule_id:plan.id});
 const query=`/api/completed-tasks?q=${encodeURIComponent(task.title)}`;
 const before=await json(request,query),record=before.items.find(item=>item.source_block_id===plan.blocks[0].id);
 expect(record).toBeTruthy();expect(before.summary.completed_minutes).toBe(60);
 await page.goto('/');await nav(page,'Completed Tasks');await page.getByLabel('Search completed work',{exact:true}).fill(task.title);
 await expect(page.locator('.completed-row')).toHaveCount(2);
 const row=page.locator('.completed-row').filter({has:page.locator('.completed-row-duration').filter({hasText:'20m'})});
 await row.getByRole('button',{name:'Mark as Not Completed',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'Mark this session as not completed?',exact:true});
 await expect(dialog).toBeVisible();await expect(page.locator('.completed-row')).toHaveCount(2);
 await dialog.getByRole('button',{name:'Mark as Not Completed',exact:true}).click();
 await expect(page.getByRole('dialog')).toHaveCount(0);await expect(page.locator('.completed-row')).toHaveCount(1);
 const after=(await json(request,`/api/schedules?date=${plan.date}`)).find(item=>item.id===plan.id);
 const changed=after.blocks.find(item=>item.id===plan.blocks[0].id),untouched=after.blocks.find(item=>item.id===plan.blocks[1].id);
 expect(changed.status).toBe('in_progress');expect(changed.completion_verified??false).toBe(false);expect(changed.completion_confirmed_at??null).toBeNull();
 for(const field of ['start','end','task_id','task_assignment_id','logical_session_id','location_id','locked'])expect(changed[field]).toBe(plan.blocks[0][field]);
 expect(untouched).toMatchObject({status:'completed',completion_verified:true});
 expect(await assignment(request,plan.date,task.id)).toMatchObject({completed_minutes:40,completed_sessions:0});
 expect(await assignment(request,later.plan.date,task.id)).toEqual(laterBefore);
 expect(await assignment(request,unrelated.plan.date,unrelated.task.id)).toEqual(unrelatedBefore);
 expect((await state(request)).task_definitions.find(item=>item.id===task.id).status).toBe('active');
 expect((await json(request,query)).items.map(item=>item.id)).not.toContain(record.id);
 expect((await json(request,`/api/schedule-archives/${saved.id}`)).payload.blocks.find(item=>item.id===changed.id).status).toBe('in_progress');
 expect((await json(request,`/api/schedule-archives/${detached.id}`)).payload).toEqual(detachedBefore.payload);
 await page.reload();await nav(page,'Completed Tasks');await page.getByLabel('Search completed work',{exact:true}).fill(task.title);await expect(page.locator('.completed-row')).toHaveCount(1);
 await planner(page,plan.date);await openBlock(page,plan.blocks[0]);await expect(page.getByRole('combobox',{name:'Activity status',exact:true})).toHaveValue('in_progress');
});

test('completed history confirmation supports keyboard cancellation without changing saved progress',async({page,request})=>{
 const {plan,task}=await fixture(request,{date:'2020-09-07',title:'QA history confirmation cancellation'});
 await complete(request,plan,plan.blocks[0]);
 const query=`/api/completed-tasks?q=${encodeURIComponent(task.title)}`;
 const before=await json(request,query),progress=await assignment(request,plan.date,task.id),saved=await json(request,`/api/schedules?date=${plan.date}`);
 let posts=0;page.on('request',r=>{if(r.method()==='POST'&&/\/completed-tasks\/[^/]+\/reverse$/.test(new URL(r.url()).pathname))posts++});
 await page.goto('/');await nav(page,'Completed Tasks');await page.getByLabel('Search completed work',{exact:true}).fill(task.title);
 const opener=page.locator('.completed-row').getByRole('button',{name:'Mark as Not Completed',exact:true});
 const dialog=page.getByRole('dialog',{name:'Mark this session as not completed?',exact:true});
 await opener.focus();await page.keyboard.press('Enter');await expect(dialog).toBeVisible();
 await expect(dialog).toContainText('This will reverse the completion of this work session and update your task progress. The session will remain in your schedule.');
 const cancel=dialog.getByRole('button',{name:'Cancel',exact:true}),confirm=dialog.getByRole('button',{name:'Mark as Not Completed',exact:true});
 await expect(cancel).toBeFocused();await page.keyboard.press('Tab');await expect(confirm).toBeFocused();
 await page.keyboard.press('Tab');await expect(dialog.getByRole('button',{name:'Close dialog',exact:true})).toBeFocused();
 await page.keyboard.press('Shift+Tab');await expect(confirm).toBeFocused();
 await cancel.click();await expect(dialog).toHaveCount(0);await expect(opener).toBeFocused();
 await opener.click();await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);await expect(opener).toBeFocused();
 await opener.click();await dialog.getByRole('button',{name:'Close dialog',exact:true}).click();await expect(dialog).toHaveCount(0);
 await opener.click();await page.locator('.modal-backdrop').click({position:{x:4,y:4}});await expect(dialog).toBeVisible();
 await cancel.click();await expect(dialog).toHaveCount(0);
 expect(posts).toBe(0);expect(await json(request,query)).toEqual(before);
 expect(await assignment(request,plan.date,task.id)).toEqual(progress);expect(await json(request,`/api/schedules?date=${plan.date}`)).toEqual(saved);
 await page.reload();await nav(page,'Completed Tasks');await page.getByLabel('Search completed work',{exact:true}).fill(task.title);await expect(page.locator('.completed-row')).toHaveCount(1);
});

test('completed history confirmation waits for the backend, blocks duplicate submission, and recovers after failure',async({page,request})=>{
 const {plan,task}=await fixture(request,{date:'2020-10-05',title:'QA history confirmation failure'});await complete(request,plan,plan.blocks[0]);
 const query=`/api/completed-tasks?q=${encodeURIComponent(task.title)}`,before=await json(request,query),record=before.items[0],progress=await assignment(request,plan.date,task.id);
 const url=`**/api/completed-tasks/${record.id}/reverse`;let requests=0,fail=true,release;
 const gate=new Promise(resolve=>{release=resolve});
 await page.route(url,async route=>{requests++;if(fail){await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'QA reversal temporarily unavailable'})});return}await gate;await route.continue()});
 await page.goto('/');await nav(page,'Completed Tasks');await page.getByLabel('Search completed work',{exact:true}).fill(task.title);
 await page.locator('.completed-row').getByRole('button',{name:'Mark as Not Completed',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'Mark this session as not completed?',exact:true});
 await dialog.getByRole('button',{name:'Mark as Not Completed',exact:true}).click();
 await expect(dialog.getByRole('alert')).toContainText('QA reversal temporarily unavailable');await expect(dialog).toBeVisible();await expect(page.locator('.completed-row')).toHaveCount(1);
 await expect(page.getByRole('status').filter({hasText:'marked as not completed.'})).toHaveCount(0);
 expect(await json(request,query)).toEqual(before);expect(await assignment(request,plan.date,task.id)).toEqual(progress);
 fail=false;await dialog.getByRole('button',{name:'Mark as Not Completed',exact:true}).click();await expect.poll(()=>requests).toBe(2);
 await expect(dialog.getByRole('button',{name:'Cancel',exact:true})).toBeDisabled();
 await expect(dialog.locator('.form-actions button').last()).toBeDisabled();
 await page.keyboard.press('Enter');await page.keyboard.press('Enter');await page.keyboard.press('Escape');await dialog.getByRole('button',{name:'Close dialog',exact:true}).click();await page.locator('.modal-backdrop').click({position:{x:4,y:4}});
 await expect(dialog).toBeVisible();await expect(page.locator('.completed-row')).toHaveCount(1);expect(requests).toBe(2);
 await expect(page.getByRole('status').filter({hasText:'marked as not completed.'})).toHaveCount(0);
 expect(await json(request,query)).toEqual(before);expect(await assignment(request,plan.date,task.id)).toEqual(progress);
 release();await expect(dialog).toHaveCount(0);await expect(page.locator('.completed-row')).toHaveCount(0);
 await expect(page.getByRole('status').filter({hasText:'marked as not completed.'})).toContainText(record.title);
 expect(requests).toBe(2);expect((await json(request,query)).total).toBe(0);expect(await assignment(request,plan.date,task.id)).toMatchObject({completed_minutes:0,completed_sessions:0});
 await page.reload();await nav(page,'Completed Tasks');await page.getByLabel('Search completed work',{exact:true}).fill(task.title);await expect(page.locator('.completed-row')).toHaveCount(0);
});

test('completed history confirmation is accessible in four themes on desktop and mobile',async({page,request})=>{
 test.setTimeout(180000);const {plan,task}=await fixture(request,{date:'2020-11-02',title:'QA history reversal accessible session with retained task context'});await complete(request,plan,plan.blocks[0]);
 const errors=[];page.on('pageerror',error=>errors.push(error.message));await page.goto('/');
 for(const theme of ['light','dark','midnight','warm']){
  await page.setViewportSize({width:1440,height:1000});await page.getByLabel('Theme',{exact:true}).selectOption(theme);
  for(const [size,width,height]of [['desktop',1440,1000],['mobile',390,844]]){
   await page.setViewportSize({width,height});await nav(page,'Completed Tasks');await page.getByLabel('Search completed work',{exact:true}).fill(task.title);await expect(page.locator('.completed-row')).toHaveCount(1);
   await page.locator('.completed-row').getByRole('button',{name:'Mark as Not Completed',exact:true}).click();
   const dialog=page.getByRole('dialog',{name:'Mark this session as not completed?',exact:true});await expect(dialog).toBeVisible();
   await audit(page,`reversal-confirm-${size}-${theme}`);await page.screenshot({path:`../test-results/${prefix}-screenshots/reversal-confirm-${size}-${theme}-viewport.png`,animations:'disabled'});
   await dialog.getByRole('button',{name:'Cancel',exact:true}).click();await expect(dialog).toHaveCount(0);
  }
 }
 expect(errors).toEqual([]);expect(await assignment(request,plan.date,task.id)).toMatchObject({completed_minutes:60,completed_sessions:1});
});

test('split chunks retain one logical session and repeating weeks remain independent',async({page,request})=>{
 const first=await fixture(request,{date:'2020-03-02',title:'QA completion repeating split',chunks:[20,40],recurring:true});
 const later=await fixture(request,{date:addDays(first.plan.date,7),title:'QA completion independent week',definition:first.task});
 await complete(request,first.plan,first.plan.blocks[0]);expect(await assignment(request,first.plan.date,first.task.id)).toMatchObject({completed_minutes:20,completed_sessions:0});
 await complete(request,first.plan,first.plan.blocks[1]);await complete(request,first.plan,first.plan.blocks[1]);expect(await assignment(request,first.plan.date,first.task.id)).toMatchObject({completed_minutes:60,completed_sessions:1});
 expect(await assignment(request,later.plan.date,first.task.id)).toMatchObject({completed_minutes:0,completed_sessions:0,status:'todo'});
 await complete(request,first.plan,first.plan.blocks[0],false);expect(await assignment(request,first.plan.date,first.task.id)).toMatchObject({completed_minutes:40,completed_sessions:0});
 await page.goto('/');await nav(page,'Tasks & deadlines');await weekTab(page);await page.getByLabel('Task week date',{exact:true}).fill(sundayOf(first.plan.date));await expect(page.locator('.task-week-loading')).toHaveCount(0);await expect(page.locator('.task-week-stat').filter({hasText:'Verified completion'})).toContainText('40m');
 expect((await week(request,first.plan.date)).sessions.filter(s=>s.task_definition_id===first.task.id)).toHaveLength(1);
});

test('workload has five persisted date-specific values shared between pages while strategy is independent',async({page,request})=>{
 const date='2021-04-12',other=addDays(date,1);await fixture(request,{date,title:'QA workload metadata only',mode:'deep'});const savedBefore=await json(request,`/api/schedules?date=${date}`);await page.goto('/');await nav(page,'Overview');await page.getByLabel('Planning date',{exact:true}).fill(date);
 const select=page.getByRole('combobox',{name:'Workload Level',exact:true});await expect(select).toBeEnabled();await expect(select).toHaveValue('medium');expect(await select.locator('option').allTextContents()).toEqual(['Very Low','Low','Medium','High','Very High']);
 await expect(page.getByRole('combobox',{name:'Scheduling mode',exact:true})).toHaveCount(0);
 for(const level of ['very_low','low','medium','high','very_high']){await select.selectOption(level);await expect.poll(async()=>(await json(request,`/api/day-preferences/${date}`)).workload_level).toBe(level);await nav(page);await expect(page.getByRole('combobox',{name:'Workload Level',exact:true})).toHaveValue(level);await expect(page.getByRole('combobox',{name:'Scheduling mode',exact:true})).toHaveCount(0);await nav(page,'Overview')}
 await page.getByLabel('Planning date',{exact:true}).fill(other);await expect(select).toHaveValue('medium');await select.selectOption('low');await expect.poll(async()=>(await json(request,`/api/day-preferences/${other}`)).workload_level).toBe('low');
 await page.reload();await nav(page,'Overview');await page.getByLabel('Planning date',{exact:true}).fill(date);await expect(select).toHaveValue('very_high');await nav(page);await expect(page.getByRole('combobox',{name:'Workload Level',exact:true})).toHaveValue('very_high');
 expect((await json(request,`/api/day-preferences/${other}`)).workload_level).toBe('low');
 const savedAfter=await json(request,`/api/schedules?date=${date}`);expect(savedAfter).toHaveLength(savedBefore.length);
 expect(savedAfter[0]).toMatchObject({id:savedBefore[0].id,date,mode:'deep',solver_status:savedBefore[0].solver_status,blocks:savedBefore[0].blocks,preferences_dirty:true,needs_regeneration:true});
 expect(savedAfter[0].explanations).toEqual(expect.arrayContaining(savedBefore[0].explanations));
});

test('completed logical sessions can exceed the weekly minimum and undo restores prior started status',async({request})=>{
 const first=await fixture(request,{date:'2020-07-06',title:'QA completion extra sessions',status:'in_progress'}),second=await fixture(request,{date:'2020-07-07',title:'QA completion extra second',definition:first.task});
 await complete(request,first.plan,first.plan.blocks[0]);await complete(request,second.plan,second.plan.blocks[0]);expect(await assignment(request,first.plan.date,first.task.id)).toMatchObject({min_sessions_per_week:1,completed_sessions:2,completed_minutes:120,status:'in_progress'});
 const undone=await complete(request,first.plan,first.plan.blocks[0],false);expect(undone.blocks.find(b=>b.id===first.plan.blocks[0].id).status).toBe('in_progress');expect(await assignment(request,first.plan.date,first.task.id)).toMatchObject({completed_sessions:1,completed_minutes:60});expect((await state(request)).task_definitions.find(t=>t.id===first.task.id).status).toBe('active');
});

test('Schedule Date uses the configured timezone and shares navigation and workload across planner pages',async({page,request})=>{
 const original=(await state(request)).settings;
 // UTC is already the next day while Toronto is still on the preceding date.
 await page.clock.install({time:new Date('2026-03-09T02:30:00Z')});
 await json(request,'/api/settings','put',{...original,timezone:'America/Toronto'});
 await page.goto('/');await nav(page,'Overview');
 const selector=page.getByRole('region',{name:'Schedule Date',exact:true}),date=selector.getByLabel('Planning date',{exact:true});
 await selector.getByRole('button',{name:'Today',exact:true}).click();await expect(date).toHaveValue('2026-03-08');
 await expect(selector).toContainText('Sunday, March 8, 2026');
 await page.getByRole('combobox',{name:'Workload Level',exact:true}).selectOption('low');
 await expect.poll(async()=>(await json(request,'/api/day-preferences/2026-03-08')).workload_level).toBe('low');
 await selector.getByRole('button',{name:'Tomorrow',exact:true}).click();await expect(date).toHaveValue('2026-03-09');
 await expect(page.getByRole('combobox',{name:'Workload Level',exact:true})).toHaveValue('medium');
 await page.getByRole('combobox',{name:'Workload Level',exact:true}).selectOption('high');
 await expect.poll(async()=>(await json(request,'/api/day-preferences/2026-03-09')).workload_level).toBe('high');
 await nav(page);await expect(date).toHaveValue('2026-03-09');await expect(page.getByRole('combobox',{name:'Workload Level',exact:true})).toHaveValue('high');
 await selector.getByRole('button',{name:'Previous day',exact:true}).click();await expect(date).toHaveValue('2026-03-08');await expect(page.getByRole('combobox',{name:'Workload Level',exact:true})).toHaveValue('low');
 await selector.getByRole('button',{name:'Next day',exact:true}).click();await nav(page,'Overview');await expect(date).toHaveValue('2026-03-09');
 await date.fill('2028-02-29');await nav(page);await expect(date).toHaveValue('2028-02-29');await expect(selector).toContainText('Tuesday, February 29, 2028');
 await json(request,'/api/settings','put',original);
});

test('deleted elapsed history permits status-only confirmation and undo without restoring task eligibility',async({page,request})=>{
 const {plan,task}=await fixture(request,{date:'2020-06-01',title:'QA completion deleted history'}),block=plan.blocks[0];
 await json(request,`/api/task-definitions/${task.id}?delete_assignments=true`,'delete');expect((await state(request)).task_definitions.some(t=>t.id===task.id)).toBe(false);
 const before=(await json(request,`/api/schedules?date=${plan.date}`))[0].blocks.find(b=>b.id===block.id);
 await page.goto('/');await planner(page,plan.date);await openBlock(page,block);await page.getByRole('button',{name:'Mark Session Completed',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
 let history=(await week(request,plan.date)).history_assignments.find(a=>a.task_definition_id===task.id);expect(history).toMatchObject({completed_minutes:60,completed_sessions:1,removed_from_week:true});
 await complete(request,plan,block,false);history=(await week(request,plan.date)).history_assignments.find(a=>a.task_definition_id===task.id);expect(history).toMatchObject({completed_minutes:0,completed_sessions:0,removed_from_week:true});
 const after=(await json(request,`/api/schedules?date=${plan.date}`))[0].blocks.find(b=>b.id===block.id);for(const field of ['start','end','task_id','location_id','task_assignment_id','logical_session_id'])expect(after[field]).toBe(before[field]);expect((await state(request)).task_definitions.some(t=>t.id===task.id)).toBe(false);expect((await week(request,plan.date)).assignments.some(a=>a.task_definition_id===task.id)).toBe(false);
});

test('completion details and workload controls remain accessible across four themes and mobile',async({page,request})=>{
 test.setTimeout(300000);const {plan}=await fixture(request,{date:'2020-05-04',title:'QA completion visual'});await complete(request,plan,plan.blocks[0]);const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('/');await planner(page,plan.date);
 for(const theme of ['light','dark','midnight','warm']){
  await page.setViewportSize({width:1440,height:1000});await page.getByLabel('Theme',{exact:true}).selectOption(theme);await expect(page.locator('html')).toHaveAttribute('data-theme',theme);await audit(page,`planner-desktop-${theme}`);
  const contrast=await page.locator('select option').evaluateAll(options=>options.filter(option=>!option.disabled).map(option=>{const style=getComputedStyle(option),rgb=value=>value.match(/[\d.]+/g).slice(0,3).map(Number),luminance=value=>rgb(value).map(channel=>{const c=channel/255;return c<=.04045?c/12.92:((c+.055)/1.055)**2.4}).reduce((sum,c,index)=>sum+c*[.2126,.7152,.0722][index],0),a=luminance(style.color),b=luminance(style.backgroundColor);return {text:option.textContent,ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)}}));
  expect(contrast.filter(option=>option.ratio<4.5)).toEqual([]);
  const workload=page.getByRole('combobox',{name:'Workload Level',exact:true});await workload.focus();await page.keyboard.press('Home');await expect(workload).toHaveValue('very_low');await expect(workload).toBeEnabled();await workload.focus();await page.keyboard.press('ArrowDown');await page.keyboard.press('Enter');await expect(workload).toHaveValue('low');await expect(workload).toBeEnabled();
  await workload.press('Alt+ArrowDown');await page.screenshot({path:`../test-results/${prefix}-screenshots/native-workload-${theme}.png`,animations:'disabled'});await page.keyboard.press('Escape');
  await openBlock(page,plan.blocks[0]);await audit(page,`completion-desktop-${theme}`);await page.getByRole('button',{name:'Close dialog',exact:true}).click();
  await page.setViewportSize({width:390,height:844});await audit(page,`planner-mobile-${theme}`);await openBlock(page,plan.blocks[0]);await audit(page,`completion-mobile-${theme}`);await page.getByRole('button',{name:'Close dialog',exact:true}).click();await nav(page,'Overview');await audit(page,`overview-mobile-${theme}`);await nav(page);
 }
 expect(errors).toEqual([]);
});
