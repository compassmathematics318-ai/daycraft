import {test,expect} from '@playwright/test';

const date='2026-11-13';
const endpoint='/api/schedules/generate';
const payload={date,mode:'balanced',reoptimize:false,include_inactive_projects:false};
async function openDay(page){
 await page.goto('/');
 await page.getByLabel('Planning date',{exact:true}).fill(date);
 await expect(page.getByRole('combobox',{name:'Workload Level',exact:true})).toBeEnabled();
}
async function chooseWorkload(page,request,level){
 await page.getByRole('combobox',{name:'Workload Level',exact:true}).selectOption(level);
 await expect.poll(async()=>(await (await request.get(`/api/day-preferences/${date}`)).json()).workload_level).toBe(level);
 await expect(page.getByRole('combobox',{name:'Workload Level',exact:true})).toBeEnabled();
}
const generationButton=page=>page.getByRole('button',{name:/^(Generate (my day|my schedule|schedule)|Reoptimize day)$/i}).first();

test('real generation succeeds for all five persisted workloads on copied personal data',async({page,request},testInfo)=>{
 test.setTimeout(240000);
 for(const level of ['very_low','low','medium','high','very_high']){
  await openDay(page);await chooseWorkload(page,request,level);
  const before=await (await request.get(`/api/schedules?date=${date}`)).json();
  const responsePromise=page.waitForResponse(response=>response.url().endsWith(endpoint)&&response.request().method()==='POST',{timeout:45000});
  await generationButton(page).click();const response=await responsePromise;
  const sent=response.request().postDataJSON(),body=await response.text();
  const expectedMode=before[0]?.mode??'balanced';
  await testInfo.attach('real-generation-response',{body:JSON.stringify({level,request:sent,status:response.status(),response:response.ok()?{solver_status:JSON.parse(body).solver_status,status:JSON.parse(body).status}:body},null,2),contentType:'application/json'});
  expect(sent).toEqual({...payload,mode:expectedMode});
  expect(sent).not.toHaveProperty('workload_level');
  if(!response.ok()){
   expect(await (await request.get(`/api/schedules?date=${date}`)).json()).toEqual(before);
   await expect(page.getByRole('alert')).toContainText(/Application Control/i);
   const retryResponsePromise=page.waitForResponse(item=>item.url().endsWith(endpoint)&&item.request().method()==='POST',{timeout:45000});
   await page.getByRole('alert').getByRole('button',{name:'Retry generation',exact:true}).click();
   const retryResponse=await retryResponsePromise;
   expect(retryResponse.request().postDataJSON()).toEqual(sent);expect(retryResponse.status()).toBe(response.status());
   await expect(page.getByRole('alert')).toContainText(/Application Control/i);
   await testInfo.attach('actual-retry-response',{body:JSON.stringify({request:retryResponse.request().postDataJSON(),status:retryResponse.status(),response:await retryResponse.text()},null,2),contentType:'application/json'});
  }
  expect.soft(response.status(),`Real optimization required for ${level}: ${body}`).toBe(200);
  if(!response.ok())continue;
  const plan=JSON.parse(body);expect(['OPTIMAL','FEASIBLE']).toContain(plan.solver_status);
  expect(['optimal','feasible','partial']).toContain(plan.status);expect(plan.conflicts).toEqual([]);
  expect((await (await request.get(`/api/schedules?date=${date}`)).json())[0].id).toBe(plan.id);
  if(level==='medium'){
   await expect(page.getByRole('button',{name:'Reoptimize day',exact:true})).toBeEnabled();
   await expect(page.getByRole('combobox',{name:'Workload Level',exact:true})).toHaveValue('medium');
   await expect(page.getByLabel('Planning date',{exact:true})).toHaveValue(date);
   await expect(page.locator('.timeline-block').first()).toBeVisible();
   await testInfo.attach('november-13-medium-generated-plan',{body:await page.screenshot({fullPage:true,animations:'disabled'}),contentType:'image/png'});
  }
 }
});

test('unavailable generation keeps the error visible and Retry repeats the same POST',async({page,request},testInfo)=>{
 // Only the unavailable dependency response is simulated; no generated plan or solver success is fabricated.
 const requests=[];
 await page.route(`**${endpoint}`,async route=>{
  requests.push(route.request().postDataJSON());
  await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'The schedule optimizer is unavailable because Windows Application Control blocked a required dependency. Your saved data has not changed.'})});
 });
 await openDay(page);await chooseWorkload(page,request,'high');
 await generationButton(page).click();
 await expect(page.getByRole('alert')).toContainText(/optimizer.*unavailable/i);
 await expect(page.getByRole('alert')).toContainText(/saved data.*not changed/i);
 await page.getByRole('alert').getByRole('button',{name:'Retry generation',exact:true}).click();
 await expect.poll(()=>requests.length).toBe(2);
 expect(requests[0]).toEqual(payload);expect(requests[1]).toEqual(requests[0]);
 await expect(page.getByRole('alert')).toContainText(/optimizer.*unavailable/i);
 await expect(page.getByText('Your schedule is ready.',{exact:true})).toHaveCount(0);
 await testInfo.attach('retry-request-bodies',{body:JSON.stringify(requests,null,2),contentType:'application/json'});
});
