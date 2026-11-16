import {test,expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs/promises';
import {taskForm,taskCard,weekTab,libraryTab,sundayOf} from '../task-helpers.js';

async function json(request,path,method='get',data){const response=await request[method](path,{data,...(path.includes('/schedules/generate')?{timeout:45000}:{})});expect(response.ok(),await response.text()).toBeTruthy();return response.status()===204?null:response.json()}
const state=request=>json(request,'/api/state');
const week=(request,date)=>json(request,`/api/task-week?week_start=${date}`);
async function nav(page){const toggle=page.getByRole('button',{name:'Open navigation',exact:true});if(await toggle.isVisible()&&!await page.locator('.sidebar').evaluate(e=>e.classList.contains('open')))await toggle.click();await page.locator('.nav-item').filter({hasText:'Tasks & deadlines'}).click()}
async function selectWeek(page,date){await page.getByLabel('Task week date',{exact:true}).fill(date);await expect(page.getByLabel('Task week date',{exact:true})).toHaveValue(sundayOf(date));await expect(page.locator('.task-week-loading')).toHaveCount(0)}
const everyTab=page=>page.locator('[aria-label="Task views"]').getByRole('button',{name:/^Every Week/}).click();
async function saved(page){await expect(page.getByRole('dialog')).toHaveCount(0)}
async function audit(page,name){await fs.mkdir('../test-results/recurrence-screenshots',{recursive:true});await expect(page.locator('.toast')).toHaveCount(0);await page.screenshot({path:`../test-results/recurrence-screenshots/${name}.png`,fullPage:true,animations:'disabled'});const result=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();await fs.writeFile(`../test-results/recurrence-screenshots/${name}.axe.json`,JSON.stringify(result.violations,null,2));expect(result.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}))).toEqual([]);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);if(await page.getByRole('dialog').count()){expect(await page.getByRole('dialog').evaluate(e=>e.scrollWidth<=e.clientWidth+1)).toBe(true);if(name.includes('mobile'))await page.screenshot({path:`../test-results/recurrence-screenshots/${name}-viewport.png`,animations:'disabled'})}}

test('every-week creation, isolated exceptions, skip, pause and archive preserve weekly history',async({page,request})=>{
 test.setTimeout(180000);await page.clock.setFixedTime(new Date('2037-04-15T16:00:00Z'));
 await page.goto('/');await nav(page);await expect(page.locator('[aria-label="Task views"]').getByRole('button',{name:/^Every Week/})).toHaveAttribute('aria-pressed','true');
 await page.getByRole('button',{name:'New every-week task',exact:true}).click();
 await taskForm(page,{title:'QA Recurrence daily research',minutes:45,type:'academic',minimum:3,importance:8.5,description:'A fresh weekly rhythm with separate progress.'});
 await expect(page.getByLabel(/^Selected week/)).toHaveCount(0);await expect(page.getByLabel(/^Due date/)).toHaveCount(0);await expect(page.getByLabel(/^Assessment date/)).toHaveCount(0);
 await page.getByRole('button',{name:'Save task',exact:true}).click();await saved(page);
 const task=(await state(request)).task_definitions.find(t=>t.title==='QA Recurrence daily research');expect(task.recurrence).toMatchObject({kind:'weekly',start_week:'2037-04-12'});
 await weekTab(page);await selectWeek(page,'2037-04-12');await expect(taskCard(page,task.title)).toHaveCount(0);await expect(page.locator('[aria-label="Task views"]').getByRole('button',{name:/^Week Specific/})).toContainText('0');await expect(page.locator('.task-week-summary')).toContainText('Every-week + week-specific work');
 const initial=(await week(request,'2037-04-12')).assignments.find(a=>a.task_definition_id===task.id);await json(request,'/api/task-sessions','post',{assignment_id:initial.id});await page.reload();await nav(page);await everyTab(page);
 await taskCard(page,task.title).getByRole('button',{name:'Adjust selected week',exact:true}).click();await page.getByLabel(/^Minimum sessions (this week|for selected week)/).fill('5');await page.getByLabel(/^Session length this week/).fill('60');await page.getByRole('dialog').locator('summary').click();await page.getByLabel(/^Due date this week/).fill('2037-04-17T17:00');await page.getByLabel('Importance this week',{exact:true}).fill('9.5');await page.getByRole('button',{name:'Save this week',exact:true}).click();await saved(page);
 let assignment=(await week(request,'2037-04-12')).assignments.find(a=>a.task_definition_id===task.id);expect(assignment).toMatchObject({min_sessions_per_week:5,session_minutes:60,completed_minutes:45});expect(assignment.overrides.importance).toBe(9.5);
 await weekTab(page);await selectWeek(page,'2037-04-19');await expect(taskCard(page,task.title)).toHaveCount(0);assignment=(await week(request,'2037-04-19')).assignments.find(a=>a.task_definition_id===task.id);expect(assignment.session_minutes).toBe(45);expect(assignment.overrides).toEqual({});await everyTab(page);
 await taskCard(page,task.title).getByRole('button',{name:'Adjust selected week',exact:true}).click();await page.getByRole('dialog').getByRole('combobox',{name:'Week status',exact:true}).selectOption('skipped');await page.getByRole('button',{name:'Save this week',exact:true}).click();await saved(page);expect((await week(request,'2037-04-19')).assignments.find(a=>a.task_definition_id===task.id).status).toBe('skipped');
 await weekTab(page);await selectWeek(page,'2037-04-26');await expect(taskCard(page,task.title)).toHaveCount(0);await everyTab(page);await taskCard(page,task.title).getByRole('button',{name:'Pause recurring task',exact:true}).click();await page.getByLabel('Filter tasks by status',{exact:true}).selectOption('all');await expect(taskCard(page,task.title)).toContainText('paused');
 let plan=await json(request,'/api/schedules/generate','post',{date:'2037-04-26'});expect(plan.blocks.filter(b=>b.task_id===task.id)).toEqual([]);
 await taskCard(page,task.title).getByRole('button',{name:'Resume recurring task',exact:true}).click();await expect(taskCard(page,task.title)).toContainText('active');await taskCard(page,task.title).getByRole('button',{name:'Archive recurring task',exact:true}).click();await expect(taskCard(page,task.title)).toContainText('archived');
 expect((await week(request,'2037-04-12')).assignments.find(a=>a.task_definition_id===task.id).completed_minutes).toBe(45);await page.reload();await nav(page);await page.getByLabel('Filter tasks by status',{exact:true}).selectOption('all');await expect(taskCard(page,task.title)).toContainText('archived');
});

