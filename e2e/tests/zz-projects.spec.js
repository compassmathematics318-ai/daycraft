import {test,expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs/promises';
import {taskForm as fillWeeklyTask,taskCard,weekTab,libraryTab,sundayOf,chooseRelated} from '../task-helpers.js';
import {choosePersistedTheme} from '../theme-helpers.js';

async function json(request,path,method='get',data){const r=await request[method](path,{data,...(path.includes('/schedules/generate')?{timeout:45000}:{})});expect(r.ok(),await r.text()).toBeTruthy();return r.status()===204?null:r.json()}
const state=request=>json(request,'/api/state');
async function nav(page,text){const toggle=page.getByRole('button',{name:'Open navigation',exact:true});if(await toggle.isVisible()&&!await page.locator('.sidebar').evaluate(e=>e.classList.contains('open')))await toggle.click();await page.locator('.nav-item').filter({hasText:text}).first().click()}
const card=(page,name)=>page.locator('.project-card').filter({has:page.getByRole('button',{name,exact:true})});
async function expectNoProjectTracker(scope){await expect(scope.locator('.project-progress')).toHaveCount(0);await expect(scope.getByRole('progressbar')).toHaveCount(0);await expect(scope).not.toContainText(/minimum weekly sessions allocated|No session target for this week|weekly scheduling target; tasks stay open/)}
async function saved(page){await expect(page.getByRole('dialog')).toHaveCount(0)}
async function projectNamed(request,name){return (await state(request)).projects.find(p=>p.name===name)}
async function taskNamed(request,title){return (await state(request)).tasks.find(t=>t.title===title)}
async function closeDialog(page){await page.getByRole('button',{name:'Close dialog',exact:true}).click();await saved(page)}
async function taskForm(page,title,minutes,projectId){await fillWeeklyTask(page,{title,minutes,projectId,week:'2032-06-01'});await expect(page.getByRole('dialog').getByText(/^Work for .*2032\./)).toBeVisible()}
async function captureAudit(page,name){
 await fs.mkdir('../test-results/project-screenshots',{recursive:true});
 await page.screenshot({path:`../test-results/project-screenshots/${name}.png`,fullPage:true,animations:'disabled'});
 const result=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
 await fs.writeFile(`../test-results/project-screenshots/${name}.axe.json`,JSON.stringify(result.violations,null,2));
 expect(result.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}))).toEqual([]);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 const dialog=page.getByRole('dialog');
 if(await dialog.count()&&name.includes('mobile'))await page.screenshot({path:`../test-results/project-screenshots/${name}-viewport.png`,fullPage:false,animations:'disabled'});
 if(await dialog.count())expect(await dialog.evaluate(e=>e.scrollWidth<=e.clientWidth+1)).toBe(true);
}

