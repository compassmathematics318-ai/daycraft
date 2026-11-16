import {expect} from '@playwright/test';
import {chooseLocation} from './location-helpers.js';

export function sundayOf(value){const d=new Date(`${value}T12:00:00Z`);d.setUTCDate(d.getUTCDate()-d.getUTCDay());return d.toISOString().slice(0,10)}
export function addDays(value,n){const d=new Date(`${value}T12:00:00Z`);d.setUTCDate(d.getUTCDate()+n);return d.toISOString().slice(0,10)}
export async function taskForm(page,{title,minutes,type='project_work',week,minimum=1,deadline,projectId,description,split=false,minChunk,importance,locationId}){
 const dialog=page.getByRole('dialog');
 await dialog.getByLabel('Task name',{exact:true}).fill(title);
 await dialog.getByRole('combobox',{name:'Task type',exact:true}).selectOption(type);
 await dialog.getByLabel(/^Session length \(minutes\)/).fill(String(minutes));
 if(projectId!==undefined)await chooseRelated(page,'project',projectId);
 if(week){const assign=dialog.getByLabel('Assign to a selected week',{exact:true});if(await assign.count())await assign.check();const date=dialog.getByLabel(/^Selected week/);if(await date.count()){if(await date.isEnabled())await date.fill(sundayOf(week));else await expect(date).toHaveValue(sundayOf(week))}else await expect(dialog.getByText(/Work for /)).toBeVisible()}
 await dialog.getByLabel(/^(Minimum sessions (this week|per week|for selected week|each week)|Default minimum sessions when assigned to a week)/).fill(String(minimum));
 await dialog.getByLabel('Allow a session to be split into smaller chunks',{exact:true}).setChecked(split);
 if(split&&minChunk!==undefined)await dialog.getByLabel(/^Minimum chunk length/).fill(String(minChunk));
 if(importance!==undefined){const slider=dialog.getByRole('slider',{name:'Importance',exact:true});await slider.press('Home');for(let i=0;i<(importance-1)*2;i++)await slider.press('ArrowRight')}
 if(deadline){if(type==='academic'){await dialog.getByRole('combobox',{name:'Academic subtype',exact:true}).selectOption('assignment');await dialog.getByLabel(/^Due date \(/).fill(deadline)}else await dialog.getByLabel(/^Deadline \(/).fill(deadline)}
 if(description!==undefined)await dialog.getByLabel(/^Description/).fill(description);
 if(locationId!==undefined){await dialog.locator('summary').filter({hasText:'Advanced options'}).click();await chooseLocation(page,dialog,{id:locationId,label:'Work location'})}
}
export const taskCard=(page,title)=>page.locator('.intelligent-task-card').filter({has:page.getByRole('button',{name:title,exact:true})});
export async function chooseRelated(page,kind,id){const dialog=page.getByRole('dialog'),picker=dialog.getByRole('combobox',{name:'Related class, assessment, commitment, or project (optional)',exact:true});await picker.fill(id);await dialog.getByRole('option').and(dialog.getByTitle(`${kind} ID ${id}`,{exact:true})).click();await expect(dialog.locator('.related-entity-selected').getByTitle(`${kind} ID ${id}`,{exact:true})).toBeVisible()}
export async function expectNoRelatedResults(page){const dialog=page.getByRole('dialog'),picker=dialog.getByRole('combobox',{name:'Related class, assessment, commitment, or project (optional)',exact:true}),selected=dialog.locator('.related-entity-selected > span');const before=await selected.evaluateAll(items=>items.map(item=>item.getAttribute('title')));await picker.fill('QA no matching entity f9d3b1377c');const list=dialog.getByRole('listbox',{name:'Existing related entities'}),empty=list.getByRole('option',{name:'No matching entities.',exact:true});await expect(list.getByRole('option')).toHaveCount(1);await expect(empty).toHaveAttribute('aria-disabled','true');await expect(empty).toHaveAttribute('aria-selected','false');await picker.press('ArrowDown');await picker.press('Enter');await expect(picker).toHaveAttribute('aria-expanded','true');expect(await selected.evaluateAll(items=>items.map(item=>item.getAttribute('title')))).toEqual(before);await expect(dialog).toBeVisible()}
export async function weekTab(page){await page.locator('.task-view-tabs .segmented').getByRole('button',{name:/^Week Specific/}).click()}
export async function libraryTab(page){await page.getByRole('button',{name:/^Task Library/}).click()}


// Complete real generated blocks through the daily planner; never invent task-card credit.
export async function completePlannedSessions(page,request,date,taskId,count=1){
 const generated=await request.post('/api/schedules/generate',{data:{date},timeout:45000});expect(generated.ok(),await generated.text()).toBeTruthy();const plan=await generated.json();
 const sessions=[...new Set(plan.blocks.filter(b=>b.task_id===taskId&&b.status!=='completed').map(b=>b.logical_session_id))].slice(0,count);expect(sessions).toHaveLength(count);
 await page.reload();
 const nav=async text=>{const toggle=page.getByRole('button',{name:'Open navigation',exact:true});if(await toggle.isVisible()&&!await page.locator('.sidebar').evaluate(e=>e.classList.contains('open')))await toggle.click();await page.locator('.nav-item').filter({hasText:text}).first().click()};
 await nav('Overview');await page.getByLabel('Planning date',{exact:true}).fill(date);await nav('Daily planner');
 for(const session of sessions)for(const block of plan.blocks.filter(b=>b.logical_session_id===session&&b.task_id===taskId)){
  expect(Date.parse(block.end),'Completion fixtures must use genuinely elapsed server time').toBeLessThanOrEqual(Date.now());
  await page.locator('.timeline-block').filter({hasText:block.title}).filter({hasText:new RegExp('.*')}).nth(plan.blocks.filter(b=>b.task_id===taskId&&b.title===block.title).findIndex(b=>b.id===block.id)).click();
  await page.getByRole('button',{name:'Mark Session Completed',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
 }
 await nav('Tasks & deadlines');await weekTab(page);await page.getByLabel('Task week date',{exact:true}).fill(sundayOf(date));await expect(page.locator('.task-week-loading')).toHaveCount(0);
}
