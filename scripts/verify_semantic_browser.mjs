// Inspect the personal app without changing any saved settings or records.
import {chromium,expect} from '../e2e/node_modules/@playwright/test/index.mjs';
import fs from 'node:fs/promises';
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const blocked=[];
await page.route('**/api/**',route=>{
 if(route.request().method()==='GET')return route.continue();
 blocked.push(`${route.request().method()} ${new URL(route.request().url()).pathname}`);
 return route.abort();
});
try{
 await page.goto('http://127.0.0.1:8765/');
 await page.locator('.nav-item').filter({hasText:'Daily planner'}).click();
 await page.getByLabel('Planning date',{exact:true}).fill('2026-11-13');
 await expect(page.locator('.calendar-stale-note')).toContainText('needs location review');
 const gym=page.locator('.timeline-block').filter({has:page.locator('.timeline-title',{hasText:/^Gym/})});
 await expect(gym).toContainText('Planned: Physical Activities Complex');
 await expect(gym).toContainText('Preferred: Physical Activities Complex');
 await expect(page.locator('body')).not.toContainText('Only the preferred place is allowed');
 await expect(page.locator('body')).not.toContainText('alternative venues are not permitted');
 await page.screenshot({path:'test-results/semantic-location/live-planner.png',fullPage:true});
 await gym.click();
 const dialog=page.getByRole('dialog');
 await expect(dialog).toContainText('A preference stays flexible.');
 await expect(dialog).not.toContainText('alternative venues are not permitted');
 await dialog.screenshot({path:'test-results/semantic-location/live-gym-details.png'});
 expect(blocked).toEqual([]);
 await fs.writeFile('test-results/semantic-location/live-browser.json',JSON.stringify({warning:await page.locator('.calendar-stale-note').innerText(),detail:await dialog.innerText(),blockedMutations:blocked},null,2));
 console.log('Live personal plan marked for regeneration; PAC preserved, flexible preference wording visible, obsolete rationale absent, no API writes.');
}finally{await browser.close();}
