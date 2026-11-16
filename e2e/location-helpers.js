import {expect} from '@playwright/test';

export async function chooseLocation(page,scope,{id,name,mode='required',label='Location'}){
 const picker=scope.locator('.location-picker').filter({has:page.getByText(label,{exact:true})});
 await picker.getByRole('button',{name:/^(Add a location|Change)$/}).click();
 const dialog=page.getByRole('dialog',{name:'Choose a location',exact:true});
 await expect(dialog).toBeVisible();
 if(id&&!name){const response=await page.request.get('/api/state');name=(await response.json()).locations.find(p=>p.id===id).name}
 if(name){await dialog.getByLabel('Search saved locations or addresses').fill(name);await dialog.locator('.location-result-list button').filter({hasText:name}).click()}
 await dialog.getByRole('combobox',{name:'Location meaning',exact:true}).selectOption(mode);
 await dialog.getByRole('button',{name:'Use location',exact:true}).click();
 await expect(dialog).toHaveCount(0);
}
