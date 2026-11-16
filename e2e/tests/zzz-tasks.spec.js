import {test,expect} from '@playwright/test';
import {choosePersistedTheme} from '../theme-helpers.js';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs/promises';
import {taskForm,taskCard,weekTab,libraryTab,sundayOf,addDays,completePlannedSessions} from '../task-helpers.js';

async function json(request,path,method='get',data){const r=await request[method](path,{data,...(path.includes('/schedules/generate')?{timeout:45000}:{})});expect(r.ok(),await r.text()).toBeTruthy();return r.status()===204?null:r.json()}
const state=request=>json(request,'/api/state');
const week=(request,date)=>json(request,`/api/task-week?week_start=${date}`);
async function nav(page,text){const toggle=page.getByRole('button',{name:'Open navigation',exact:true});if(await toggle.isVisible()&&!await page.locator('.sidebar').evaluate(e=>e.classList.contains('open')))await toggle.click();await page.locator('.nav-item').filter({hasText:text}).first().click()}
async function saved(page){await expect(page.getByRole('dialog')).toHaveCount(0)}
async function selectWeek(page,date){await page.getByLabel('Task week date',{exact:true}).fill(date);await expect(page.getByLabel('Task week date',{exact:true})).toHaveValue(sundayOf(date));await expect(page.locator('.task-week-loading')).toHaveCount(0)}
async function assignmentFor(request,date,id){return (await week(request,date)).assignments.find(a=>a.task_definition_id===id)}
async function newAssignment(page,title,count){await page.getByRole('button',{name:'Assign existing task',exact:true}).first().click();await page.getByRole('dialog').getByLabel('Search existing tasks',{exact:true}).fill(title);await page.locator('.task-add-existing-row').filter({hasText:title}).getByRole('button',{name:'Choose task',exact:true}).click();await page.getByRole('dialog').getByLabel(/^Minimum sessions (this week|for selected week)/).fill(String(count));await page.getByRole('button',{name:'Assign to week',exact:true}).click();await saved(page)}
async function captureAudit(page,name){
 await fs.mkdir('../test-results/task-screenshots',{recursive:true});
 await page.screenshot({path:`../test-results/task-screenshots/${name}.png`,fullPage:true,animations:'disabled'});
 const result=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
 await fs.writeFile(`../test-results/task-screenshots/${name}.axe.json`,JSON.stringify(result.violations,null,2));
 expect(result.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}))).toEqual([]);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 const dialog=page.getByRole('dialog');if(await dialog.count()){expect(await dialog.evaluate(e=>e.scrollWidth<=e.clientWidth+1)).toBe(true);if(name.includes('mobile'))await page.screenshot({path:`../test-results/task-screenshots/${name}-viewport.png`,animations:'disabled'})}
}

