import {test,expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs/promises';

const addDays=(value,n)=>{const d=new Date(`${value}T12:00:00Z`);d.setUTCDate(d.getUTCDate()+n);return d.toISOString().slice(0,10)};
async function json(request,path,method='get',data){const r=await request[method](path,{data,...(path.includes('/schedules/generate')?{timeout:45000}:{})});expect(r.ok(),await r.text()).toBeTruthy();return r.status()===204?null:r.json()}
async function nav(page,text){const toggle=page.getByRole('button',{name:'Open navigation',exact:true});if(await toggle.isVisible()&&!await page.locator('.sidebar').evaluate(e=>e.classList.contains('open')))await toggle.click();await page.locator('.nav-item').filter({hasText:text}).first().click()}
async function setDateField(field,date){if(await field.evaluate(e=>e.tagName)==='SELECT')await field.selectOption(date);else await field.fill(date)}
async function calendar(request,week){return json(request,`/api/calendar?week_start=${week}`)}
async function create(page,{name,type='class',subtype,description='Calendar QA context',startDate,endDate,start,end,course}){
 await page.locator('.block-library').getByRole('button',{name:'Create Block',exact:true}).click();
 const dialog=page.getByRole('dialog');
 await dialog.getByRole('radio',{name:type.charAt(0).toUpperCase()+type.slice(1),exact:true}).check();
 await dialog.getByLabel('Block name',{exact:true}).fill(name);
 await dialog.getByRole('textbox',{name:'Description',exact:true}).fill(description);
 if(type==='class'){
  await expect(dialog.getByRole('combobox',{name:'Class subtype',exact:true})).toBeVisible();
  await expect(dialog.getByLabel(/^Starts \(/)).toHaveCount(0);
  if(subtype)await dialog.getByRole('combobox',{name:'Class subtype',exact:true}).selectOption(subtype);
 }
 if(type==='commitment'){
  await expect(dialog.getByRole('combobox',{name:'Commitment type',exact:true})).toBeVisible();
  await expect(dialog.getByRole('combobox',{name:'Class subtype',exact:true})).toHaveCount(0);
  if(subtype)await dialog.getByRole('combobox',{name:'Commitment type',exact:true}).selectOption(subtype);
 }
 if(type==='assessment'){
  await expect(dialog.getByRole('combobox',{name:'Class subtype',exact:true})).toHaveCount(0);
  await dialog.getByLabel(/^Starts \(/).fill(start);
  await dialog.getByLabel(/^Ends \(/).fill(end);
  if(course)await dialog.getByLabel('Course association',{exact:true}).fill(course);
 }
 if(startDate)await dialog.getByLabel(/^Start date/).fill(startDate);
 if(endDate)await dialog.getByLabel(/^End date/).fill(endDate);
 await dialog.getByRole('button',{name:'Save block',exact:true}).click();
 await expect(dialog).toHaveCount(0);
}
async function schedule(page,name,date,start,end){
 await page.getByRole('button',{name:`Schedule ${name}`,exact:true}).click();
 await setDateField(page.getByRole('dialog').getByRole('combobox',{name:'Date',exact:true}),date);
 await page.getByLabel('Start time',{exact:true}).fill(start);
 await page.getByLabel('End time',{exact:true}).fill(end);
 await page.getByRole('button',{name:'Save placement',exact:true}).click();
 await expect(page.getByRole('dialog')).toHaveCount(0);
}
async function dragToMinute(page,source,date,minute,{valid=true}={}){
 const day=page.locator(`[data-testid="calendar-day"][data-date="${date}"]`);
 await page.getByTestId('calendar-scroll').evaluate((e,minute)=>{e.scrollTop=Math.max(0,minute-200)},minute);
 await source.scrollIntoViewIfNeeded();
 const a=await source.boundingBox(),b=await day.boundingBox();expect(a&&b).toBeTruthy();
 const offset=await source.getAttribute('data-testid')==='calendar-event'?10:0;
 const to={x:b.x+b.width/2,y:b.y+minute+offset};
 expect(a.y).toBeGreaterThanOrEqual(0);expect(a.y+a.height).toBeLessThanOrEqual(page.viewportSize().height);
 expect(to.y).toBeGreaterThan(0);expect(to.y).toBeLessThan(page.viewportSize().height);
 await page.mouse.move(a.x+a.width/2,a.y+10);await page.mouse.down();
 await page.mouse.move(a.x+a.width/2+10,a.y+10,{steps:4});
 await page.mouse.move(to.x,to.y,{steps:20});await page.mouse.move(to.x,to.y);
 await expect(page.getByTestId('drag-preview')).toBeVisible();
 if(valid)await expect(page.getByTestId('drag-preview')).not.toHaveClass(/invalid/);
 else await expect(page.getByTestId('drag-preview')).toHaveClass(/invalid/);
 await page.mouse.up();
}
async function captureAudit(page,name){
 await fs.mkdir('../test-results/calendar-screenshots',{recursive:true});
 await page.screenshot({path:`../test-results/calendar-screenshots/${name}.png`,fullPage:true,animations:'disabled'});
 const result=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
 await fs.writeFile(`../test-results/calendar-screenshots/${name}.axe.json`,JSON.stringify(result.violations,null,2));
 expect(result.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}))).toEqual([]);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
}

test('library, real drag/move/resize, manual occurrences, copy weeks, assessments and themes',async({page,request})=>{
 test.setTimeout(240000);await page.setViewportSize({width:1600,height:1400});
 await page.clock.setFixedTime(new Date('2026-11-09T12:00:00Z'));
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/');await nav(page,'Classes, Commitments & Assessments');
 await expect(page.locator('.block-library').getByRole('button',{name:'Create Block',exact:true})).toBeVisible();
 const dayDates=await page.getByTestId('calendar-day').evaluateAll(els=>els.map(e=>e.dataset.date));
 expect(dayDates).toEqual(Array.from({length:7},(_,i)=>addDays('2026-11-08',i)));
 const week=dayDates[0],wed=dayDates[3],thu=dayDates[4],fri=dayDates[5],sat=dayDates[6];
 expect(new Date(`${week}T12:00:00Z`).getUTCDay()).toBe(0);
 await expect(page.locator('#week-title')).toHaveText('Nov 8–14, 2026');
 await expect(page.locator('.calendar-day-heading>span')).toHaveText(['Sun','Mon','Tue','Wed','Thu','Fri','Sat']);
 const className='QA Calendar MATH147',assessmentName='QA Calendar CS135 Midterm';let commitName='QA Calendar Reality Labs';

 await create(page,{name:className,type:'class',subtype:'Lecture',startDate:week,endDate:addDays(week,6),description:'Proof exercises and lecture discussion.'});
 let state=await json(request,'/api/state'),item=state.activities.find(a=>a.title===className);expect(item).toBeTruthy();
 const palette=page.getByTestId('block-palette'),chip=palette.locator(`[data-testid="palette-item"][data-activity-id="${item.id}"]`);
 await expect(chip).toBeVisible();await expect(chip).toContainText('Lecture');
 expect((await calendar(request,week)).occurrences.filter(o=>o.activity_id===item.id)).toHaveLength(0);
 await schedule(page,className,wed,'09:05','09:50');
 const manual=(await calendar(request,week)).occurrences.find(o=>o.activity_id===item.id);
 expect(manual.source).toBe('manual');expect(Date.parse(manual.end)-Date.parse(manual.start)).toBe(45*60000);

 // Both the palette and its target stay in view: no trip back to the Block Library.
 await page.setViewportSize({width:1440,height:1000});
 await page.locator('.weekly-calendar').evaluate(e=>e.scrollIntoView({block:'start'}));
 const adjacentScroll=await page.evaluate(()=>scrollY);
 await dragToMinute(page,chip,wed,10*60+30);
 expect(await page.evaluate(()=>scrollY)).toBe(adjacentScroll);
 await fs.mkdir('../test-results/calendar-screenshots',{recursive:true});
 await page.screenshot({path:'../test-results/calendar-screenshots/adjacent-palette-wednesday-1030.png',animations:'disabled'});
 await expect.poll(async()=>(await calendar(request,week)).occurrences.filter(o=>o.activity_id===item.id).length).toBe(2);
 const wednesday=(await calendar(request,week)).occurrences.find(o=>o.activity_id===item.id&&o.id!==manual.id);
 expect(Date.parse(wednesday.start)).toBe(Date.parse(`${wed}T10:30:00-05:00`));
 const viewportScroll=await page.evaluate(()=>scrollY);
 await dragToMinute(page,chip,fri,14*60+5);
 expect(await page.evaluate(()=>scrollY)).toBe(viewportScroll);
 await expect.poll(async()=>(await calendar(request,week)).occurrences.filter(o=>o.activity_id===item.id).length).toBe(3);
 let occurrences=(await calendar(request,week)).occurrences.filter(o=>o.activity_id===item.id);
 let dragged=occurrences.find(o=>o.id!==manual.id&&o.id!==wednesday.id);expect(dragged.source).toBe('manual');
 expect(Object.keys(dragged).sort()).toEqual(Object.keys(manual).sort());
 expect(Date.parse(dragged.end)-Date.parse(dragged.start)).toBe(60*60000);
 expect(Date.parse(dragged.start)).toBe(Date.parse(`${fri}T14:05:00-05:00`));
 expect(new Intl.DateTimeFormat('en-CA',{timeZone:'America/Toronto',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(dragged.start))).toBe('14:05');
 await dragToMinute(page,chip,wed,9*60+30,{valid:false});
 expect((await calendar(request,week)).occurrences.filter(o=>o.activity_id===item.id)).toHaveLength(3);
 await page.reload();await nav(page,'Classes, Commitments & Assessments');
 const reloaded=(await calendar(request,week)).occurrences.filter(o=>o.activity_id===item.id);
 expect(reloaded).toEqual(expect.arrayContaining([manual,wednesday,dragged]));
 expect((await json(request,'/api/state')).activities.filter(a=>a.title===className)).toHaveLength(1);
 await page.setViewportSize({width:1600,height:1400});

 let event=page.locator(`[data-testid="calendar-event"][data-occurrence-id="${dragged.id}"]`);
 await dragToMinute(page,event,thu,15*60+10);
 await expect.poll(async()=>Date.parse((await calendar(request,week)).occurrences.find(o=>o.id===dragged.id).start)).not.toBe(Date.parse(dragged.start));
 dragged=(await calendar(request,week)).occurrences.find(o=>o.id===dragged.id);
 expect(new Intl.DateTimeFormat('en-CA',{timeZone:'America/Toronto',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(dragged.start))).toBe('15:10');
 event=page.locator(`[data-testid="calendar-event"][data-occurrence-id="${dragged.id}"]`);
 await expect(event).toHaveCSS('top','910px');
 await expect(event).toHaveAttribute('draggable','true');
 await page.getByTestId('calendar-scroll').evaluate(e=>{e.scrollTop=12*60});
 await page.evaluate(()=>{window.__calendarResizeEvents=[];for(const name of ['pointerdown','pointermove','pointerup','pointercancel','dragstart','dragend'])document.addEventListener(name,e=>{if(e.target.closest?.('[data-testid="calendar-event"]'))window.__calendarResizeEvents.push({type:e.type,target:e.target.tagName,handle:!!e.target.closest('[data-testid="resize-handle"]'),x:e.clientX,y:e.clientY})},true)});
 const handle=await event.getByTestId('resize-handle').boundingBox();expect(handle).toBeTruthy();
 const resizeDay=await page.locator(`[data-testid="calendar-day"][data-date="${thu}"]`).boundingBox();
 await page.mouse.move(handle.x+handle.width/2,handle.y+handle.height/2);await page.mouse.down();
 // Regression: the seven-second success notification must not move the grid
 // underneath an active pointer gesture when it disappears.
 await page.waitForTimeout(7500);
 expect((await page.locator(`[data-testid="calendar-day"][data-date="${thu}"]`).boundingBox()).y).toBe(resizeDay.y);
 await page.mouse.move(handle.x+handle.width/2,resizeDay.y+16*60+23,{steps:10});await page.mouse.up();
 await fs.mkdir('../test-results/calendar-screenshots',{recursive:true});
 await fs.writeFile('../test-results/calendar-screenshots/resize-events.json',JSON.stringify(await page.evaluate(()=>window.__calendarResizeEvents),null,2));
 await expect.poll(async()=>Date.parse((await calendar(request,week)).occurrences.find(o=>o.id===dragged.id).end)-Date.parse(dragged.start)).toBe(75*60000);

 await create(page,{name:commitName,type:'commitment',subtype:'Groupwork',description:'Build and review the weekly prototype.'});
 const commitId=(await json(request,'/api/state')).activities.find(a=>a.title===commitName).id;
 await expect(palette.locator(`[data-activity-id="${commitId}"]`)).toContainText('Groupwork');
 await palette.getByRole('searchbox',{name:'Search reusable blocks',exact:true}).fill('MATH147');
 await expect(chip).toBeVisible();await expect(palette.locator(`[data-activity-id="${commitId}"]`)).toHaveCount(0);
 await palette.getByRole('searchbox',{name:'Search reusable blocks',exact:true}).fill('');
 await schedule(page,commitName,fri,'11:10','11:50');
 await schedule(page,commitName,dayDates[1],'17:05','17:35');
 await create(page,{name:assessmentName,type:'assessment',start:`${sat}T15:00`,end:`${sat}T16:00`,course:'CS135'});
 state=await json(request,'/api/state');const assessment=state.activities.find(a=>a.title===assessmentName);
 await expect(palette.locator(`[data-activity-id="${assessment.id}"]`)).toHaveCount(0);
 const assessmentEvent=page.locator(`[data-testid="calendar-event"][data-activity-id="${assessment.id}"]`);
 await expect(assessmentEvent).toHaveAttribute('draggable','false');
 await expect(assessmentEvent.getByTestId('resize-handle')).toHaveCount(0);
 expect((await calendar(request,week)).occurrences.filter(o=>o.activity_id===assessment.id)).toHaveLength(1);
 await page.getByRole('button',{name:`Edit block ${assessmentName}`,exact:true}).click();
 await page.getByLabel(/^Starts \(/).fill(`${sat}T15:05`);await page.getByLabel(/^Ends \(/).fill(`${sat}T16:05`);
 await page.getByRole('button',{name:'Save block',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
 expect((await calendar(request,week)).occurrences.filter(o=>o.activity_id===assessment.id)).toHaveLength(1);

 // A rejected manual overlap leaves both the library definition and old placements intact.
 await page.getByRole('button',{name:`Schedule ${className}`,exact:true}).click();
 await setDateField(page.getByRole('dialog').getByRole('combobox',{name:'Date',exact:true}),wed);
 await page.getByLabel('Start time',{exact:true}).fill('09:30');await page.getByLabel('End time',{exact:true}).fill('10:30');
 await page.getByRole('button',{name:'Save placement',exact:true}).click();await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible();
 expect((await calendar(request,week)).occurrences.filter(o=>o.activity_id===item.id)).toHaveLength(3);
 await page.getByRole('dialog').getByRole('button',{name:'Cancel',exact:true}).click();

 // Deleting one placement preserves the underlying reusable block and another meeting.
 await page.locator(`[data-testid="calendar-event"][data-occurrence-id="${manual.id}"]`).click();
 await page.getByRole('button',{name:'Delete placement',exact:true}).click();
 await expect.poll(async()=>(await calendar(request,week)).occurrences.some(o=>o.id===manual.id)).toBe(false);
 expect((await json(request,'/api/state')).activities.some(a=>a.id===item.id)).toBe(true);

 // Copying makes partial progress: one target is occupied, the bounded class cannot recur,
 // and one-time assessments are never duplicated.
 const targetWeek=addDays(week,7),commit=(await json(request,'/api/state')).activities.find(a=>a.title===commitName);
 const blocker=await json(request,'/api/activities','post',{title:'QA Calendar target blocker',category:'commitment',subtype:'Personal'});
 await json(request,'/api/occurrences','post',{activity_id:blocker.id,start:`${addDays(fri,7)}T11:10:00-05:00`,end:`${addDays(fri,7)}T11:30:00-05:00`});
 await page.getByRole('button',{name:'Next Week',exact:true}).click();
 await expect(page.locator(`[data-testid="calendar-day"][data-date="${targetWeek}"]`)).toHaveCount(1);
 await expect(page.getByRole('button',{name:'Copy Previous Week',exact:true})).toBeEnabled();
 await dragToMinute(page,chip,targetWeek,14*60,{valid:false});
 expect((await calendar(request,targetWeek)).occurrences.filter(o=>o.activity_id===item.id)).toHaveLength(0);
 await page.getByRole('button',{name:'Copy Previous Week',exact:true}).click();
 await expect.poll(async()=>(await calendar(request,targetWeek)).occurrences.filter(o=>o.activity_id===commit.id).length).toBe(1);
 let target=(await calendar(request,targetWeek)).occurrences;
 expect(target.some(o=>o.activity_id===blocker.id)).toBe(true);expect(target.some(o=>o.activity_id===assessment.id||o.activity_id===item.id)).toBe(false);
 const targetCount=target.length;await page.getByRole('button',{name:'Copy Previous Week',exact:true}).click();
 await expect(page.getByRole('button',{name:'Copy Previous Week',exact:true})).toBeEnabled();
 expect((await calendar(request,targetWeek)).occurrences).toHaveLength(targetCount);
 await page.getByRole('button',{name:'Previous Week',exact:true}).click();
 await page.reload();await nav(page,'Classes, Commitments & Assessments');
 expect((await calendar(request,week)).occurrences.some(o=>o.id===dragged.id)).toBe(true);
 await page.getByRole('button',{name:`Edit block ${commitName}`,exact:true}).click();
 commitName+=' Updated';await page.getByRole('textbox',{name:'Block name',exact:true}).fill(commitName);
 await page.getByRole('textbox',{name:'Description',exact:true}).fill('Updated groupwork context shared by every linked meeting.');
 await page.getByRole('button',{name:'Save block',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
 expect((await calendar(request,targetWeek)).activities.find(a=>a.id===commit.id).description).toContain('Updated groupwork');
 await expect(palette.locator(`[data-activity-id="${commit.id}"]`)).toContainText(commitName);
 expect((await calendar(request,week)).occurrences.find(o=>o.id===wednesday.id)).toEqual(wednesday);

 const generated=await json(request,'/api/schedules/generate','post',{date:sat,mode:'balanced'});
 const fixed=generated.blocks.find(b=>b.activity_id===assessment.id);expect(fixed).toBeTruthy();expect(fixed.category).toBe('assessment');expect(fixed.locked).toBe(true);expect(fixed.description).toBeTruthy();
 for(const theme of ['light','dark','midnight','warm']){
  await page.setViewportSize({width:1440,height:1000});await page.getByLabel('Theme',{exact:true}).selectOption(theme);await captureAudit(page,`calendar-desktop-${theme}`);
  await page.setViewportSize({width:390,height:844});await captureAudit(page,`calendar-mobile-${theme}`);
 }
 await page.setViewportSize({width:768,height:1024});await captureAudit(page,'calendar-tablet-warm');
 for(const name of [className,commitName,assessmentName]){
  await page.getByRole('button',{name:`Delete block ${name}`,exact:true}).click();
  await page.getByRole('dialog').getByRole('button',{name:'Delete block',exact:true}).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect((await json(request,'/api/state')).activities.some(a=>a.title===name)).toBe(false);
  await expect(palette.getByTestId('palette-item').filter({hasText:name})).toHaveCount(0);
 }
 expect((await calendar(request,week)).occurrences.some(o=>[item.id,commit.id,assessment.id].includes(o.activity_id))).toBe(false);
 expect(errors).toEqual([]);
});

test('assessment description edits preserve the second occurrence of a DST repeated hour',async({page,request})=>{
 const item=await json(request,'/api/activities','post',{title:'QA DST repeated hour',category:'assessment',subtype:null,description:'Original context',assessment_start:'2026-11-01T06:30:00Z',assessment_end:'2026-11-01T07:30:00Z'});
 await page.goto('/');await nav(page,'Classes, Commitments & Assessments');
 await page.getByRole('button',{name:'Edit block QA DST repeated hour',exact:true}).click();
 await page.getByRole('textbox',{name:'Description',exact:true}).fill('Edited context, same absolute assessment time.');
 await page.getByRole('button',{name:'Save block',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
 const saved=(await json(request,'/api/state')).activities.find(a=>a.id===item.id);
 expect(Date.parse(saved.assessment_start)).toBe(Date.parse('2026-11-01T06:30:00Z'));
 expect(Date.parse(saved.assessment_end)).toBe(Date.parse('2026-11-01T07:30:00Z'));
 await json(request,`/api/activities/${item.id}`,'delete');
});

test('Sunday boundaries keep original instants and copy only eligible meetings',async({page,request})=>{
 await page.clock.setFixedTime(new Date('2026-11-09T12:00:00Z'));
 const activity=await json(request,'/api/activities','post',{title:'QA Sunday boundary class',category:'class',subtype:'Tutorial'});
 const nextSunday=await json(request,'/api/activities','post',{title:'QA Following Sunday',category:'commitment',subtype:'Personal'});
 const assessment=await json(request,'/api/activities','post',{title:'QA Sunday fixed assessment',category:'assessment',subtype:null,assessment_start:'2026-11-08T01:00:00-05:00',assessment_end:'2026-11-08T01:30:00-05:00'});
 try{
  const before=await json(request,'/api/occurrences','post',{activity_id:activity.id,start:'2026-11-07T23:45:00-05:00',end:'2026-11-08T00:15:00-05:00'});
  const sunday=await json(request,'/api/occurrences','post',{activity_id:activity.id,start:'2026-11-08T00:15:00-05:00',end:'2026-11-08T01:00:00-05:00'});
  const saturday=await json(request,'/api/occurrences','post',{activity_id:activity.id,start:'2026-11-14T23:15:00-05:00',end:'2026-11-14T23:45:00-05:00'});
  const after=await json(request,'/api/occurrences','post',{activity_id:nextSunday.id,start:'2026-11-15T00:05:00-05:00',end:'2026-11-15T00:10:00-05:00'});
  const grouped=await calendar(request,'2026-11-11');
  expect(grouped.week_start).toBe('2026-11-08');expect(grouped.week_end).toBe('2026-11-14');
  expect(grouped.occurrences).toEqual(expect.arrayContaining([before,sunday,saturday]));
  expect(grouped.occurrences.some(o=>o.id===after.id)).toBe(false);
  const assessmentOriginal=grouped.occurrences.find(o=>o.activity_id===assessment.id);

  await page.goto('/');await nav(page,'Classes, Commitments & Assessments');
  await expect(page.locator('#week-title')).toHaveText('Nov 8–14, 2026');
  expect(await page.getByTestId('calendar-day').evaluateAll(els=>els.map(e=>e.dataset.date))).toEqual(Array.from({length:7},(_,i)=>addDays('2026-11-08',i)));
  // The palette's manual alternative works with a keyboard and lists Sunday first.
  const manual=page.getByTestId('block-palette').getByRole('button',{name:`Schedule ${activity.title} from palette`,exact:true});
  await manual.focus();await page.keyboard.press('Enter');
  const dates=page.getByRole('dialog').getByRole('combobox',{name:'Date',exact:true});
  expect(await dates.locator('option').evaluateAll(options=>options.map(o=>o.value))).toEqual(Array.from({length:7},(_,i)=>addDays('2026-11-08',i)));
  await page.getByRole('dialog').getByRole('button',{name:'Cancel',exact:true}).click();
  await page.getByRole('button',{name:'Previous Week',exact:true}).click();
  await expect(page.getByTestId('calendar-day').first()).toHaveAttribute('data-date','2026-11-01');
  await page.getByRole('button',{name:'This Week',exact:true}).click();
  await expect(page.getByTestId('calendar-day').first()).toHaveAttribute('data-date','2026-11-08');
  await page.getByRole('button',{name:'Next Week',exact:true}).click();
  await expect(page.getByTestId('calendar-day').first()).toHaveAttribute('data-date','2026-11-15');
  await expect(page.getByTestId('calendar-day').last()).toHaveAttribute('data-date','2026-11-21');
  await page.getByRole('button',{name:'Copy Previous Week',exact:true}).click();
  await expect.poll(async()=>(await calendar(request,'2026-11-15')).occurrences.filter(o=>o.activity_id===activity.id).length).toBe(2);
  const copied=(await calendar(request,'2026-11-15')).occurrences.filter(o=>o.activity_id===activity.id);
  expect(copied.map(o=>o.start).sort()).toEqual(['2026-11-15T05:15:00Z','2026-11-22T04:15:00Z']);
  expect((await calendar(request,'2026-11-15')).occurrences.some(o=>o.activity_id===assessment.id)).toBe(false);
  await page.getByRole('button',{name:'Copy Previous Week',exact:true}).click();
  await expect(page.getByRole('button',{name:'Copy Previous Week',exact:true})).toBeEnabled();
  expect((await calendar(request,'2026-11-15')).occurrences.filter(o=>o.activity_id===activity.id)).toHaveLength(2);
  const retained=(await calendar(request,'2026-11-08')).occurrences;
  expect(retained).toEqual(expect.arrayContaining([before,sunday,saturday,assessmentOriginal]));
 }finally{
  for(const item of [activity,nextSunday,assessment])await json(request,`/api/activities/${item.id}`,'delete');
 }
});

test('many reusable blocks stay compact, searchable and usable at a narrow viewport',async({page,request})=>{
 const items=[];
 try{
  for(let i=0;i<18;i++)items.push(await json(request,'/api/activities','post',{title:i===17?'QA Palette Waterloo Reality Labs with a long descriptive name':`QA Palette MATH${String(100+i)}`,category:i%2?'commitment':'class',subtype:i%2?'Groupwork':'Lecture'}));
  await page.goto('/');await nav(page,'Classes, Commitments & Assessments');
  await page.getByRole('button',{name:'Next Week',exact:true}).click();
  await page.getByRole('button',{name:'Next Week',exact:true}).click();
  await expect(page.getByTestId('calendar-event')).toHaveCount(0);
  const palette=page.getByTestId('block-palette');
  await palette.getByRole('searchbox',{name:'Search reusable blocks',exact:true}).fill('QA Palette');
  await expect(palette.getByTestId('palette-item')).toHaveCount(18);
  for(const viewport of [{width:1440,height:1000},{width:390,height:844}]){
   await page.setViewportSize(viewport);await palette.scrollIntoViewIfNeeded();
   const box=await palette.boundingBox();expect(box.height).toBeLessThan(230);
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
   await fs.mkdir('../test-results/calendar-screenshots',{recursive:true});
   await page.screenshot({path:`../test-results/calendar-screenshots/calendar-palette-many-${viewport.width}.png`,animations:'disabled'});
  }
  const gridScroll=page.getByTestId('calendar-scroll');
  await gridScroll.focus();const initialScroll=await gridScroll.evaluate(e=>e.scrollTop);
  await page.keyboard.press('ArrowDown');
  await expect.poll(()=>gridScroll.evaluate(e=>e.scrollTop)).toBeGreaterThan(initialScroll);
  await palette.getByRole('searchbox',{name:'Search reusable blocks',exact:true}).fill('Reality Labs');
  await expect(palette.getByTestId('palette-item')).toHaveCount(1);
  await expect(palette.getByTestId('palette-item')).toContainText('Reality Labs');
  await palette.getByRole('button',{name:`Schedule ${items[17].title} from palette`,exact:true}).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await captureAudit(page,'calendar-mobile-palette-manual');
  await page.getByRole('dialog').getByRole('button',{name:'Cancel',exact:true}).click();
  await palette.getByRole('searchbox',{name:'Search reusable blocks',exact:true}).fill('no saved block matches this');
  await expect(palette.getByTestId('palette-item')).toHaveCount(0);
 }finally{
  for(const item of items)await json(request,`/api/activities/${item.id}`,'delete');
 }
});
