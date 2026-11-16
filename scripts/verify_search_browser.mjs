// Live read-only UI smoke: provider-backed search and map preview, no saved data.
import {chromium,expect} from '../e2e/node_modules/@playwright/test/index.mjs';
import fs from 'node:fs/promises';
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const blocked=[];
await page.route('**/api/**',route=>{
 const request=route.request(),url=new URL(request.url());
 if(request.method()==='GET'||(request.method()==='POST'&&url.pathname==='/api/geocode'))return route.continue();
 blocked.push(`${request.method()} ${url.pathname}`);return route.abort();
});
try{
 await page.goto('http://127.0.0.1:8765/');
 await page.locator('.nav-item').filter({hasText:'Tasks & deadlines'}).click();
 await page.getByRole('button',{name:/^Task Library/}).click();
 await page.getByRole('button',{name:'New reusable task',exact:true}).click();
 const task=page.getByRole('dialog');
 await expect(task.getByLabel(/^Minimum work blocks on a scheduled day/)).toHaveValue('1');
 await task.getByRole('button',{name:'Add a location',exact:true}).click();
 const picker=page.getByRole('dialog',{name:'Choose a location',exact:true});
 const responsePromise=page.waitForResponse(response=>response.url().endsWith('/api/geocode'));
 await picker.getByLabel('Search saved locations or addresses').fill('SLC Waterloo');
 await picker.getByLabel('Search saved locations or addresses').press('Enter');
 const response=await responsePromise,payload=await response.json();
 expect(response.status()).toBe(200);expect(payload.status).toBe('ok');
 const candidate=payload.results.find(result=>result.name.includes('Student Life Centre')&&Math.abs(result.lat-43.4719722)<0.002&&Math.abs(result.lon+80.5452128)<0.002);
 expect(candidate).toBeTruthy();
 await picker.locator('.location-provider-result').filter({hasText:candidate.name}).first().click();
 await expect(picker.locator('.location-mini-map .leaflet-container')).toBeVisible();
 await picker.getByText('Floor, entrance and coordinates',{exact:true}).click();
 expect(Number(await picker.getByLabel('Latitude',{exact:true}).inputValue())).toBe(candidate.lat);
 expect(Number(await picker.getByLabel('Longitude',{exact:true}).inputValue())).toBe(candidate.lon);
 await picker.screenshot({path:'test-results/search-repair-live-picker.png'});
 await fs.writeFile('test-results/search-repair-live-browser.json',JSON.stringify({query:'SLC Waterloo',candidate,diagnostics:payload.diagnostics,blockedMutations:blocked},null,2));
 expect(blocked).toEqual([]);
 console.log('Live SLC search, verified coordinates, map preview and scheduled-day labels passed; no data saved.');
}finally{await browser.close();}