test('reusable tasks, arbitrary year navigation, independent weekly targets and honest completion',async({page,request})=>{
 test.setTimeout(180000);
 await page.clock.setFixedTime(new Date('2004-12-30T16:00:00Z'));
 const settings=(await state(request)).settings;await json(request,'/api/settings','put',{...settings,meals:[],default_location_id:null});
 await page.goto('/');await nav(page,'Tasks & deadlines');await weekTab(page);await selectWeek(page,'2004-12-31');
 await expect(page.locator('.task-week-title')).toContainText('Dec 26');
 await page.getByRole('button',{name:'Next task week',exact:true}).click();await expect(page.getByLabel('Task week date',{exact:true})).toHaveValue('2005-01-02');
 await page.getByRole('button',{name:'Previous task week',exact:true}).click();await expect(page.getByLabel('Task week date',{exact:true})).toHaveValue('2004-12-26');
 await selectWeek(page,'2045-07-18');await expect(page.getByLabel('Task week date',{exact:true})).toHaveValue(sundayOf('2045-07-18'));
 await page.locator('.task-week-controls').getByRole('button',{name:'This week',exact:true}).click();await expect(page.getByLabel('Task week date',{exact:true})).toHaveValue('2004-12-26');
 await libraryTab(page);await page.getByRole('button',{name:'New reusable task',exact:true}).click();
 await taskForm(page,{title:'QA Weekly calculus research',minutes:137,type:'academic',minimum:0,description:'A reusable definition with independent academic dates.'});
 await expect(page.getByLabel('Assign to a selected week',{exact:true})).toHaveCount(0);await expect(page.getByLabel(/^Selected week/)).toHaveCount(0);
 const minutes=page.getByRole('dialog').getByLabel(/^Session length \(minutes\)/);await expect(minutes).not.toHaveAttribute('max',/.+/);for(const invalid of ['0','1.5']){await minutes.fill(invalid);await page.getByRole('button',{name:'Save task',exact:true}).click();await expect(page.getByRole('dialog')).toBeVisible();expect(await minutes.evaluate(e=>e.checkValidity())).toBe(false)}await minutes.fill('137');
 await page.getByRole('combobox',{name:'Academic subtype',exact:true}).selectOption('assessment_preparation');
 await page.getByLabel(/^Due date \(/).fill('2005-01-06T17:00');await page.getByLabel(/^Assessment date \(/).fill('2005-01-07T09:00');await expect(page.getByLabel('Course (optional)',{exact:true})).toHaveCount(0);
 const importance=page.getByRole('slider',{name:'Importance',exact:true}),difficulty=page.getByRole('slider',{name:'Difficulty',exact:true});await importance.press('Home');await importance.press('ArrowRight');await expect(importance).toHaveValue('1.5');await difficulty.press('Home');await difficulty.press('ArrowRight');await expect(difficulty).toHaveValue('0.5');
 await page.getByRole('button',{name:'Save task',exact:true}).click();await saved(page);
 let definition=(await state(request)).task_definitions.find(t=>t.title==='QA Weekly calculus research');expect(definition).toMatchObject({session_minutes:137,min_sessions_per_week:0,importance:1.5,difficulty:0.5,academic_subtype:'assessment_preparation',course:''});expect(Date.parse(definition.due_at)).toBe(Date.parse('2005-01-06T17:00:00-05:00'));expect(Date.parse(definition.assessment_at)).toBe(Date.parse('2005-01-07T09:00:00-05:00'));
 expect((await week(request,'2004-12-26')).assignments.some(a=>a.task_definition_id===definition.id)).toBe(false);
 const empty=await json(request,'/api/schedules/generate','post',{date:'2004-12-26'});expect(empty.blocks.filter(b=>b.task_id===definition.id)).toEqual([]);
 await weekTab(page);await selectWeek(page,'2005-01-03');await newAssignment(page,definition.title,2);
 let assignment=await assignmentFor(request,'2005-01-02',definition.id);expect(assignment).toMatchObject({min_sessions_per_week:2,completed_sessions:0,scheduled_sessions:0,session_minutes:137});expect((await week(request,'2005-01-02')).sessions.filter(s=>s.assignment_id===assignment.id)).toHaveLength(0);
 // Keep the browser clock after these real past blocks; the server clock is untouched.
 await page.clock.setFixedTime(new Date('2005-01-08T16:00:00Z'));
 await completePlannedSessions(page,request,'2005-01-02',definition.id);await completePlannedSessions(page,request,'2005-01-03',definition.id);expect((await assignmentFor(request,'2005-01-02',definition.id)).completed_sessions).toBe(2);
 await page.getByRole('combobox',{name:'Filter tasks by status',exact:true}).selectOption('all');await selectWeek(page,'2005-01-04');await expect(taskCard(page,definition.title)).toBeVisible();await taskCard(page,definition.title).getByRole('button',{name:'Adjust this week',exact:true}).click();await page.getByRole('dialog').getByLabel(/^Minimum sessions (this week|for selected week)/).fill('1');await page.getByRole('button',{name:'Save this week',exact:true}).click();await saved(page);
 assignment=await assignmentFor(request,'2005-01-02',definition.id);expect(assignment.min_sessions_per_week).toBe(1);expect(assignment.completed_sessions).toBe(2);expect(assignment.completed_minutes).toBe(274);expect((await week(request,'2005-01-02')).sessions.filter(s=>s.assignment_id===assignment.id)).toHaveLength(2);
 await page.getByRole('button',{name:'Next task week',exact:true}).click();await expect(page.getByLabel('Task week date',{exact:true})).toHaveValue('2005-01-09');await newAssignment(page,definition.title,3);let later=await assignmentFor(request,'2005-01-09',definition.id);expect(later.completed_sessions).toBe(0);expect(later.completed_minutes).toBe(0);
 await taskCard(page,definition.title).getByRole('button',{name:'Adjust this week',exact:true}).click();await page.getByRole('combobox',{name:'Week status',exact:true}).selectOption('completed');await page.getByRole('button',{name:'Save this week',exact:true}).click();await saved(page);later=await assignmentFor(request,'2005-01-09',definition.id);expect(later.status).toBe('completed');expect(later.completed_sessions).toBe(0);expect((await week(request,'2005-01-09')).sessions.filter(s=>s.assignment_id===later.id)).toHaveLength(0);
 await libraryTab(page);await taskCard(page,definition.title).getByRole('button',{name:`Edit ${definition.title}`,exact:true}).click();await page.getByLabel(/^Session length \(minutes\)/).fill('10000');await page.getByRole('button',{name:'Save task',exact:true}).click();await saved(page);
 definition=(await state(request)).task_definitions.find(t=>t.id===definition.id);expect(definition.session_minutes).toBe(10000);expect((await assignmentFor(request,'2005-01-02',definition.id)).session_minutes).toBe(137);expect((await assignmentFor(request,'2005-01-02',definition.id)).completed_minutes).toBe(274);
 await page.reload();await nav(page,'Tasks & deadlines');await weekTab(page);await selectWeek(page,'2005-01-02');await page.getByRole('combobox',{name:'Filter tasks by status',exact:true}).selectOption('all');await expect(taskCard(page,definition.title)).toContainText('minimum sessions allocated');
 await selectWeek(page,'2004-12-26');expect((await week(request,'2004-12-26')).assignments.some(a=>a.task_definition_id===definition.id)).toBe(false);
 await json(request,'/api/settings','put',settings);
});

test('daily planner preserves one logical session across chunks and reverses completion exactly once',async({page,request})=>{
 test.setTimeout(180000);
 const original=(await state(request)).settings;const settings={...original,wake_time:'07:00',sleep_time:'23:00',work_start:'08:00',work_end:'08:20',focus_minutes:60,break_minutes:0,travel_buffer_minutes:0,default_location_id:null,meals:[]};await json(request,'/api/settings','put',settings);
 const first='2006-01-01',second='2006-01-02';
 const definition=await json(request,'/api/task-definitions','post',{title:'QA Weekly split proof',task_type:'academic',academic_subtype:'assessment_preparation',session_minutes:60,min_sessions_per_week:1,importance:1,difficulty:0,allow_splitting:true,min_chunk_minutes:20,due_at:`${second}T08:40:00-05:00`,assessment_at:'2006-01-03T09:00:00-05:00'});
 const assignment=await json(request,'/api/task-weeks','post',{task_definition_id:definition.id,week_start:first,min_sessions_per_week:1});
 let firstPlan=await json(request,'/api/schedules/generate','post',{date:first});let firstBlocks=firstPlan.blocks.filter(b=>b.task_id===definition.id);expect(firstBlocks).toHaveLength(1);expect((Date.parse(firstBlocks[0].end)-Date.parse(firstBlocks[0].start))/60000).toBe(20);const sid=firstBlocks[0].logical_session_id;expect(sid).toBeTruthy();
 await json(request,'/api/settings','put',{...settings,work_end:'08:40'});const secondPlan=await json(request,'/api/schedules/generate','post',{date:second});const secondBlocks=secondPlan.blocks.filter(b=>b.task_id===definition.id);expect(secondBlocks).toHaveLength(1);expect(secondBlocks[0].logical_session_id).toBe(sid);expect((Date.parse(secondBlocks[0].end)-Date.parse(secondBlocks[0].start))/60000).toBe(40);expect(Date.parse(secondBlocks[0].end)).toBeLessThanOrEqual(Date.parse(`${second}T08:40:00-05:00`));
 let progress=await assignmentFor(request,first,definition.id);expect(progress.scheduled_sessions).toBe(1);expect(progress.completed_sessions).toBe(0);expect(progress.planned_minutes).toBe(60);
 await page.goto('/');
 async function plannerStatus(date,status){await nav(page,'Overview');await page.getByLabel('Planning date',{exact:true}).fill(date);await nav(page,'Daily planner');await page.locator('.timeline-block').filter({hasText:definition.title}).click();const plan=(await state(request)).schedules.find(s=>s.date===date),block=plan.blocks.find(b=>b.task_id===definition.id);if(block.status===status){await json(request,`/api/schedules/${plan.id}/blocks/${block.id}/completion`,'post',{completed:status==='completed'});await page.getByRole('button',{name:'Cancel',exact:true}).click()}else await page.getByRole('button',{name:status==='completed'?'Mark Session Completed':'Undo Completion',exact:true}).click();await saved(page)}
 await plannerStatus(first,'completed');progress=await assignmentFor(request,first,definition.id);expect(progress.completed_minutes).toBe(20);expect(progress.completed_sessions).toBe(0);expect(progress.scheduled_sessions).toBe(1);
 await plannerStatus(second,'completed');progress=await assignmentFor(request,first,definition.id);expect(progress.completed_minutes).toBe(60);expect(progress.completed_sessions).toBe(1);expect(progress.planned_minutes).toBe(0);
 await plannerStatus(second,'completed');expect((await assignmentFor(request,first,definition.id)).completed_minutes).toBe(60);
 await plannerStatus(first,'todo');progress=await assignmentFor(request,first,definition.id);expect(progress.completed_minutes).toBe(40);expect(progress.completed_sessions).toBe(0);expect(progress.planned_minutes).toBe(20);
 await plannerStatus(first,'completed');expect((await assignmentFor(request,first,definition.id)).completed_sessions).toBe(1);
 await nav(page,'Tasks & deadlines');await weekTab(page);await selectWeek(page,first);await page.getByRole('combobox',{name:'Filter tasks by status',exact:true}).selectOption('all');await taskCard(page,definition.title).getByRole('button',{name:'Adjust this week',exact:true}).click();await page.getByRole('dialog').getByLabel(/^Minimum sessions (this week|for selected week)/).fill('0');await page.getByRole('button',{name:'Save this week',exact:true}).click();await saved(page);progress=await assignmentFor(request,first,definition.id);expect(progress.min_sessions_per_week).toBe(0);expect(progress.completed_sessions).toBe(1);expect((await week(request,first)).sessions.filter(s=>s.id===sid)).toHaveLength(1);
 const impossible=await json(request,'/api/task-definitions','post',{title:'QA Weekly last-day shortfall',session_minutes:10000,min_sessions_per_week:2,importance:1,difficulty:0});await json(request,'/api/task-weeks','post',{task_definition_id:impossible.id,week_start:'2006-01-08',min_sessions_per_week:2});const last=await json(request,'/api/schedules/generate','post',{date:'2006-01-14'});expect(last.blocks.filter(b=>b.task_id===impossible.id)).toEqual([]);expect(last.weekly_progress.find(p=>p.task_definition_id===impossible.id).expected_shortfall).toBe(2);expect((await week(request,'2006-01-08')).sessions.filter(s=>s.task_definition_id===impossible.id)).toHaveLength(0);
 const zero=await json(request,'/api/task-definitions','post',{title:'QA Weekly no filler',session_minutes:1,min_sessions_per_week:0,importance:1,difficulty:0});await json(request,'/api/task-weeks','post',{task_definition_id:zero.id,week_start:'2006-01-15',min_sessions_per_week:0});const zeroPlan=await json(request,'/api/schedules/generate','post',{date:'2006-01-15'});expect(zeroPlan.blocks.filter(b=>b.task_id===zero.id)).toEqual([]);expect((await week(request,'2006-01-15')).sessions.filter(s=>s.task_definition_id===zero.id)).toHaveLength(0);
 await json(request,'/api/settings','put',original);
});

test('weekly task library, editor, assignments and progress stay accessible across themes and viewports',async({page,request},testInfo)=>{
 test.setTimeout(300000);await page.clock.setFixedTime(new Date('2035-03-14T16:00:00Z'));const start=sundayOf('2035-03-14');
 const definition=await json(request,'/api/task-definitions','post',{title:'QA Task Theme study calculus',task_type:'academic',academic_subtype:'studying',session_minutes:137,min_sessions_per_week:3,importance:8.5,difficulty:7.5,description:'Reusable academic context, independent dates, and weekly session progress.\nBreak a logical session into chunks only when needed.',due_at:'2035-03-17T17:00:00-04:00',assessment_at:'2035-03-18T09:00:00-04:00',course:'MATH 137',allow_splitting:true,min_chunk_minutes:20});await json(request,'/api/task-weeks','post',{task_definition_id:definition.id,week_start:start,min_sessions_per_week:3});
 const other=await json(request,'/api/task-definitions','post',{title:'QA Task Theme project research',task_type:'project_work',session_minutes:60,min_sessions_per_week:0,importance:5.5,difficulty:4.5,description:'An optional reusable project work definition.'});await json(request,'/api/task-weeks','post',{task_definition_id:other.id,week_start:start,min_sessions_per_week:0});
 const settings=(await state(request)).settings;await json(request,'/api/settings','put',{...settings,theme:'warm'});await page.addInitScript(()=>localStorage.setItem('daycraft-theme','warm'));
 const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('/');await nav(page,'Tasks & deadlines');await weekTab(page);await selectWeek(page,start);await expect(taskCard(page,definition.title)).toBeVisible();
 for(const theme of ['light','dark','midnight','warm']){
  await page.setViewportSize({width:1440,height:1000});await choosePersistedTheme(page,request,theme,testInfo);await weekTab(page);await captureAudit(page,`task-week-desktop-${theme}`);
  await taskCard(page,definition.title).getByRole('button',{name:`Edit ${definition.title}`,exact:true}).click();await captureAudit(page,`task-editor-desktop-${theme}`);await page.getByRole('button',{name:'Close dialog',exact:true}).click();await libraryTab(page);await captureAudit(page,`task-library-desktop-${theme}`);
  await page.setViewportSize({width:390,height:844});await weekTab(page);await captureAudit(page,`task-week-mobile-${theme}`);
  await taskCard(page,definition.title).getByRole('button',{name:`Edit ${definition.title}`,exact:true}).click();await captureAudit(page,`task-editor-mobile-${theme}`);await page.getByRole('dialog').locator('summary').filter({hasText:'Advanced options'}).click();await page.getByLabel(/^Earliest start/).scrollIntoViewIfNeeded();await captureAudit(page,`task-editor-advanced-mobile-${theme}`);await page.getByRole('button',{name:'Close dialog',exact:true}).click();
  await page.getByRole('button',{name:'Assign existing task',exact:true}).click();await captureAudit(page,`task-assign-mobile-${theme}`);await page.getByRole('button',{name:'Close dialog',exact:true}).click();
 }
 await page.setViewportSize({width:768,height:1024});await captureAudit(page,'task-week-tablet-warm');await taskCard(page,definition.title).getByRole('button',{name:'Adjust this week',exact:true}).click();await captureAudit(page,'task-target-tablet-warm');await page.getByRole('button',{name:'Cancel',exact:true}).click();expect(errors).toEqual([]);
});



 test('week creation inherits page week and library edits never create or move an assignment',async({page,request})=>{
 await page.clock.setFixedTime(new Date('2031-02-10T16:00:00Z'));await page.goto('/');await nav(page,'Tasks & deadlines');await weekTab(page);await selectWeek(page,'2031-02-12');
 await page.getByRole('button',{name:'New task for this week',exact:true}).click();const dialog=page.getByRole('dialog');await expect(dialog.getByRole('heading',{name:'Weekly intention',exact:true})).toHaveCount(0);await expect(dialog.getByLabel('Assign to a selected week',{exact:true})).toHaveCount(0);await expect(dialog.getByLabel(/^Selected week/)).toHaveCount(0);
 await taskForm(page,{title:'QA Implicit selected-week task',minutes:45,minimum:4});await page.getByRole('button',{name:'Save task',exact:true}).click();await saved(page);
 const definition=(await state(request)).task_definitions.find(t=>t.title==='QA Implicit selected-week task');const original=await assignmentFor(request,'2031-02-09',definition.id);expect(original).toMatchObject({min_sessions_per_week:4,session_minutes:45,week_start:'2031-02-09'});
 await selectWeek(page,'2031-02-16');await libraryTab(page);await taskCard(page,definition.title).getByRole('button',{name:`Edit ${definition.title}`,exact:true}).click();await expect(page.getByRole('dialog').getByLabel(/^Selected week/)).toHaveCount(0);await page.getByRole('dialog').getByLabel('Task name',{exact:true}).fill('QA Implicit edited reusable task');await page.getByRole('button',{name:'Save task',exact:true}).click();await saved(page);
 const retained=await assignmentFor(request,'2031-02-09',definition.id);expect(retained.id).toBe(original.id);expect(retained.min_sessions_per_week).toBe(4);expect(await assignmentFor(request,'2031-02-16',definition.id)).toBeUndefined();await page.reload();expect((await assignmentFor(request,'2031-02-09',definition.id)).id).toBe(original.id);
 });