test('contextual project CRUD, precise ratings, task links, task-level progress, eligibility and safe deletion',async({page,request})=>{
 test.setTimeout(240000);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/');await nav(page,'Personal projects');
 const beforeTasks=(await state(request)).tasks.length;
 await page.getByRole('button',{name:'New project',exact:true}).first().click();
 const dialog=page.getByRole('dialog');
 await expect(dialog.getByRole('heading',{name:'New project',exact:true})).toBeVisible();
 for(const label of ['Estimated minutes','Remaining minutes','Minimum session (min)','Maximum session (min)','Split into focused sessions','Preferred start','Preferred end'])await expect(dialog.getByLabel(label,{exact:true})).toHaveCount(0);
 await dialog.getByLabel('Project name (required)',{exact:true}).fill('   ');
 await dialog.getByRole('button',{name:'Save project',exact:true}).click();
 await expect(dialog.getByRole('alert')).toContainText('Enter a project name');
 await dialog.getByLabel('Project name (required)',{exact:true}).fill('QA Redesign Vector');
 await dialog.getByRole('combobox',{name:'Project category',exact:true}).selectOption('software');
 await dialog.getByRole('combobox',{name:'Project status',exact:true}).selectOption('planning');
 await dialog.getByLabel(/^Affiliations/).fill('Waterloo Reality Labs\nUniversity of Waterloo');
 const importance=dialog.getByRole('slider',{name:'Importance',exact:true}),difficulty=dialog.getByRole('slider',{name:'Difficulty',exact:true});
 await expect(importance).toHaveAttribute('min','1');await expect(importance).toHaveAttribute('max','10');await expect(importance).toHaveAttribute('step','0.5');
 await importance.focus();await importance.press('Home');await expect(importance).toHaveValue('1');await importance.press('ArrowLeft');await expect(importance).toHaveValue('1');await importance.press('End');await expect(importance).toHaveValue('10');await importance.press('ArrowRight');await expect(importance).toHaveValue('10');
 for(let n=0;n<3;n++)await importance.press('ArrowLeft');await expect(importance).toHaveValue('8.5');
 await expect(dialog.locator('.project-rating').filter({has:page.getByRole('slider',{name:'Importance',exact:true})}).locator('output')).toContainText('8.5');
 await expect(difficulty).toHaveAttribute('min','0');await expect(difficulty).toHaveAttribute('step','0.5');await difficulty.focus();await difficulty.press('Home');await expect(difficulty).toHaveValue('0');await difficulty.press('ArrowRight');await expect(difficulty).toHaveValue('0.5');await difficulty.press('End');await expect(difficulty).toHaveValue('10');for(let n=0;n<5;n++)await difficulty.press('ArrowLeft');await expect(difficulty).toHaveValue('7.5');
 await dialog.getByLabel(/^Description/).fill('Semantic processing, context evaluation, and visualization.\nResponsibilities: architecture and implementation.');
 await dialog.locator('summary').filter({hasText:'Dates, contributors, goals & links'}).click();
 await dialog.getByLabel(/^Start date/).fill('2030-01-01');await dialog.getByLabel(/^End date/).fill('2029-12-31');
 await dialog.getByRole('button',{name:'Save project',exact:true}).click();await expect(dialog).toBeVisible();expect(await dialog.getByLabel(/^End date/).evaluate(e=>e.validity.rangeUnderflow)).toBe(true);
 await dialog.getByLabel(/^End date/).fill('2030-12-31');
 const contributors=dialog.getByLabel(/^Number of contributors/);await expect(contributors).toHaveValue('1');
 for(const invalid of ['0','1.5']){await contributors.fill(invalid);await dialog.getByRole('button',{name:'Save project',exact:true}).click();await expect(dialog).toBeVisible();expect(await contributors.evaluate(e=>e.checkValidity())).toBe(false)}
 await contributors.fill('3');await dialog.getByLabel('Project goals (optional)',{exact:true}).fill('Deliver a semantic processor and measure Context Finder precision.');
 await dialog.getByLabel(/^Relevant links/).fill('javascript:alert(1)');await dialog.getByRole('button',{name:'Save project',exact:true}).click();await expect(dialog.getByRole('alert')).toContainText('http:// or https://');
 await dialog.getByLabel(/^Relevant links/).fill('https://github.com/example/vector\nhttps://example.com/vector/docs');
 await dialog.getByRole('button',{name:'Save project',exact:true}).click();await saved(page);
 let project=await projectNamed(request,'QA Redesign Vector');
 expect(project).toMatchObject({affiliations:['Waterloo Reality Labs','University of Waterloo'],contributors:3,importance:8.5,difficulty:7.5,status:'planning',category:'software',start_date:'2030-01-01',end_date:'2030-12-31'});
 expect(project.links).toHaveLength(2);expect((await state(request)).tasks.length).toBe(beforeTasks);
 await expectNoProjectTracker(card(page,project.name));
 const emptyPlan=await json(request,'/api/schedules/generate','post',{date:'2032-06-01',mode:'balanced'});
 expect(emptyPlan.blocks.filter(b=>b.project_id===project.id)).toEqual([]);
 await page.reload();await nav(page,'Tasks & deadlines');await weekTab(page);await page.getByLabel('Task week date',{exact:true}).fill('2032-06-01');await expect(page.locator('.task-week-loading')).toHaveCount(0);await nav(page,'Personal projects');await page.getByRole('button',{name:project.name,exact:true}).click();
 await expectNoProjectTracker(page.getByRole('dialog'));await expect(page.getByRole('dialog')).toContainText(project.description);await expect(page.getByRole('dialog')).toContainText(project.goals);await expect(page.getByRole('dialog').getByRole('link')).toHaveCount(2);
 await page.getByRole('button',{name:'Add linked task',exact:true}).click();await expect(page.getByRole('dialog').locator('.related-entity-selected').getByTitle(`project ID ${project.id}`,{exact:true})).toBeVisible();
 await taskForm(page,'QA Redesign semantic processor',60);await page.getByLabel(/^Deadline \(/).fill('2032-06-01T10:00');await page.getByRole('button',{name:'Save task',exact:true}).click();await saved(page);
 let work=await taskNamed(request,'QA Redesign semantic processor');expect(work.project_id).toBe(project.id);
 await expectNoProjectTracker(card(page,project.name));
 await card(page,project.name).getByRole('button',{name:/View tasks/}).click();
 await expect(page.getByRole('combobox',{name:'Filter tasks by project',exact:true})).toHaveValue(project.id);await expect(page.getByRole('button',{name:'Edit QA Redesign semantic processor',exact:true})).toBeVisible();
 await weekTab(page);await page.getByLabel('Task week date',{exact:true}).fill('2032-06-01');await expect(page.locator('.task-week-loading')).toHaveCount(0);
 await page.getByRole('button',{name:'Add task',exact:true}).first().click();await taskForm(page,'QA Redesign evaluate context',30,project.id);await page.getByRole('button',{name:'Save task',exact:true}).click();await saved(page);
 let second=await taskNamed(request,'QA Redesign evaluate context');expect(second.project_id).toBe(project.id);
 await page.getByRole('button',{name:`Edit ${second.title}`,exact:true}).click();await page.getByRole('dialog').locator('.related-entity-selected').getByTitle(`project ID ${project.id}`,{exact:true}).getByRole('button',{name:/^Remove link to/}).click();await page.getByRole('button',{name:'Save task',exact:true}).click();await saved(page);
 expect((await taskNamed(request,second.title)).project_id).toBeNull();
 await page.getByRole('button',{name:'Show all tasks',exact:true}).click();await page.getByRole('button',{name:`Edit ${second.title}`,exact:true}).click();await chooseRelated(page,'project',project.id);await page.getByRole('button',{name:'Save task',exact:true}).click();await saved(page);
 // Future work can meet a scheduling target without invented completion credit.
 const futurePlan=await json(request,'/api/schedules/generate','post',{date:'2032-06-01'}),futureBlock=futurePlan.blocks.find(b=>b.task_id===second.id);expect(futureBlock).toBeTruthy();
 const premature=await request.post(`/api/schedules/${futurePlan.id}/blocks/${futureBlock.id}/completion`,{data:{completed:true}});expect(premature.status()).toBe(409);
 expect((await json(request,`/api/task-week?week_start=${sundayOf('2032-06-01')}`)).assignments.find(a=>a.task_definition_id===second.id).completed_minutes).toBe(0);
 await page.reload();await nav(page,'Tasks & deadlines');await weekTab(page);await page.getByLabel('Task week date',{exact:true}).fill('2032-06-01');await expect(page.locator('.task-week-loading')).toHaveCount(0);
 await expect(taskCard(page,work.title)).toContainText('1 of 1 minimum sessions allocated');await expect(taskCard(page,work.title).getByRole('progressbar',{name:`${work.title} weekly target allocation`,exact:true})).toHaveAttribute('aria-valuenow','100');
 await nav(page,'Personal projects');await expectNoProjectTracker(card(page,project.name));
 await card(page,project.name).getByRole('button',{name:project.name,exact:true}).click();await expectNoProjectTracker(page.getByRole('dialog'));await expect(page.getByRole('dialog')).toContainText(work.title);await closeDialog(page);
 await card(page,project.name).getByRole('button',{name:`Edit ${project.name}`,exact:true}).click();
 await page.getByLabel('Project name (required)',{exact:true}).fill('QA Redesign Vector refreshed');await page.getByRole('combobox',{name:'Project status',exact:true}).selectOption('active');await page.getByLabel(/^Description/).fill('Revised technical context; no model interpretation is implied.');
 await page.getByRole('slider',{name:'Importance',exact:true}).press('ArrowRight');await page.getByRole('slider',{name:'Difficulty',exact:true}).press('Home');await page.getByRole('slider',{name:'Difficulty',exact:true}).press('ArrowRight');
 await page.getByRole('button',{name:'Save project',exact:true}).click();await saved(page);project=await projectNamed(request,'QA Redesign Vector refreshed');expect(project).toMatchObject({importance:9,difficulty:0.5,status:'active'});expect((await taskNamed(request,work.title)).project_id).toBe(project.id);
 await page.getByRole('textbox',{name:'Search projects',exact:true}).fill('Waterloo Reality');await expect(card(page,project.name)).toBeVisible();await page.getByRole('combobox',{name:'Filter projects by category',exact:true}).selectOption('research');await expect(card(page,project.name)).toHaveCount(0);await page.getByRole('button',{name:'Clear filters',exact:true}).click();await page.getByRole('combobox',{name:'Sort projects',exact:true}).selectOption('name');
 await nav(page,'Overview');await page.getByLabel('Planning date',{exact:true}).fill('2032-06-01');await page.getByRole('button',{name:/Generate My Schedule/i}).click();
 await expect(page.getByRole('button',{name:'Reoptimize day',exact:true})).toBeEnabled({timeout:30000});
 let plan=(await state(request)).schedules.find(s=>s.date==='2032-06-01');let sessions=plan.blocks.filter(b=>b.task_id===work.id);expect(sessions.length).toBeGreaterThanOrEqual(1);for(const session of sessions){expect((Date.parse(session.end)-Date.parse(session.start))/60000).toBe(60);expect(Date.parse(session.end)).toBeLessThanOrEqual(Date.parse('2032-06-01T10:00:00-04:00'));expect(session.project_id).toBe(project.id)}expect(plan.conflicts).toEqual([]);
 await nav(page,'Personal projects');await card(page,project.name).getByRole('button',{name:`Edit ${project.name}`,exact:true}).click();await page.getByRole('combobox',{name:'Project status',exact:true}).selectOption('paused');await page.getByRole('button',{name:'Save project',exact:true}).click();await saved(page);
 await nav(page,'Daily planner');await expect(page.locator('.calendar-stale-note')).toContainText('project');await page.getByRole('button',{name:'Reoptimize day',exact:true}).click();await expect(page.getByRole('button',{name:'Reoptimize day',exact:true})).toBeEnabled({timeout:30000});
 plan=(await state(request)).schedules.find(s=>s.date==='2032-06-01');expect(plan.blocks.some(b=>b.task_id===work.id)).toBe(false);expect(plan.excluded_tasks.some(t=>t.task_id===work.id&&t.reason.includes('paused'))).toBe(true);await expect(page.locator('.planner-aside')).toContainText(work.title);
 await page.getByLabel('Include tasks from paused and archived projects',{exact:true}).check();await page.getByRole('button',{name:'Reoptimize day',exact:true}).click();await expect(page.getByRole('button',{name:'Reoptimize day',exact:true})).toBeEnabled({timeout:30000});
 expect((await state(request)).schedules.find(s=>s.date==='2032-06-01').blocks.some(b=>b.task_id===work.id)).toBe(true);await expect(page.getByLabel('Include tasks from paused and archived projects',{exact:true})).not.toBeChecked();
 await nav(page,'Personal projects');await card(page,project.name).getByRole('button',{name:/View tasks/}).click();await nav(page,'Personal projects');
 const refusal=await request.delete(`/api/projects/${project.id}`);expect(refusal.status()).toBe(409);expect((await taskNamed(request,work.title)).project_id).toBe(project.id);
 await card(page,project.name).getByRole('button',{name:`Delete ${project.name}`,exact:true}).click();await expect(page.getByRole('dialog')).toContainText('2 linked tasks will be kept');await page.getByRole('button',{name:'Delete project & keep tasks',exact:true}).click();await saved(page);
 await nav(page,'Tasks & deadlines');await libraryTab(page);await expect(page.getByRole('button',{name:`Edit ${work.title}`,exact:true})).toBeVisible();await expect(page.getByRole('combobox',{name:'Filter tasks by project',exact:true})).toHaveValue('');
 expect((await taskNamed(request,work.title)).project_id).toBeNull();expect((await taskNamed(request,second.title)).project_id).toBeNull();expect((await taskNamed(request,work.title)).duration_minutes).toBe(60);expect(await projectNamed(request,project.name)).toBeUndefined();
 expect(errors).toEqual([]);
});

test('project cards, metadata form, details and associated tasks are accessible in every theme and viewport',async({page,request},testInfo)=>{
 test.setTimeout(300000);
 const project=await json(request,'/api/projects','post',{name:'QA Theme Vector',category:'software',status:'active',importance:8.5,difficulty:7.5,affiliations:['Waterloo Reality Labs','University of Waterloo'],contributors:3,start_date:'2026-11-01',end_date:'2027-08-31',description:'A thoughtful place for technical purpose, responsibilities, and challenges.\nLong-term project context remains distinct from daily work.',goals:'Deliver a semantic processor, evaluate context precision, and improve visual explanations.',links:['https://github.com/example/vector','https://example.com/documentation/long-project-context-and-responsibilities']});
 const themeParts=new Intl.DateTimeFormat('en-CA',{timeZone:(await state(request)).settings.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
 const themeToday=['year','month','day'].map(type=>themeParts.find(part=>part.type===type).value).join('-');
 for(const [title,minutes,credit] of [['QA Theme implement semantic processor',120,30],['QA Theme completed evaluation',90,90]]){
  const task=await json(request,'/api/task-definitions','post',{title,task_type:'project_work',project_id:project.id,session_minutes:minutes,allow_splitting:true,min_chunk_minutes:25});
  const assignment=await json(request,'/api/task-weeks','post',{task_definition_id:task.id,week_start:themeToday,min_sessions_per_week:1});
  await json(request,'/api/task-sessions','post',{assignment_id:assignment.id,completed_minutes:credit});
 }
 for(const [name,status,category] of [['QA Theme Research','planning','research'],['QA Theme Personal Portfolio','paused','personal'],['QA Theme Archive','archived','extracurricular']])await json(request,'/api/projects','post',{name,status,category,importance:6,difficulty:4.5,affiliations:['Independent'],description:'A second project card for status and layout comparison.'});
 // Browser-local theme takes precedence. Align a fresh context with the API
 // fixture before testing actual changes, rather than expecting a no-op light
 // selection to synchronize a warm preference left by a preceding workflow.
 const initialSettings=(await state(request)).settings;
 await json(request,'/api/settings','put',{...initialSettings,theme:'warm'});
 const initialTheme=(await state(request)).settings.theme;
 expect(initialTheme).toBe('warm');
 await page.addInitScript(theme=>localStorage.setItem('daycraft-theme',theme),initialTheme);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('/');await nav(page,'Personal projects');
 // Navigation renders before the initial workspace request finishes. Wait for
 // this fixture to be loaded before testing a persisted theme change.
 await expect(card(page,project.name)).toBeVisible();
 for(const theme of ['light','dark','midnight','warm']){
  await page.setViewportSize({width:1440,height:1000});await choosePersistedTheme(page,request,theme,testInfo);
  await expectNoProjectTracker(card(page,project.name));await captureAudit(page,`projects-desktop-${theme}`);
  await card(page,project.name).getByRole('button',{name:`Edit ${project.name}`,exact:true}).click();await captureAudit(page,`project-form-desktop-${theme}`);await closeDialog(page);
  await page.getByRole('button',{name:project.name,exact:true}).click();await expectNoProjectTracker(page.getByRole('dialog'));await captureAudit(page,`project-detail-desktop-${theme}`);await closeDialog(page);
  await page.setViewportSize({width:390,height:844});await captureAudit(page,`projects-mobile-${theme}`);
  await card(page,project.name).getByRole('button',{name:`Edit ${project.name}`,exact:true}).click();await captureAudit(page,`project-form-mobile-${theme}`);await page.getByRole('dialog').locator('summary').filter({hasText:'Dates, contributors, goals & links'}).click();await page.getByLabel(/^Relevant links/).scrollIntoViewIfNeeded();await captureAudit(page,`project-form-expanded-mobile-${theme}`);await closeDialog(page);
  await page.getByRole('button',{name:project.name,exact:true}).click();await expectNoProjectTracker(page.getByRole('dialog'));await captureAudit(page,`project-detail-mobile-${theme}`);await closeDialog(page);
  await card(page,project.name).getByRole('button',{name:/View tasks/}).click();await captureAudit(page,`project-tasks-mobile-${theme}`);await nav(page,'Personal projects');
 }
 await page.setViewportSize({width:768,height:1024});await captureAudit(page,'projects-tablet-warm');await page.getByRole('button',{name:project.name,exact:true}).click();await captureAudit(page,'project-detail-tablet-warm');await closeDialog(page);
 expect(errors).toEqual([]);
});
