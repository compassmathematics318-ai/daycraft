import {test,expect} from '@playwright/test';
import fs from 'node:fs/promises';
import {sundayOf} from '../task-helpers.js';

async function json(request,path,method='get',data){const r=await request[method](path,{data,...(path.includes('/schedules/generate')?{timeout:45000}:{})});expect(r.ok(),await r.text()).toBeTruthy();return r.status()===204?null:r.json()}
async function nav(page,label){await page.locator('.nav-item').filter({hasText:label}).first().click()}
const minutes=b=>(Date.parse(b.end)-Date.parse(b.start))/60000;

test('five workloads produce useful marginal work and retain anchors, meals and terminal recovery',async({page,request},testInfo)=>{
 test.setTimeout(180000);
 const original=(await json(request,'/api/state')).settings,date='2037-05-09',levels=['very_low','low','medium','high','very_high'];
 const meals=[{id:'quality-first',name:'First meal',duration_minutes:20,enabled:true},{id:'quality-second',name:'Second meal',duration_minutes:20,enabled:true}];
 try{
  await json(request,'/api/settings','put',{...original,wake_time:'07:00',sleep_time:'23:00',work_start:'08:00',work_end:'22:00',focus_minutes:60,break_minutes:10,home_location_id:null,default_location_id:null,start_at_home:false,end_at_home:false,meals});
  const activity=await json(request,'/api/activities','post',{title:'Quality fixed appointment',category:'commitment',subtype:'Personal',location_mode:'remote'});
  const occurrence=await json(request,'/api/occurrences','post',{activity_id:activity.id,start:`${date}T12:00:00-04:00`,end:`${date}T13:00:00-04:00`});
  const task=await json(request,'/api/task-definitions','post',{title:'Quality useful academic study',task_type:'academic',session_minutes:45,min_sessions_per_week:1,min_sessions_per_day:1,importance:10,difficulty:3,location_mode:'remote'});
  await json(request,'/api/task-weeks','post',{task_definition_id:task.id,week_start:sundayOf(date)});
  await page.goto('/');await page.getByLabel('Planning date',{exact:true}).fill(date);
  const summaries=[];
  for(const [index,level] of levels.entries()){
   await nav(page,index%2?'Daily planner':'Overview');
   const selector=page.getByRole('combobox',{name:'Workload Level',exact:true});await expect(selector).toBeEnabled();await selector.selectOption(level);
   await expect.poll(async()=>(await json(request,`/api/day-preferences/${date}`)).workload_level).toBe(level);
   await nav(page,'Daily planner');await expect(page.getByRole('combobox',{name:'Workload Level',exact:true})).toHaveValue(level);
   const pending=page.waitForResponse(r=>r.url().endsWith('/api/schedules/generate')&&r.request().method()==='POST',{timeout:45000});
   await page.getByRole('button',{name:/^(Generate schedule|Reoptimize day)$/i}).click();const response=await pending;expect(response.ok(),await response.text()).toBeTruthy();const plan=await response.json();
   expect(['OPTIMAL','FEASIBLE']).toContain(plan.solver_status);expect(plan.conflicts).toEqual([]);expect(plan.workload_level).toBe(level);
   const work=plan.blocks.filter(b=>b.task_id===task.id),ordered=[...plan.blocks].sort((a,b)=>Date.parse(a.start)-Date.parse(b.start));
   const anchor=ordered.find(b=>b.occurrence_id===occurrence.id);expect(Date.parse(anchor.start)).toBe(Date.parse(occurrence.start));expect(Date.parse(anchor.end)).toBe(Date.parse(occurrence.end));
   expect(ordered.filter(b=>b.kind==='meal').map(b=>b.meal_id)).toEqual(meals.map(m=>m.id));
   for(let i=1;i<ordered.length;i++)expect(Date.parse(ordered[i].start)).toBeGreaterThanOrEqual(Date.parse(ordered[i-1].end));
   expect(work.length).toBeGreaterThan(0);const last=work.toSorted((a,b)=>Date.parse(a.end)-Date.parse(b.end)).at(-1);
   expect(ordered.some(b=>b.kind==='break'&&Date.parse(b.start)>=Date.parse(last.end)),'No recovery exists solely after terminal work').toBe(false);
   summaries.push({level,work_minutes:work.reduce((sum,b)=>sum+minutes(b),0),last_work_end:last.end,break_minutes:ordered.filter(b=>b.kind==='break').reduce((s,b)=>s+minutes(b),0)});
  }
  expect(summaries[4].work_minutes).toBeGreaterThan(summaries[3].work_minutes);expect(summaries[3].work_minutes).toBeGreaterThan(summaries[0].work_minutes);
  await fs.mkdir('../test-results/workload-quality',{recursive:true});await fs.writeFile('../test-results/workload-quality/browser-comparison.json',JSON.stringify(summaries,null,2));await testInfo.attach('useful-work-comparison',{body:JSON.stringify(summaries,null,2),contentType:'application/json'});
  await expect(page.locator('.toast')).toHaveCount(0);await page.screenshot({path:'../test-results/workload-quality/planner.png',fullPage:true});
 }finally{await json(request,'/api/settings','put',original)}
});

test('midnight sleep and availability persist through Preferences save and refresh',async({page,request})=>{
 const original=(await json(request,'/api/state')).settings;
 try{
  await page.goto('/');await nav(page,'Preferences');await page.getByLabel('Sleep time',{exact:true}).fill('00:00');await page.getByLabel('Available until',{exact:true}).fill('23:30');await page.getByRole('button',{name:'Save preferences',exact:true}).click();
  await expect.poll(async()=>{const s=(await json(request,'/api/state')).settings;return [s.sleep_time,s.work_end]}).toEqual(['00:00','23:30']);
  await page.reload();await nav(page,'Preferences');await expect(page.getByLabel('Sleep time',{exact:true})).toHaveValue('00:00');await expect(page.getByLabel('Available until',{exact:true})).toHaveValue('23:30');
 }finally{await json(request,'/api/settings','put',original)}
});
