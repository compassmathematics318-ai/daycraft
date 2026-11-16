import {expect} from '@playwright/test';

// Verify the real settings mutation. A missing response gets one recorded retry;
// record UI and server state without assuming why the first action failed.
export async function choosePersistedTheme(page,request,theme,testInfo){
 const network=[];
 const sent=r=>{if(r.url().endsWith('/api/settings'))network.push({event:'request',method:r.method(),data:r.postData()})};
 const failed=r=>{if(r.url().endsWith('/api/settings'))network.push({event:'requestfailed',failure:r.failure()})};
 page.on('request',sent);page.on('requestfailed',failed);
 await page.evaluate(()=>{window.__qaThemeChanges=[];window.__qaThemeListener=e=>{if(e.target?.matches?.('select[aria-label="Theme"]'))window.__qaThemeChanges.push({value:e.target.value,isTrusted:e.isTrusted})};document.addEventListener('change',window.__qaThemeListener,true)});
 try{
 let response;
 for(let attempt=0;attempt<2;attempt++){
  const pending=page.waitForResponse(r=>r.url().endsWith('/api/settings')&&r.request().method()==='PUT'&&r.request().postDataJSON()?.theme===theme,{timeout:5000}).catch(()=>null);
  await page.getByLabel('Theme',{exact:true}).selectOption(theme);response=await pending;
  if(response)break;
  if(attempt===0){
   const ui=await page.evaluate(()=>({htmlTheme:document.documentElement.dataset.theme,localTheme:localStorage.getItem('daycraft-theme'),selectedTheme:document.querySelector('select[aria-label="Theme"]')?.value,changes:window.__qaThemeChanges}));
   const serverTheme=(await(await request.get('/api/state')).json()).settings.theme;
   await testInfo.attach(`missing-${theme}-settings-response`,{body:JSON.stringify({expectedTheme:theme,ui,serverTheme,network},null,2),contentType:'application/json'});
   testInfo.annotations.push({type:'theme-event-retry',description:`No ${theme} settings PUT response within five seconds of first selection; repeating the same selection once.`});
  }
 }
 expect(response,`Selecting ${theme} must send a real settings PUT`).not.toBeNull();
 expect(response.ok(),await response.text()).toBeTruthy();
 await expect(page.locator('html')).toHaveAttribute('data-theme',theme);
 await expect.poll(async()=>(await(await request.get('/api/state')).json()).settings.theme).toBe(theme);
 }finally{
  page.off('request',sent);page.off('requestfailed',failed);
  await page.evaluate(()=>document.removeEventListener('change',window.__qaThemeListener,true));
 }
}
