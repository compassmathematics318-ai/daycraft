import {test,expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs/promises';
import {taskForm,taskCard,weekTab} from '../task-helpers.js';
import {chooseLocation} from '../location-helpers.js';

async function state(request){const r=await request.get('/api/state');expect(r.ok()).toBeTruthy();return r.json()}
async function nav(page,text){const item=page.locator('.nav-item').filter({hasText:text}).first();const toggle=page.getByRole('button',{name:'Open navigation',exact:true});if(await toggle.isVisible()&&!await page.locator('.sidebar').evaluate(el=>el.classList.contains('open')))await toggle.click();await item.click()}
async function saved(page,request,collection,title){await expect.poll(async()=>((await state(request))[collection]).some(x=>(x.title??x.name)===title)).toBe(true);await expect(page.getByRole('dialog')).toHaveCount(0)}
async function noOverflow(page){expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBe(true)}
async function screenshot(page,name){await fs.mkdir('../test-results/screenshots',{recursive:true});await page.screenshot({path:`../test-results/screenshots/${name}.png`,fullPage:true,animations:'disabled'})}
async function audit(page,name){const results=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();await fs.mkdir('../test-results/accessibility',{recursive:true});await fs.writeFile(`../test-results/accessibility/${name}.json`,JSON.stringify(results,null,2));expect(results.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>n.target)}))).toEqual([])}

