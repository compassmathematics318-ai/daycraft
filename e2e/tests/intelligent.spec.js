import {test,expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs/promises';
import {sundayOf} from '../task-helpers.js';

async function json(request,path,method='get',data){const response=await request[method](path,{data,...(path.includes('/schedules/generate')?{timeout:45000}:{})});expect(response.ok(),await response.text()).toBeTruthy();return response.status()===204?null:response.json()}
const state=request=>json(request,'/api/state');
async function nav(page,label){await page.locator('.nav-item').filter({hasText:label}).first().click()}
async function savePreferences(page,request,predicate){await page.getByRole('button',{name:'Save preferences',exact:true}).click();await expect.poll(async()=>predicate((await state(request)).settings)).toBe(true);await expect(page.getByRole('button',{name:'Save preferences',exact:true})).toBeEnabled()}
async function capture(page,testInfo,name){await fs.mkdir('../test-results/intelligent-scheduling/ui',{recursive:true});await expect(page.locator('.toast')).toHaveCount(0);await page.locator('main').focus();const path=`../test-results/intelligent-scheduling/ui/${name}.png`;await page.screenshot({path,fullPage:true,animations:'disabled'});await testInfo.attach(name,{path,contentType:'image/png'});await page.screenshot({path:`../test-results/intelligent-scheduling/ui/${name}-viewport.png`,animations:'disabled'})}

test('flexible meals have duration, enable and venue controls; custom legacy preferences survive edits',async({page,request},testInfo)=>{
 const original=(await state(request)).settings;
 expect(original.meals.map(m=>[m.name,m.duration_minutes,m.time??null])).toEqual([['Breakfast',30,null],['Lunch',45,null],['Dinner',30,null]]);
 const venue=await json(request,'/api/locations','post',{name:'QA meal kitchen',lat:43.47,lon:-80.54});
 await json(request,'/api/settings','put',{...original,meals:[{id:'qa-legacy',name:'Custom lunch',duration_minutes:65,time:'13:35',enabled:false,location_id:venue.id}]});
 await page.goto('/');await nav(page,'Preferences');
 const section=page.locator('section').filter({has:page.getByRole('heading',{name:'Meals & recovery',exact:true})});
 await expect(section).toContainText('Daycraft automatically chooses the meal time');
 await expect(section.locator('input[type=time]')).toHaveCount(0);
 const first=section.locator('.meal-row').first();
 await expect(first.getByLabel('Meal name',{exact:true})).toHaveValue('Custom lunch');
 await expect(first.getByLabel('Minutes',{exact:true})).toHaveValue('65');
 await expect(first.getByLabel('Include meal',{exact:true})).not.toBeChecked();
 await expect(first.getByLabel(/^Meal venue \(optional\)/)).toHaveValue(venue.id);
 await first.getByLabel('Meal name',{exact:true}).fill('Flexible lunch');await first.getByLabel('Minutes',{exact:true}).fill('70');await first.getByLabel('Include meal',{exact:true}).check();
 await first.getByLabel(/^Meal venue \(optional\)/).selectOption('');
 await section.getByRole('button',{name:'Add meal',exact:true}).click();
 const added=section.locator('.meal-row').last();await added.getByLabel('Meal name',{exact:true}).fill('Recovery snack');await added.getByLabel('Minutes',{exact:true}).fill('15');await added.getByLabel(/^Meal venue \(optional\)/).selectOption(venue.id);
 await savePreferences(page,request,s=>s.meals.length===2&&s.meals[1].name==='Recovery snack');
 expect((await state(request)).settings.meals[0]).toMatchObject({id:'qa-legacy',name:'Flexible lunch',duration_minutes:70,time:'13:35',enabled:true,location_id:null});
 await page.reload();await nav(page,'Preferences');await expect(section.locator('.meal-row')).toHaveCount(2);await expect(section.locator('.meal-row').last().getByLabel(/^Meal venue \(optional\)/)).toHaveValue(venue.id);
 await section.getByRole('button',{name:'Remove Recovery snack',exact:true}).click();await savePreferences(page,request,s=>s.meals.length===1);
 await capture(page,testInfo,'meal-preferences-desktop');
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 const audit=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();expect(audit.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))).toEqual([]);await testInfo.attach('meal-preferences-mobile-accessibility',{body:JSON.stringify(audit.violations,null,2),contentType:'application/json'});await capture(page,testInfo,'meal-preferences-mobile');
 await json(request,'/api/settings','put',original);
});

