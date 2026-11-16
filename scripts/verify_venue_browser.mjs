// Read-only smoke against the personal app; all API writes are blocked.
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
 await expect(gym).toContainText('Planned: Mathematics & Computer');
 await expect(gym).toContainText('Preferred: Physical Activities Complex');
 await page.screenshot({path:'test-results/venue-live-planner-reviewed.png',fullPage:true});
 await gym.click();
 const dialog=page.getByRole('dialog');
 await expect(dialog).toContainText('Planned: Mathematics & Computer');
 await expect(dialog).toContainText('Preferred: Physical Activities Complex');
 await dialog.screenshot({path:'test-results/venue-live-detail-reviewed.png'});
 expect(blocked).toEqual([]);
 await fs.writeFile('test-results/venue-live-browser.json',JSON.stringify({warning:await page.locator('.calendar-stale-note').innerText(),gymDetail:await dialog.innerText(),blockedMutations:blocked},null,2));
 console.log('Live personal Gym plan clearly marked stale; actual MC and configured PAC distinguished; no API writes.');
}finally{await browser.close();}