test('copy from arbitrary weeks previews selection and preserves or shifts dates without progress',async({page,request})=>{
 test.setTimeout(180000);
 const source='2038-01-03',target='2038-03-07',shiftTarget='2038-03-14';
 const task=await json(request,'/api/task-definitions','post',{title:'QA Recurrence copy selected paper',task_type:'academic',academic_subtype:'assignment',session_minutes:137,min_sessions_per_week:2,importance:8.5,difficulty:7.5,due_at:'2038-01-08T17:00:00-05:00'});
 const other=await json(request,'/api/task-definitions','post',{title:'QA Recurrence copy leave behind',session_minutes:30});
 const recurring=await json(request,'/api/task-definitions','post',{title:'QA Recurrence copy automatic rhythm',recurrence:{start_week:source},session_minutes:30});
 for(const definition of [task,other])await json(request,'/api/task-weeks','post',{task_definition_id:definition.id,week_start:source,min_sessions_per_week:2});
 const original=(await week(request,source)).assignments.find(a=>a.task_definition_id===task.id);await json(request,'/api/task-sessions','post',{assignment_id:original.id});
 await page.goto('/');await nav(page);await weekTab(page);await selectWeek(page,target);await page.getByRole('button',{name:'Copy from another week',exact:true}).click();await page.getByLabel(/^Copy from week/).fill(source);await expect(page.getByRole('dialog').locator('.task-copy-row')).toHaveCount(2);await expect(page.getByRole('dialog').getByText(recurring.title,{exact:true})).toHaveCount(0);
 await page.getByRole('dialog').getByLabel(new RegExp(other.title)).uncheck();await page.getByRole('button',{name:'Preview copy',exact:true}).click();await expect(page.getByRole('dialog').getByRole('status')).toContainText('1 will be added');expect((await week(request,target)).assignments.some(a=>a.task_definition_id===task.id)).toBe(false);
 await page.getByRole('button',{name:'Copy selected tasks',exact:true}).click();await expect(page.getByRole('dialog').getByRole('status')).toContainText('Copy complete');await page.getByRole('button',{name:'Done',exact:true}).click();await saved(page);
 const copied=(await week(request,target)).assignments.find(a=>a.task_definition_id===task.id);expect(copied.completed_minutes).toBe(0);expect(copied.sessions).toEqual([]);expect(copied.effective_definition.due_at).toBe(task.due_at);expect((await week(request,target)).assignments.some(a=>a.task_definition_id===other.id)).toBe(false);
 await page.getByRole('button',{name:'Copy from another week',exact:true}).click();await page.getByLabel(/^Copy from week/).fill(source);await expect(page.getByRole('dialog').locator('.task-copy-row')).toHaveCount(2);await page.getByRole('dialog').getByLabel(new RegExp(other.title)).uncheck();await page.getByRole('button',{name:'Preview copy',exact:true}).click();await expect(page.getByRole('dialog').getByRole('status')).toContainText('0 will be added');await expect(page.getByRole('dialog').getByRole('status')).toContainText('already assigned');await page.getByRole('button',{name:'Cancel',exact:true}).click();
 await page.getByRole('button',{name:'Copy from another week',exact:true}).click();await page.getByLabel(/^Copy from week/).fill(source);await page.getByLabel(/^Copy to week/).fill(shiftTarget);await expect(page.getByRole('dialog').locator('.task-copy-row')).toHaveCount(2);await page.getByRole('dialog').getByLabel(new RegExp(other.title)).uncheck();await page.getByRole('radio',{name:/Shift dates by the week difference/}).check();await page.getByRole('button',{name:'Preview copy',exact:true}).click();await page.getByRole('button',{name:'Copy selected tasks',exact:true}).click();await expect(page.getByRole('dialog').getByRole('status')).toContainText('Copy complete');await page.getByRole('button',{name:'Done',exact:true}).click();
 const shifted=(await week(request,shiftTarget)).assignments.find(a=>a.task_definition_id===task.id);expect(shifted.effective_definition.due_at).toBe('2038-03-19T17:00:00-04:00');expect(shifted.completed_minutes).toBe(0);expect((await week(request,source)).assignments.find(a=>a.task_definition_id===task.id).completed_minutes).toBe(137);
});