test('five real workload generations preserve anchors, meals, availability and strategy, and show truthful stale forecast state',async({page,request},testInfo)=>{
 test.setTimeout(240000);
 const original=(await state(request)).settings,date='2037-03-18',week=sundayOf(date),levels=['very_low','low','medium','high','very_high'];
 await json(request,'/api/settings','put',{...original,wake_time:'07:00',sleep_time:'23:00',work_start:'08:00',work_end:'22:00',focus_minutes:60,break_minutes:10,home_location_id:null,default_location_id:null,start_at_home:false,end_at_home:false});
 const activity=await json(request,'/api/activities','post',{title:'QA intelligent fixed lecture',category:'class',subtype:'Lecture',location_mode:'remote'});
 const occurrence=await json(request,'/api/occurrences','post',{activity_id:activity.id,start:`${date}T11:00:00-04:00`,end:`${date}T14:00:00-04:00`});
 const tasks=[];
 for(let index=0;index<7;index++){
  const task=await json(request,'/api/task-definitions','post',{title:`QA intelligent ${index===0?'urgent proof':'optional reading '+index}`,task_type:'academic',session_minutes:45,min_sessions_per_week:3,min_sessions_per_day:1,max_sessions_per_day:4,importance:index===0?10:Math.max(1,7-index),difficulty:index%3*3,location_mode:'remote',...(index===0?{due_at:`${date}T18:00:00-04:00`}:{})});tasks.push(task);await json(request,'/api/task-weeks','post',{task_definition_id:task.id,week_start:week});
 }
 await json(request,'/api/schedules/generate','post',{date:'2037-03-25',mode:'balanced'});
 const otherSchedulesBefore=(await json(request,'/api/schedules')).filter(plan=>plan.date!==date);
 const seed=await json(request,'/api/schedules/generate','post',{date,mode:'deadline'});expect(seed.mode).toBe('deadline');
 await page.goto('/');await page.getByLabel('Planning date',{exact:true}).fill(date);await nav(page,'Daily planner');
 const summaries=[];
 for(const [index,level] of levels.entries()){
  const before=(await json(request,`/api/schedules?date=${date}`)).at(-1);
  await expect(page.getByRole('combobox',{name:'Workload Level',exact:true})).toBeEnabled();await page.getByRole('combobox',{name:'Workload Level',exact:true}).selectOption(level);
  await expect.poll(async()=>(await json(request,`/api/day-preferences/${date}`)).workload_level).toBe(level);
  if(before.workload_level!==level){await expect(page.locator('.calendar-stale-note')).toContainText('preferences have changed');await expect(page.locator('.applied-workload')).toContainText('Current selection:');const stale=(await json(request,`/api/schedules?date=${date}`)).at(-1);expect(stale.blocks).toEqual(before.blocks);expect(stale.mode).toBe('deadline')}
  const responsePromise=page.waitForResponse(r=>r.url().endsWith('/api/schedules/generate')&&r.request().method()==='POST',{timeout:45000});await page.getByRole('button',{name:'Reoptimize day',exact:true}).click();const response=await responsePromise;expect(response.ok(),await response.text()).toBeTruthy();const plan=await response.json();
  expect(['OPTIMAL','FEASIBLE']).toContain(plan.solver_status);expect(plan.conflicts).toEqual([]);expect(plan.workload_level).toBe(level);expect(plan.mode).toBe('deadline');expect(response.request().postDataJSON()).toMatchObject({date,mode:'deadline',reoptimize:true});expect(response.request().postDataJSON()).not.toHaveProperty('workload_level');
  const anchor=plan.blocks.find(b=>b.occurrence_id===occurrence.id);expect(anchor).toBeTruthy();expect(Date.parse(anchor.start)).toBe(Date.parse(occurrence.start));expect(Date.parse(anchor.end)).toBe(Date.parse(occurrence.end));
  const meals=plan.blocks.filter(b=>b.kind==='meal');expect(meals.map(b=>b.title).sort()).toEqual(['Breakfast','Dinner','Lunch']);expect(meals.map(b=>(Date.parse(b.end)-Date.parse(b.start))/60000).sort((a,b)=>a-b)).toEqual([30,30,45]);
  const sorted=plan.blocks.toSorted((a,b)=>Date.parse(a.start)-Date.parse(b.start));for(let i=1;i<sorted.length;i++)expect(Date.parse(sorted[i].start)).toBeGreaterThanOrEqual(Date.parse(sorted[i-1].end));
  for(const block of plan.blocks.filter(b=>b.kind==='task'||b.kind==='project')){expect(block.start.slice(11,16)>='08:00').toBe(true);expect(block.end.slice(11,16)<='22:00').toBe(true);if(block.task_id===tasks[0].id)expect(Date.parse(block.end)).toBeLessThanOrEqual(Date.parse(`${date}T18:00:00-04:00`))}
  expect(plan.blocks.some(b=>b.task_id===tasks[0].id),'Urgent academic work must receive useful time at every workload').toBe(true);
  expect(plan.horizon_forecast).toMatchObject({forecast_only:true,start:date});expect(plan.horizon_forecast.days.length).toBeGreaterThanOrEqual(14);expect(plan.horizon_forecast.limitations.length).toBeGreaterThan(0);
  await expect(page.locator('.calendar-stale-note')).toHaveCount(0);await expect(page.locator('.applied-workload')).toContainText(`Applied workload: ${['Very Low','Low','Medium','High','Very High'][index]}`);await expect(page.locator('.forecast-panel')).toContainText('Forecast only. Future days are estimates; this does not reserve time or confirm completed work.');
  if(index===0){const meal=page.locator('.timeline-block.meal').first();await expect(meal).toHaveAttribute('draggable','false');await meal.click();await expect(page.getByRole('dialog').getByLabel(/^Start \(/)).toBeDisabled();await expect(page.getByRole('dialog').getByLabel('End',{exact:true})).toBeDisabled();await page.getByRole('dialog').getByRole('button',{name:'Cancel',exact:true}).click()}
  const schedules=await json(request,'/api/schedules');expect(schedules.filter(s=>s.date!==date)).toEqual(otherSchedulesBefore);
  summaries.push({level,status:plan.status,solver_status:plan.solver_status,work_minutes:plan.blocks.filter(b=>b.kind==='task'||b.kind==='project').reduce((sum,b)=>sum+(Date.parse(b.end)-Date.parse(b.start))/60000,0),break_minutes:plan.blocks.filter(b=>b.kind==='break').reduce((sum,b)=>sum+(Date.parse(b.end)-Date.parse(b.start))/60000,0),forecast_days:plan.horizon_forecast.days.length});
  await nav(page,'Overview');await expect(page.getByRole('combobox',{name:'Workload Level',exact:true})).toHaveValue(level);await nav(page,'Daily planner');
 }
 expect(summaries.at(-1).work_minutes).toBeGreaterThan(summaries[0].work_minutes);await testInfo.attach('actual-workload-comparison',{body:JSON.stringify(summaries,null,2),contentType:'application/json'});await fs.writeFile('../test-results/intelligent-scheduling/workload-browser-comparison.json',JSON.stringify(summaries,null,2));await capture(page,testInfo,'generated-plan-desktop');
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);const audit=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();expect(audit.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))).toEqual([]);await testInfo.attach('planner-mobile-accessibility',{body:JSON.stringify(audit.violations,null,2),contentType:'application/json'});await capture(page,testInfo,'generated-plan-mobile');
 await json(request,'/api/settings','put',original);
});