test('persisted planner workflow, travel, exports, themes and responsive screens',async({page,request})=>{
 test.setTimeout(240000);
 const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 // Exercise map selection without sending automated tile requests to public servers.
 await page.route('https://tile.openstreetmap.org/**',route=>route.fulfill({status:200,contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j85sAAAAASUVORK5CYII=','base64')}));
 await page.goto('/');
 await expect(page.getByRole('button',{name:/Generate My Schedule/i})).toBeVisible();
 const selectedDate=await page.locator('input[type=date]').first().inputValue();

 await nav(page,'Locations & map');
 await page.locator('summary').filter({hasText:'Saved places and walking routes'}).click();
 await page.locator('.location-manager .leaflet-container').click({position:{x:300,y:200}});
 await page.getByLabel('Location name',{exact:true}).fill('QA Home');
 await page.getByRole('button',{name:'Save location',exact:true}).click();
 await expect.poll(async()=>(await state(request)).locations.length).toBe(1);await expect(page.getByRole('button',{name:'Save location',exact:true})).toBeEnabled();await expect(page.getByLabel('Location name',{exact:true})).toHaveValue('');
 await page.getByLabel('Location name',{exact:true}).fill('QA Library');
 await page.getByLabel('Latitude',{exact:true}).fill('43.469');
 await page.getByLabel('Longitude',{exact:true}).fill('-80.542');
 await page.getByRole('button',{name:'Save location',exact:true}).click();
 await expect.poll(async()=>(await state(request)).locations.length).toBe(2);await expect(page.getByRole('button',{name:'Save location',exact:true})).toBeEnabled();
 const locations=(await state(request)).locations;
 const home=locations.find(x=>x.name==='QA Home'),library=locations.find(x=>x.name==='QA Library');
 await page.getByRole('combobox',{name:'From',exact:true}).selectOption(home.id);
 await page.getByRole('combobox',{name:'To',exact:true}).selectOption(library.id);
 await page.getByRole('button',{name:'Get route',exact:true}).click();
 await expect(page.getByText(/Estimated fallback/)).toBeVisible();
 await page.getByRole('spinbutton',{name:/^Manual walking time/}).fill('15');
 await page.getByRole('button',{name:'Save override',exact:true}).click();
 await expect.poll(async()=>(await state(request)).locations.find(x=>x.id===home.id).travel_overrides[library.id]).toBe(15);
 await screenshot(page,'locations-map-offline-tiles');
 await chooseLocation(page,page.locator('.location-overview'),{id:home.id,label:'Home / Starting Location'});
 await expect.poll(async()=>(await state(request)).settings.home_location_id).toBe(home.id);
 await page.getByLabel('Start my day at Home',{exact:true}).click();
 await expect.poll(async()=>(await state(request)).settings.start_at_home).toBe(true);

 await nav(page,'Preferences');
 await page.getByRole('combobox',{name:'Start / default location',exact:true}).selectOption(home.id);
 await page.getByLabel('Focus session (min)',{exact:true}).fill('45');
 await page.getByRole('button',{name:'Save preferences',exact:true}).click();
 await expect.poll(async()=>(await state(request)).settings.focus_minutes).toBe(45);

 await nav(page,'Classes, Commitments & Assessments');
 await page.locator('.block-library').getByRole('button',{name:'Create Block',exact:true}).click();
 await page.getByLabel('Block name',{exact:true}).fill('QA Algorithms');
 await chooseLocation(page,page.getByRole('dialog'),{id:library.id});
 await page.getByRole('button',{name:'Save block',exact:true}).click();
 await saved(page,request,'activities','QA Algorithms');
 await page.getByRole('button',{name:'Edit block QA Algorithms',exact:true}).click();
 await page.getByLabel(/^Room Number/).fill('201');
 await page.getByLabel('Description',{exact:true}).fill('Algorithms lecture, saved through the reusable block editor.');
 await page.getByRole('button',{name:'Save block',exact:true}).click();
 await expect(page.getByRole('dialog')).toHaveCount(0);
 expect((await state(request)).activities.find(a=>a.title==='QA Algorithms').room).toBe('201');
 if(!await page.locator(`[data-testid="calendar-day"][data-date="${selectedDate}"]`).count())await page.getByRole('button',{name:'Next Week',exact:true}).click();
 await page.getByRole('button',{name:'Schedule QA Algorithms',exact:true}).click();
 const placementDate=page.getByRole('dialog').getByRole('combobox',{name:'Date',exact:true});
 if(await placementDate.evaluate(e=>e.tagName)==='SELECT')await placementDate.selectOption(selectedDate);else await placementDate.fill(selectedDate);
 await page.getByLabel('Start time',{exact:true}).fill('09:00');
 await page.getByLabel('End time',{exact:true}).fill('10:00');
 await page.getByRole('button',{name:'Save placement',exact:true}).click();
 await expect(page.getByRole('dialog')).toHaveCount(0);

 await nav(page,'Tasks & deadlines');await weekTab(page);
 // Tomorrow may start a different Sunday-based week from today's task view.
 // Select the actual planning week before creating its weekly assignments.
 await page.getByLabel('Task week date',{exact:true}).fill(selectedDate);
 await expect(page.locator('.task-week-loading')).toHaveCount(0);
 await page.getByRole('button',{name:/Add task/i}).first().click();
 await taskForm(page,{title:'QA Assignment',minutes:90,type:'academic',week:selectedDate,deadline:`${selectedDate}T16:00`,split:true,minChunk:45,importance:1,locationId:library.id});
 await page.getByRole('button',{name:'Save task',exact:true}).click();
 await saved(page,request,'tasks','QA Assignment');
 await page.getByRole('button',{name:'Edit QA Assignment',exact:true}).click();
 await page.getByLabel(/^Description/).fill('Saved through the actual edit dialog.');
 await page.getByRole('button',{name:'Save task',exact:true}).click();
 await expect(page.getByRole('dialog')).toHaveCount(0);

 await nav(page,'Personal projects');
 await page.getByRole('button',{name:/New project/i}).first().click();
 await page.getByLabel('Project name (required)',{exact:true}).fill('QA Portfolio');
 await expect(page.getByLabel('Estimated minutes',{exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'Save project',exact:true}).click();
 await saved(page,request,'projects','QA Portfolio');
 await page.getByRole('button',{name:'QA Portfolio',exact:true}).click();
 await page.getByRole('button',{name:'Add linked task',exact:true}).click();
 await taskForm(page,{title:'QA Portfolio work',minutes:45,week:selectedDate,importance:1,deadline:`${selectedDate}T22:00`});
 await page.getByRole('button',{name:'Save task',exact:true}).click();
 await saved(page,request,'tasks','QA Portfolio work');
 await page.getByRole('button',{name:'New project',exact:true}).first().click();
 await page.getByLabel('Project name (required)',{exact:true}).fill('QA Temporary');
 await page.getByRole('button',{name:'Save project',exact:true}).click();
 await saved(page,request,'projects','QA Temporary');
 await page.getByRole('button',{name:'Delete QA Temporary',exact:true}).click();
 await page.getByRole('dialog').getByRole('button',{name:'Delete',exact:true}).click();
 await expect.poll(async()=>(await state(request)).projects.some(t=>t.name==='QA Temporary')).toBe(false);
 await expect(page.getByRole('dialog')).toHaveCount(0);
 await nav(page,'Overview');
 await page.getByRole('button',{name:/Generate My Schedule/i}).click();
 await expect.poll(async()=>(await state(request)).schedules.length,{timeout:30000}).toBe(1);
 let schedule=(await state(request)).schedules[0];
 expect(['optimal','feasible','partial']).toContain(schedule.status);
 expect(schedule.conflicts).toEqual([]);
 expect(schedule.blocks.some(b=>b.kind==='travel')).toBe(true);
 const assignment=(await state(request)).tasks.find(t=>t.title==='QA Assignment');
 expect(schedule.blocks.filter(b=>b.task_id===assignment.id).every(b=>new Date(b.end)<=new Date(assignment.deadline))).toBe(true);
 await screenshot(page,'planner-initial');
 const [calendarDownload]=await Promise.all([page.waitForEvent('download'),page.getByRole('link',{name:'ICS',exact:true}).click()]);
 await fs.mkdir('../test-results/downloads',{recursive:true});
 await calendarDownload.saveAs('../test-results/downloads/schedule.ics');
 expect(await fs.readFile('../test-results/downloads/schedule.ics','utf8')).toContain('BEGIN:VCALENDAR');

 // Inspector actions use the actual saved solver blocks rather than fabricated schedules.
 const academic=schedule.blocks.find(b=>b.kind==='task');
 const beforeCompletion=(await state(request)).tasks.find(t=>t.id===academic.task_id).remaining_minutes;
 await page.locator('.timeline-block.task').first().click();
 await page.getByLabel('Keep this activity in place',{exact:true}).check();
 await page.getByRole('button',{name:'Save & validate',exact:true}).click();
 await expect(page.getByRole('dialog')).toHaveCount(0);
 await page.getByRole('button',{name:'Reoptimize day',exact:true}).click();await expect(page.getByRole('button',{name:'Reoptimize day',exact:true})).toBeEnabled({timeout:30000});
 await expect.poll(async()=>((await state(request)).schedules[0].blocks.find(b=>b.id===academic.id)?.locked),{timeout:30000}).toBe(true);
 schedule=(await state(request)).schedules[0];
 expect(schedule.blocks.find(b=>b.id===academic.id).start).toBe(academic.start);
 await page.locator('.timeline-block.task').filter({hasText:'QA Assignment'}).first().click();
 await expect(page.getByRole('button',{name:'Mark Session Completed',exact:true})).toBeDisabled();
 const premature=await request.post(`/api/schedules/${schedule.id}/blocks/${academic.id}/completion`,{data:{completed:true}});expect(premature.status()).toBe(409);
 await page.getByRole('button',{name:'Cancel',exact:true}).click();
 await expect(page.getByRole('dialog')).toHaveCount(0);
 const remaining=(await state(request)).tasks.find(t=>t.id===assignment.id).remaining_minutes;
 expect(remaining).toBe(beforeCompletion);
 await page.getByRole('button',{name:'Reoptimize day',exact:true}).click();
 await expect(page.getByRole('button',{name:'Reoptimize day',exact:true})).toBeEnabled({timeout:30000});
 expect((await state(request)).schedules[0].blocks.find(b=>b.id===academic.id).status).toBe(academic.status);
 const projectBlock=(await state(request)).schedules[0].blocks.find(b=>b.kind==='project');
 expect(projectBlock,'The explicitly due project session should be allocated before manual-edit verification').toBeTruthy();
 const movePlan=(await state(request)).schedules[0];
 const moveOffset=projectBlock.start.match(/([+-]\d{2}:\d{2}|Z)$/)[1];
 const candidateMinutes=[1200,...Array.from({length:64},(_,i)=>16*60+i*5)];
 const moveMinute=candidateMinutes.find(minute=>{const start=Date.parse(`${selectedDate}T${String(Math.floor(minute/60)).padStart(2,'0')}:${String(minute%60).padStart(2,'0')}:00${moveOffset}`),end=start+45*60000;return movePlan.blocks.filter(b=>b.id!==projectBlock.id).every(b=>end+30*60000<=Date.parse(b.start)||start>=Date.parse(b.end)+30*60000)});
 expect(moveMinute,'A verified free 45-minute gap with travel/recovery margin').toBeDefined();
 const moveStart=`${String(Math.floor(moveMinute/60)).padStart(2,'0')}:${String(moveMinute%60).padStart(2,'0')}`,moveEnd=`${String(Math.floor((moveMinute+45)/60)).padStart(2,'0')}:${String((moveMinute+45)%60).padStart(2,'0')}`;
 await page.locator('.timeline-block.project').first().click();
 await page.getByLabel(/^Start \(/).fill(`${selectedDate}T09:00`);
 await page.getByLabel('End',{exact:true}).fill(`${selectedDate}T09:45`);
 await page.getByRole('button',{name:'Save & validate',exact:true}).click();
 await expect(page.getByRole('alert')).toBeVisible();
 await expect(page.getByRole('dialog')).toBeVisible();
 await page.getByLabel(/^Start \(/).fill(`${selectedDate}T${moveStart}`);
 await page.getByLabel('End',{exact:true}).fill(`${selectedDate}T${moveEnd}`);
 await page.getByRole('button',{name:'Save & validate',exact:true}).click();
 await expect(page.getByRole('dialog')).toHaveCount(0);
 await expect.poll(async()=>new Date((await state(request)).schedules[0].blocks.find(b=>b.id===projectBlock.id).start).toLocaleTimeString('en-GB',{timeZone:'America/Toronto',hour12:false})===`${moveStart}:00`).toBe(true);
 await page.reload();
 await expect.poll(async()=>(await state(request)).tasks.length).toBe(2);
 await noOverflow(page);
 for(const theme of ['light','dark','midnight','warm']){
   await page.setViewportSize({width:1440,height:1000});
   await page.getByLabel('Theme',{exact:true}).selectOption(theme);
   await expect(page.locator('html')).toHaveAttribute('data-theme',theme);
   await expect.poll(async()=>(await state(request)).settings.theme).toBe(theme);
   await noOverflow(page);await screenshot(page,`desktop-${theme}`);await audit(page,`desktop-${theme}`);
   await nav(page,'Daily planner');await screenshot(page,`planner-${theme}`);await audit(page,`planner-${theme}`);
   await page.setViewportSize({width:390,height:844});
   await noOverflow(page);await screenshot(page,`mobile-${theme}`);await audit(page,`mobile-${theme}`);
   await nav(page,'Overview');
 }
 await page.reload();await expect(page.getByLabel('Theme',{exact:true})).toHaveValue('warm');
 await page.setViewportSize({width:768,height:1024});await noOverflow(page);await screenshot(page,'tablet-warm');
 for(const screen of ['Classes','Tasks & deadlines','Personal projects','Preferences']){await nav(page,screen);await noOverflow(page)}
 await nav(page,'Tasks & deadlines');await weekTab(page);
 await weekTab(page);await page.getByLabel('Task week date',{exact:true}).fill(selectedDate);
 await page.getByRole('combobox',{name:'Filter tasks by status',exact:true}).selectOption('all');
 await expect(taskCard(page,'QA Assignment').getByRole('button',{name:'Log completed session',exact:true})).toHaveCount(0);
 await taskCard(page,'QA Assignment').getByRole('button',{name:'Adjust this week',exact:true}).click();
 await page.getByRole('dialog').locator('summary').click();
 await page.getByRole('dialog').getByLabel('Week notes',{exact:true}).fill('QA task edit invalidates saved planning.');
 await page.getByRole('button',{name:'Save this week',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
 await nav(page,'Daily planner');
 await expect(page.locator('.calendar-stale-note')).toContainText('task');
 await page.getByRole('button',{name:'Reoptimize day',exact:true}).click();await expect(page.getByRole('button',{name:'Reoptimize day',exact:true})).toBeEnabled({timeout:30000});
 await page.locator('.timeline-block.project').first().click();
 await page.getByRole('button',{name:'Save & validate',exact:true}).click();
 await expect(page.getByRole('dialog')).toHaveCount(0);
 expect(errors).toEqual([]);
 const csv=await request.get(`/api/schedules/${schedule.id}/export?format=csv`);
 expect(csv.ok()).toBeTruthy();expect(await csv.text()).toContain('QA Assignment');
 const ics=await request.get(`/api/schedules/${schedule.id}/export?format=ics`);
 expect(ics.ok()).toBeTruthy();expect(await ics.text()).toContain('BEGIN:VCALENDAR');
 // Remove only this workflow's QA placement so fixed-date calendar fixtures
 // do not depend on the real date used by the tomorrow selector.
 const leadWorkspaceActivity=(await state(request)).activities.find(a=>a.title==='QA Algorithms');
 if(leadWorkspaceActivity){
   const leadWorkspaceWeek=await request.get(`/api/calendar?week_start=${selectedDate}`);
   expect(leadWorkspaceWeek.ok()).toBeTruthy();
   for(const occurrence of (await leadWorkspaceWeek.json()).occurrences.filter(o=>o.activity_id===leadWorkspaceActivity.id)){
     const removed=await request.delete(`/api/occurrences/${occurrence.id}`);expect(removed.ok()).toBeTruthy();
   }
 }

 const finalSettings=(await state(request)).settings;
 const resetHome=await request.put('/api/settings',{data:{...finalSettings,home_location_id:null,start_at_home:false,end_at_home:false}});
 expect(resetHome.ok()).toBeTruthy();
});








