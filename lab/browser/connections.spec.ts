import {test,expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test.beforeEach(async({page})=>{
  await page.route('**/*',route=>new URL(route.request().url()).hostname==='127.0.0.1'?route.continue():route.abort());
  await page.goto('/');
});

for(const scenario of ['mixed','new','failure','offline','slow']){
  test(`${scenario}: honest status, usable rows, no overflow`,async({page},info)=>{
    await page.getByLabel('Scenario').selectOption(scenario);
    if(scenario==='slow')await expect(page.getByText('Checking connections…',{exact:true})).toBeVisible();
    const rows=page.locator('.connection-card');
    await expect(rows).toHaveCount(7);
    if(scenario==='offline'){
      await expect(rows.locator('.connection-badge').filter({hasText:'Couldn’t check'})).toHaveCount(7);
      await expect(page.getByRole('button',{name:'Refresh connections'})).toBeEnabled();
    }else{
      await expect(rows.filter({hasText:'Gmail inbox'}).locator('.connection-badge')).toHaveText(scenario==='new'?'Not connected':/Connected/,{timeout:15000});
      await expect(rows.filter({hasText:'Microsoft email'}).locator('.connection-badge')).toHaveText(scenario==='failure'?'Couldn’t check':scenario==='new'?'Not connected':'Sign-in pending');
      await expect(rows.locator('.connection-badge').filter({hasText:'Admin setup'})).toHaveCount(4);
    }
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    for(const row of await rows.all()){
      const box=await row.boundingBox();expect(box!.height).toBeGreaterThanOrEqual(44);expect(box!.height).toBeLessThan(190);
    }
    const accessibility=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa','wcag22aa']).analyze();
    expect(accessibility.violations).toEqual([]);
    await page.screenshot({path:info.outputPath(`${scenario}.png`),fullPage:true});
  });
}

test('keyboard navigation preserves status and progressively reveals setup details',async({page})=>{
  const scheduling=page.locator('.connection-card').filter({hasText:'Scheduling & Google'});
  await expect(scheduling).toBeEnabled();
  await scheduling.focus();await page.keyboard.press('Enter');
  await expect(page.getByRole('heading',{name:'Scheduling & Google sign-in',exact:true}).first()).toBeFocused();
  const disclosure=page.locator('.connection-setup-guide details');
  await expect(disclosure).not.toHaveAttribute('open');
  await disclosure.locator('summary').focus();await page.keyboard.press('Enter');
  await expect(disclosure).toHaveAttribute('open','');
  await page.getByRole('button',{name:'All connections'}).click();
  await expect(page.getByRole('heading',{name:'Connections',exact:true})).toBeFocused();
  await expect(page.locator('.connection-card').filter({hasText:'Microsoft email'}).locator('.connection-badge')).toHaveText('Sign-in pending');
});
