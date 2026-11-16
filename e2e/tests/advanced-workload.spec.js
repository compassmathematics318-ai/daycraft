import {test,expect} from '@playwright/test';
import fs from 'node:fs/promises';
import {sundayOf} from '../task-helpers.js';

async function json(request,path,method='get',data){const response=await request[method](path,{data,...(path.includes('/schedules/generate')?{timeout:45000}:{})});expect(response.ok(),await response.text()).toBeTruthy();return response.status()===204?null:response.json()}
const minutes=block=>(Date.parse(block.end)-Date.parse(block.start))/60000;
const levels=['very_low','low','medium','high','very_high'];

test('all workloads preserve actual anchors and meals across 22:30 and 23:30 availability',async({page,request},testInfo)=>{
 test.setTimeout(300000);
 const original=(await json(request,'/api/state')).settings,date='2039-05-09',summaries=[];
 const meals=[{id:'advanced-first',name:'First meal',duration_minutes:20,enabled:true},
              {id:'advanced-second',name:'Second meal',duration_minutes:20,enabled:true}];
 try{
  const activity=await json(request,'/api/activities','post',{title:'Advanced fixed commitment',category:'commitment',subtype:'Personal',location_mode:'remote'});
  const occurrence=await json(request,'/api/occurrences','post',{activity_id:activity.id,start:`${date}T12:00:00-04:00`,end:`${date}T13:00:00-04:00`});
  const task=await json(request,'/api/task-definitions','post',{title:'Advanced meaningful academic study',task_type:'academic',session_minutes:45,min_sessions_per_week:4,min_sessions_per_day:1,importance:10,difficulty:3,location_mode:'remote'});
  await json(request,'/api/task-weeks','post',{task_definition_id:task.id,week_start:sundayOf(date)});
  await page.goto('/');await page.getByLabel('Planning date',{exact:true}).fill(date);
  await page.locator('.nav-item').filter({hasText:'Daily planner'}).first().click();
  for(const cutoff of ['22:30','23:30']){
   await json(request,'/api/settings','put',{...original,wake_time:'07:00',sleep_time:'00:00',work_start:'08:00',work_end:cutoff,focus_minutes:60,break_minutes:10,home_location_id:null,default_location_id:null,start_at_home:false,end_at_home:false,meals});
   await page.reload();await page.getByLabel('Planning date',{exact:true}).fill(date);await page.locator('.nav-item').filter({hasText:'Daily planner'}).first().click();
   for(const level of levels){
    const selector=page.getByRole('combobox',{name:'Workload Level',exact:true});await expect(selector).toBeEnabled();await selector.selectOption(level);
    await expect.poll(async()=>(await json(request,`/api/day-preferences/${date}`)).workload_level).toBe(level);
    const pending=page.waitForResponse(response=>response.url().endsWith('/api/schedules/generate')&&response.request().method()==='POST',{timeout:45000});
    await page.getByRole('button',{name:/^(Generate schedule|Reoptimize day)$/i}).click();const response=await pending;expect(response.ok(),await response.text()).toBeTruthy();const plan=await response.json();
    expect(['OPTIMAL','FEASIBLE']).toContain(plan.solver_status);expect(plan.conflicts).toEqual([]);expect(plan.workload_level).toBe(level);
    const ordered=plan.blocks.toSorted((a,b)=>Date.parse(a.start)-Date.parse(b.start));
    const anchor=ordered.find(block=>block.occurrence_id===occurrence.id);expect(Date.parse(anchor.start)).toBe(Date.parse(occurrence.start));expect(Date.parse(anchor.end)).toBe(Date.parse(occurrence.end));
    expect(ordered.filter(block=>block.kind==='meal').map(block=>block.meal_id)).toEqual(meals.map(meal=>meal.id));
    for(let index=1;index<ordered.length;index++)expect(Date.parse(ordered[index].start)).toBeGreaterThanOrEqual(Date.parse(ordered[index-1].end));
    const work=ordered.filter(block=>block.task_id===task.id);expect(work.length).toBeGreaterThan(0);
    for(const block of work)expect(Date.parse(block.end)).toBeLessThanOrEqual(Date.parse(`${date}T${cutoff}:00-04:00`));
    const summary={cutoff,level,work_minutes:work.reduce((total,block)=>total+minutes(block),0),stats:plan.stats,explanations:plan.explanations};summaries.push(summary);
    await expect(page.locator('main')).toContainText(/Weekly session minimums are soft goals/);
   }
  }
  for(const cutoff of ['22:30','23:30']){const rows=summaries.filter(row=>row.cutoff===cutoff);expect(rows[4].work_minutes).toBeGreaterThanOrEqual(rows[3].work_minutes);expect(rows[4].work_minutes).toBeGreaterThan(rows[0].work_minutes)}
  await fs.mkdir('../test-results/advanced-workload',{recursive:true});await fs.writeFile('../test-results/advanced-workload/browser-comparison.json',JSON.stringify(summaries,null,2));await testInfo.attach('ten-actual-workload-plans',{body:JSON.stringify(summaries,null,2),contentType:'application/json'});
  await page.screenshot({path:'../test-results/advanced-workload/planner.png',fullPage:true});
 }finally{await json(request,'/api/settings','put',original)}
});

test('a 55 minute tail does not shorten an unfinished 120 minute session and shows its explanation',async({page,request})=>{
 const original=(await json(request,'/api/state')).settings,date='2039-06-19';
 try{
  await json(request,'/api/settings','put',{...original,wake_time:'07:00',sleep_time:'23:30',work_start:'08:00',work_end:'10:55',break_minutes:0,home_location_id:null,default_location_id:null,start_at_home:false,end_at_home:false,meals:[]});
  const task=await json(request,'/api/task-definitions','post',{title:'Advanced indivisible 120 minute practice',task_type:'academic',session_minutes:120,min_sessions_per_week:2,min_sessions_per_day:1,importance:8,difficulty:2,allow_splitting:false,location_mode:'remote'});
  await json(request,'/api/task-weeks','post',{task_definition_id:task.id,week_start:sundayOf(date)});
  await page.goto('/');await page.getByLabel('Planning date',{exact:true}).fill(date);await page.locator('.nav-item').filter({hasText:'Daily planner'}).first().click();
  await page.getByRole('combobox',{name:'Workload Level',exact:true}).selectOption('very_high');await expect.poll(async()=>(await json(request,`/api/day-preferences/${date}`)).workload_level).toBe('very_high');
  const pending=page.waitForResponse(response=>response.url().endsWith('/api/schedules/generate')&&response.request().method()==='POST',{timeout:45000});await page.getByRole('button',{name:/^(Generate schedule|Reoptimize day)$/i}).click();const response=await pending;expect(response.ok(),await response.text()).toBeTruthy();const plan=await response.json();
  expect(plan.conflicts).toEqual([]);const work=plan.blocks.filter(block=>block.task_id===task.id);expect(work).toHaveLength(1);expect(minutes(work[0])).toBe(120);
  expect(plan.stats.tail_diagnostics.contiguous_free_minutes).toBe(55);
  expect(plan.stats.tail_diagnostics.remaining_candidates.some(candidate=>candidate.minimum_chunk_minutes===120||candidate.min_session_minutes===120)).toBeTruthy();
  await expect(page.locator('main')).toContainText(/Weekly session minimums are soft goals/);
 }finally{await json(request,'/api/settings','put',original)}
});

