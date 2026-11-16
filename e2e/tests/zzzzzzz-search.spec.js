import {test,expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs/promises';

// Public search and map tiles are fixtures here; actual provider checks run separately.
const tile=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j85sAAAAASUVORK5CYII=','base64');
async function json(request,path,method='get',data){const r=await request[method](path,{data,...(path.includes('/schedules/generate')?{timeout:45000}:{})});expect(r.ok(),await r.text()).toBeTruthy();return r.status()===204?null:r.json()}
async function nav(page,name){const toggle=page.getByRole('button',{name:'Open navigation',exact:true});if(await toggle.isVisible()&&!await page.locator('.sidebar').evaluate(e=>e.classList.contains('open')))await toggle.click();await page.locator('.nav-item').filter({hasText:name}).first().click()}
async function audit(page,name){await fs.mkdir('../test-results/search-review',{recursive:true});await page.screenshot({path:`../test-results/search-review/${name}.png`,fullPage:true,animations:'disabled'});const axe=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();await fs.writeFile(`../test-results/search-review/${name}.axe.json`,JSON.stringify(axe.violations,null,2));expect(axe.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}))).toEqual([]);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true)}

for(const surface of ['picker','manager'])test(`${surface} classifies explicit search outcomes, preserves local choices during outages, and confirms provider coordinates`,async({page,request})=>{
 test.setTimeout(240000);
 await page.route('https://tile.openstreetmap.org/**',r=>r.fulfill({status:200,contentType:'image/png',body:tile}));
 const saved=await json(request,'/api/locations','post',{name:`Search QA saved ${surface}`,lat:43.471111,lon:-80.541111,address:'200 University Avenue W',aliases:[`Search QA ${surface} local alias`]});
 let calls=0,reply={status:'unavailable',message:'Map search is temporarily unavailable. Saved places and manual selection are still available.'},release;
 const result={name:`Search QA external ${surface}, Waterloo`,lat:43.478123,lon:-80.548456,address:{house_number:'321',road:'QA University Avenue',city:'Waterloo'},provider:'QA fixture provider',attribution:'QA fixture attribution',match_type:'provider'};
 await page.route('**/api/geocode',async route=>{calls++;if(release)await release.promise;const body={results:reply.status==='ok'?[result]:[],...reply};await route.fulfill({status:['ok','no_results'].includes(reply.status)?200:reply.status==='invalid_query'?422:503,contentType:'application/json',body:JSON.stringify(['ok','no_results'].includes(reply.status)?body:{detail:body})})});
 await page.goto('/');await nav(page,'Locations & map');
 let scope,input,search;
 if(surface==='picker'){await page.locator('.location-overview .location-picker').getByRole('button',{name:/^(Add a location|Change)$/}).click();scope=page.getByRole('dialog',{name:'Choose a location',exact:true});input=scope.getByLabel('Search saved locations or addresses');search=()=>scope.getByRole('button',{name:'Search map',exact:true})}
 else{await page.locator('.location-manager > summary').click();scope=page.locator('.location-manager');input=scope.getByLabel('Search for a place',{exact:true});search=()=>scope.getByRole('button',{name:'Search',exact:true})}
 await input.fill(`Search QA ${surface} local alias`);await expect(scope.locator('[aria-label="Saved location matches"] button')).toHaveCount(1);expect(calls).toBe(0);
 await scope.locator('[aria-label="Saved location matches"] button').click();
 if(surface==='picker')await expect(scope.locator('[title="Selected location: '+saved.name+'"]')).toBeVisible();else await expect(scope.getByLabel('Latitude',{exact:true})).toHaveValue(String(saved.lat));
 await search().click();await expect(scope.locator('[data-search-status="unavailable"]')).toHaveRole('alert');await expect(scope.locator('[data-search-status="no_results"]')).toHaveCount(0);await expect(scope.locator('[aria-label="Saved location matches"] button')).toHaveCount(1);
 // Saved local results remain selectable after the explicit provider search fails.
 await scope.locator('[aria-label="Saved location matches"] button').click();
 if(surface==='picker')await expect(scope.getByRole('button',{name:'Use location',exact:true})).toBeEnabled();else await expect(scope.getByRole('button',{name:'Save location',exact:true})).toBeEnabled();
 for(const status of ['rate_limited','timeout','configuration_error','invalid_response','invalid_query','no_results']){reply={status,message:`QA ${status} outcome`};await input.fill(`Search QA ${status}`);if(status==='no_results')await input.press('Enter');else await search().click();const response=scope.locator(`[data-search-status="${status}"]`);await expect(response).toContainText(reply.message);await expect(response).toHaveRole(status==='no_results'?'status':'alert');await expect(scope.locator('[aria-label="Map search results"] button')).toHaveCount(0)}
 // A pending request is visible and cannot be submitted a second time.
 let unblock;release={promise:new Promise(resolve=>{unblock=resolve})};reply={status:'ok',message:'Choose a result, then confirm its address and pin.'};await input.fill('Search QA external');const before=calls;await search().click();await expect(scope.getByRole('button',{name:/Searching/})).toBeDisabled();await expect.poll(()=>calls).toBe(before+1);unblock();release=null;
 const candidate=scope.locator('[aria-label="Map search results"] .location-provider-result');await expect(candidate).toHaveCount(1);await expect(candidate).toContainText('321');await expect(candidate).toContainText('QA fixture provider');await expect(candidate).toContainText('QA fixture attribution');
 // Search suggestions do not persist a place. Selection previews it before saving.
 expect((await json(request,'/api/state')).locations.some(p=>p.name.startsWith(`Search QA external ${surface}`))).toBe(false);await candidate.click();await expect(scope.getByLabel('Location name',{exact:true})).toHaveValue(`Search QA external ${surface}`);
 if(surface==='picker')await scope.locator('summary').filter({hasText:'Floor, entrance and coordinates'}).click();else await scope.locator('summary').filter({hasText:'Address, aliases and access details'}).click();
 await expect(scope.getByLabel('Latitude',{exact:true})).toHaveValue(String(result.lat));await expect(scope.getByLabel('Longitude',{exact:true})).toHaveValue(String(result.lon));await expect(scope.getByLabel('Address',{exact:true})).toHaveValue('321, QA University Avenue, Waterloo');
 for(const theme of ['light','dark','midnight','warm'])for(const [size,width,height] of [['desktop',1440,1000],['mobile',390,844]]){await page.setViewportSize({width,height});await page.getByLabel('Theme',{exact:true}).selectOption(theme);await expect(page.locator('html')).toHaveAttribute('data-theme',theme);await candidate.scrollIntoViewIfNeeded();await audit(page,`${surface}-result-${theme}-${size}`)}
 if(surface==='picker'){await scope.getByRole('button',{name:'Save and use this place',exact:true}).click();await expect(scope).toHaveCount(0)}else await scope.getByRole('button',{name:'Save location',exact:true}).click();
 await expect.poll(async()=>(await json(request,'/api/state')).locations.find(p=>p.name===`Search QA external ${surface}`)).toMatchObject({lat:result.lat,lon:result.lon,address:'321, QA University Avenue, Waterloo'});
 const created=(await json(request,'/api/state')).locations.find(p=>p.name===`Search QA external ${surface}`);
 if(surface==='picker')await expect.poll(async()=>(await json(request,'/api/state')).settings.home_location_id).toBe(created.id);
 await page.reload();await nav(page,'Locations & map');if(surface==='picker')await expect(page.locator('.location-overview .location-selection')).toContainText(created.name);
 expect((await json(request,'/api/state')).locations.filter(p=>p.id===created.id)).toHaveLength(1);
});