test('library conversion preserves task identity, project links and existing progress',async({page,request})=>{
 await page.clock.setFixedTime(new Date('2040-02-15T16:00:00Z'));
 const project=await json(request,'/api/projects','post',{name:'QA Recurrence conversion project',status:'active'});
 const task=await json(request,'/api/task-definitions','post',{title:'QA Recurrence convert saved definition',project_id:project.id,session_minutes:60,min_sessions_per_week:2,deadline_at:'2040-02-17T17:00:00-05:00'});
 const assignment=await json(request,'/api/task-weeks','post',{task_definition_id:task.id,week_start:'2040-02-12',min_sessions_per_week:2});await json(request,'/api/task-sessions','post',{assignment_id:assignment.id});
 await page.goto('/');await nav(page);await libraryTab(page);await taskCard(page,task.title).getByRole('button',{name:'Make recurring every week',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('Absolute due dates');await page.getByRole('dialog').getByRole('button',{name:'Make recurring',exact:true}).click();await saved(page);
 const converted=(await state(request)).task_definitions.find(item=>item.id===task.id);expect(converted.project_id).toBe(project.id);expect(converted.recurrence.start_week).toBe('2040-02-12');expect(converted.deadline_at).toBeNull();expect((await week(request,'2040-02-12')).assignments.find(item=>item.task_definition_id===task.id).completed_minutes).toBe(60);expect((await week(request,'2040-02-19')).assignments.find(item=>item.task_definition_id===task.id).completed_minutes).toBe(0);await expect(taskCard(page,task.title)).toContainText('2 sessions each week');
});

test('recurrence, exception and copy views remain accessible in all themes and mobile layouts',async({page,request})=>{
 test.setTimeout(300000);await page.clock.setFixedTime(new Date('2039-05-11T16:00:00Z'));const date='2039-05-08';
 const recurring=await json(request,'/api/task-definitions','post',{title:'QA Recurrence Theme extended research title',task_type:'academic',academic_subtype:'studying',recurrence:{start_week:date},session_minutes:137,min_sessions_per_week:3,importance:8.5,difficulty:7.5,description:'A recurring study rhythm with project context, a soft target, and weekly exceptions.'});
 const copy=await json(request,'/api/task-definitions','post',{title:'QA Recurrence Theme paper',task_type:'academic',academic_subtype:'assignment',session_minutes:60});await json(request,'/api/task-weeks','post',{task_definition_id:copy.id,week_start:'2039-05-01'});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('/');await nav(page);
 for(const theme of ['light','dark','midnight','warm']){
  await page.setViewportSize({width:1440,height:1000});await page.getByLabel('Theme',{exact:true}).selectOption(theme);await everyTab(page);await audit(page,`recurring-desktop-${theme}`);await taskCard(page,recurring.title).getByRole('button',{name:`Edit ${recurring.title}`,exact:true}).click();await audit(page,`recurring-editor-desktop-${theme}`);await page.getByRole('button',{name:'Close dialog',exact:true}).click();
  await page.setViewportSize({width:390,height:844});await audit(page,`recurring-mobile-${theme}`);await weekTab(page);await selectWeek(page,date);await audit(page,`effective-week-mobile-${theme}`);await everyTab(page);await taskCard(page,recurring.title).getByRole('button',{name:'Adjust selected week',exact:true}).click();await page.getByRole('dialog').locator('summary').click();await audit(page,`exception-mobile-${theme}`);await page.getByRole('button',{name:'Close dialog',exact:true}).click();await weekTab(page);await page.getByRole('button',{name:'Copy from another week',exact:true}).click();await expect(page.getByRole('dialog').locator('.task-copy-row')).toHaveCount(1);await audit(page,`copy-mobile-${theme}`);await page.getByRole('button',{name:'Preview copy',exact:true}).click();await audit(page,`copy-preview-mobile-${theme}`);await page.getByRole('button',{name:'Cancel',exact:true}).click();await libraryTab(page);await audit(page,`library-mobile-${theme}`);
 }
 await page.setViewportSize({width:768,height:1024});await weekTab(page);await audit(page,'effective-week-tablet-warm');expect(errors).toEqual([]);
});


 test('management tabs separate inherited work while summaries and scheduling combine it',async({page,request})=>{
 await page.clock.setFixedTime(new Date('2030-11-16T12:00:00Z'));
 const rhythm=await json(request,'/api/task-definitions','post',{title:'QA Separation weekly rhythm',recurrence:{start_week:'2030-11-10'},session_minutes:30,min_sessions_per_week:1,importance:10});
 const explicit=await json(request,'/api/task-definitions','post',{title:'QA Separation explicit work',session_minutes:30,min_sessions_per_week:1,importance:10});
 await json(request,'/api/task-weeks','post',{task_definition_id:explicit.id,week_start:'2030-11-10'});
 await page.goto('/');await nav(page);await weekTab(page);await selectWeek(page,'2030-11-10');
 await expect(taskCard(page,rhythm.title)).toHaveCount(0);await expect(taskCard(page,explicit.title)).toHaveCount(1);
 await expect(page.locator('[aria-label="Task views"]').getByRole('button',{name:/^Week Specific/})).toContainText('1');
 await expect(page.locator('.task-week-stat').first()).toContainText('2');await expect(page.getByText('Weekly summaries above include Every Week and Week Specific tasks.',{exact:false})).toBeVisible();
 await page.getByLabel('Search tasks',{exact:true}).fill(rhythm.title);await expect(page.locator('.intelligent-task-card')).toHaveCount(0);await expect(page.getByText('No tasks match these filters',{exact:true})).toBeVisible();await page.getByLabel('Search tasks',{exact:true}).fill('');
 await page.getByRole('button',{name:'Assign existing task',exact:true}).first().click();await expect(page.getByRole('dialog').getByText(rhythm.title,{exact:true})).toHaveCount(0);await page.getByRole('dialog').getByRole('button',{name:'Close dialog',exact:true}).click();
 await everyTab(page);await expect(taskCard(page,rhythm.title)).toHaveCount(1);await expect(taskCard(page,explicit.title)).toHaveCount(0);await libraryTab(page);await expect(taskCard(page,rhythm.title)).toHaveCount(1);await expect(taskCard(page,explicit.title)).toHaveCount(1);
 const effective=await week(request,'2030-11-10');expect(effective.assignments.map(a=>a.task_definition_id).sort()).toEqual([rhythm.id,explicit.id].sort());
 const plan=await json(request,'/api/schedules/generate','post',{date:'2030-11-16'});const ids=plan.blocks.filter(b=>b.kind==='task').map(b=>b.task_definition_id);expect(ids).toContain(rhythm.id);expect(ids).toContain(explicit.id);
 });