test('explicit assessment preparation cannot be presented after its actual linked quiz',async({page,request},testInfo)=>{
 test.setTimeout(90000);const original=(await state(request)).settings,date='2037-04-03';
 await json(request,'/api/settings','put',{...original,work_start:'10:00',work_end:'12:00',default_location_id:null,home_location_id:null,start_at_home:false,end_at_home:false});
 const assessment=await json(request,'/api/activities','post',{title:'QA linked morning quiz',category:'assessment',assessment_start:`${date}T09:00:00-04:00`,assessment_end:`${date}T10:00:00-04:00`,location_mode:'remote'});
 const task=await json(request,'/api/task-definitions','post',{title:'QA explicit quiz preparation',task_type:'academic',academic_subtype:'assessment_preparation',related_activity_id:assessment.id,session_minutes:30,min_sessions_per_week:1,importance:10,difficulty:7,location_mode:'remote'});
 await json(request,'/api/task-weeks','post',{task_definition_id:task.id,week_start:sundayOf(date)});
 await page.goto('/');await page.getByLabel('Planning date',{exact:true}).fill(date);await expect(page.getByRole('combobox',{name:'Workload Level',exact:true})).toBeEnabled();
 const responsePromise=page.waitForResponse(r=>r.url().endsWith('/api/schedules/generate')&&r.request().method()==='POST',{timeout:45000});await page.getByRole('button',{name:'Generate My Schedule',exact:true}).click();const response=await responsePromise;expect(response.ok(),await response.text()).toBeTruthy();const plan=await response.json();
 expect(['OPTIMAL','FEASIBLE']).toContain(plan.solver_status);expect(plan.blocks.filter(b=>b.task_id===task.id)).toEqual([]);expect(plan.weekly_progress.find(p=>p.task_definition_id===task.id).expected_shortfall).toBe(1);const risk=plan.horizon_forecast.task_risks.find(r=>r.task_definition_id===task.id);expect(['at_risk','overdue']).toContain(risk.deadline_risk);expect(Date.parse(risk.preparation_cutoff)).toBe(Date.parse(assessment.assessment_start));
 await expect(page.locator('.forecast-panel')).toContainText(task.title);await expect(page.locator('.timeline-block').filter({hasText:task.title})).toHaveCount(0);
 const saved=(await state(request)).task_definitions.find(t=>t.id===task.id);expect(saved.status).toBe('active');expect(saved.assessment_at).toBeNull();const weekly=await json(request,`/api/task-week?week_start=${date}`);expect(weekly.assignments.find(a=>a.task_definition_id===task.id).completed_minutes).toBe(0);
 await testInfo.attach('actual-linked-assessment-preparation',{body:JSON.stringify({solver_status:plan.solver_status,forecast:risk,weekly_progress:plan.weekly_progress.find(p=>p.task_definition_id===task.id)},null,2),contentType:'application/json'});await json(request,'/api/settings','put',original);
});
