import {test,expect} from '@playwright/test';
import {taskCard,weekTab,libraryTab,sundayOf,addDays} from '../task-helpers.js';

async function json(request,path,method='get',data){const response=await request[method](path,{data,...(path.includes('/schedules/generate')?{timeout:45000}:{})});expect(response.ok(),await response.text()).toBeTruthy();return response.status()===204?null:response.json()}
const state=request=>json(request,'/api/state');
const week=(request,date)=>json(request,`/api/task-week?week_start=${date}`);
test.beforeEach(async({page})=>{await page.route('https://tile.openstreetmap.org/**',route=>route.fulfill({status:200,contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j85sAAAAASUVORK5CYII=','base64')}))});
async function nav(page,text='Tasks & deadlines'){const toggle=page.getByRole('button',{name:'Open navigation',exact:true});if(await toggle.isVisible()&&!await page.locator('.sidebar').evaluate(e=>e.classList.contains('open')))await toggle.click();await page.locator('.nav-item').filter({hasText:text}).first().click()}
async function selectedWeek(page,date){await page.getByLabel('Task week date',{exact:true}).fill(date);await expect(page.locator('.task-week-loading')).toHaveCount(0)}
async function deleteTask(page,title){await taskCard(page,title).getByRole('button',{name:'Delete task everywhere',exact:true}).click();await expect(page.getByRole('dialog')).toContainText(title);await page.getByRole('dialog').getByRole('button',{name:'Delete task everywhere',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0)}
async function completedPlan(request,date,task){const plan=await json(request,'/api/schedules/generate','post',{date});const own=plan.blocks.filter(b=>b.task_id===task.id);expect(own.length).toBeGreaterThan(0);for(const block of own){expect(Date.parse(block.end)).toBeLessThanOrEqual(Date.now());await json(request,`/api/schedules/${plan.id}/blocks/${block.id}/completion`,'post',{completed:true})}return plan}

test('global deletion removes recurring and week-specific work from management and map while preserving verified history and same-name neighbors',async({page,request})=>{
 test.setTimeout(240000);
 const original=(await state(request)).settings;await json(request,'/api/settings','put',{...original,work_start:'07:00',work_end:'22:00',focus_minutes:180,break_minutes:0,meals:[],default_location_id:null,home_location_id:null,start_at_home:false});
 const location=await json(request,'/api/locations','post',{name:'QA Lifecycle shared place',lat:43.47,lon:-80.54});
 const title='QA Lifecycle duplicate title',neighbor=await json(request,'/api/activities','post',{title,category:'commitment',subtype:'Personal',location_id:location.id,location_mode:'required'});
 const past=sundayOf('2021-01-06'),future=sundayOf('2048-01-06');
 await page.goto('/');
 for(const recurring of [true,false]){
  const task=await json(request,'/api/task-definitions','post',{title,session_minutes:10,min_sessions_per_week:1,max_sessions_per_day:1,importance:10,difficulty:0,location_id:location.id,location_mode:'required',...(recurring?{recurrence:{start_week:past}}:{})});
  if(!recurring)for(const date of [past,future,addDays(future,7)])await json(request,'/api/task-weeks','post',{task_definition_id:task.id,week_start:date});
  const history=await completedPlan(request,addDays(past,1),task);const pending=await json(request,'/api/schedules/generate','post',{date:addDays(future,1)});expect(pending.blocks.some(b=>b.task_id===task.id)).toBe(true);await json(request,`/api/schedules/${pending.id}`,'put',{blocks:pending.blocks.map(b=>b.task_id===task.id?{...b,locked:true}:b)});
  await page.reload();await nav(page);await libraryTab(page);await page.getByLabel('Search tasks',{exact:true}).fill(title);await deleteTask(page,title);await expect(taskCard(page,title)).toHaveCount(0);
  expect((await state(request)).task_definitions.some(t=>t.id===task.id)).toBe(false);expect((await json(request,'/api/task-definitions')).some(t=>t.id===task.id)).toBe(false);
  for(const date of [past,future,addDays(future,7)]){expect((await week(request,date)).assignments.some(a=>a.task_definition_id===task.id)).toBe(false);expect(JSON.stringify(await json(request,`/api/location-overview?week_start=${date}`))).not.toContain(task.id)}
  const schedules=await json(request,'/api/schedules');expect(schedules.find(s=>s.id===history.id).blocks.some(b=>b.task_id===task.id&&b.status==='completed')).toBe(true);expect(schedules.find(s=>s.id===pending.id).blocks.some(b=>b.task_id===task.id)).toBe(false);
  await page.reload();await nav(page);for(const open of [libraryTab,weekTab]){await open(page);await page.getByLabel('Filter tasks by status',{exact:true}).selectOption('all');await expect(taskCard(page,title)).toHaveCount(0)}
  await nav(page,'Locations & map');await page.getByLabel('Week containing',{exact:true}).fill(future);await page.getByLabel('Search mapped activities and places',{exact:true}).fill(title);await expect(page.locator('.geo-reference-group')).toHaveCount(1);await expect(page.locator('.geo-reference-group')).toContainText(title);
  expect((await state(request)).activities.some(a=>a.id===neighbor.id)).toBe(true);expect((await state(request)).locations.some(p=>p.id===location.id)).toBe(true);
 }
 await json(request,'/api/settings','put',original);
});

test('removing one selected week preserves the task library, other weeks and completed history',async({page,request})=>{
 test.setTimeout(180000);const first=sundayOf('2049-04-06'),second=addDays(first,7),title='QA Lifecycle remove only one week';
 const task=await json(request,'/api/task-definitions','post',{title,session_minutes:15,min_sessions_per_week:1,max_sessions_per_day:1,importance:10,difficulty:0});
 const assignments=[];for(const date of [first,second])assignments.push(await json(request,'/api/task-weeks','post',{task_definition_id:task.id,week_start:date}));
 const plan=await json(request,'/api/schedules/generate','post',{date:addDays(first,1)});expect(plan.blocks.some(b=>b.task_id===task.id)).toBe(true);
 await page.goto('/');await nav(page);await weekTab(page);await selectedWeek(page,first);await taskCard(page,title).getByRole('button',{name:'Remove from this week',exact:true}).click();await page.getByRole('dialog').getByRole('button',{name:'Remove from this week',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);await expect(taskCard(page,title)).toHaveCount(0);
 expect((await week(request,first)).assignments.some(a=>a.task_definition_id===task.id)).toBe(false);expect((await week(request,second)).assignments.find(a=>a.task_definition_id===task.id).id).toBe(assignments[1].id);expect((await state(request)).task_definitions.some(t=>t.id===task.id)).toBe(true);expect((await json(request,`/api/schedules?date=${addDays(first,1)}`)).find(s=>s.id===plan.id).blocks.some(b=>b.task_id===task.id)).toBe(false);
 await selectedWeek(page,second);await expect(taskCard(page,title)).toBeVisible();await libraryTab(page);await expect(taskCard(page,title)).toBeVisible();await page.reload();await nav(page);await weekTab(page);await selectedWeek(page,first);await page.getByLabel('Filter tasks by status',{exact:true}).selectOption('all');await expect(taskCard(page,title)).toHaveCount(0);
});

test('stop repeating keeps prior completion and suppresses already materialized future work',async({page,request})=>{
 test.setTimeout(180000);const past=sundayOf('2022-02-08'),cutoff=sundayOf('2050-02-08'),title='QA Lifecycle stop future rhythm';
 const task=await json(request,'/api/task-definitions','post',{title,session_minutes:10,min_sessions_per_week:1,max_sessions_per_day:1,importance:10,difficulty:0,recurrence:{start_week:past}});
 const history=await completedPlan(request,addDays(past,1),task);await json(request,'/api/schedules/generate','post',{date:addDays(cutoff,1)});const before=(await week(request,past)).assignments.find(a=>a.task_definition_id===task.id);expect(before.completed_minutes).toBeGreaterThan(0);
 await page.goto('/');await nav(page);await weekTab(page);await selectedWeek(page,cutoff);await page.locator('[aria-label="Task views"]').getByRole('button',{name:/^Every Week/}).click();await taskCard(page,title).getByRole('button',{name:'Stop repeating',exact:true}).click();await expect(page.getByRole('dialog')).toContainText(title);await page.getByRole('dialog').getByLabel('First week without repeating work',{exact:true}).fill(cutoff);await page.getByRole('dialog').getByRole('button',{name:'Stop repeating',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
 const saved=(await state(request)).task_definitions.find(t=>t.id===task.id);expect(saved).toBeTruthy();expect(saved.recurrence.stopped_from_week).toBe(cutoff);expect((await week(request,past)).assignments.find(a=>a.task_definition_id===task.id).completed_minutes).toBe(before.completed_minutes);expect((await json(request,'/api/schedules')).find(s=>s.id===history.id).blocks.some(b=>b.task_id===task.id&&b.status==='completed')).toBe(true);
 for(const date of [cutoff,addDays(cutoff,7)]){expect((await week(request,date)).assignments.some(a=>a.task_definition_id===task.id)).toBe(false);const generated=await json(request,'/api/schedules/generate','post',{date:addDays(date,1)});expect(generated.blocks.some(b=>b.task_id===task.id)).toBe(false)}
 await page.reload();await nav(page);await libraryTab(page);await expect(taskCard(page,title)).toBeVisible();
});
