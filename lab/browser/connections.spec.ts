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
    const cards=page.locator('.connection-card-box');
    await expect(cards).toHaveCount(7);
    const rows=page.locator('button.connection-card');
    if(scenario==='offline'){
      await expect(rows).toHaveCount(7);
      await expect(rows.locator('.connection-badge').filter({hasText:'Needs attention'})).toHaveCount(7);
      await expect(page.getByText('Connections could not be checked. Try again or open a service.',{exact:true})).toBeVisible();
      await expect(page.getByRole('button',{name:'Refresh connections'})).toBeEnabled();
    }else{
      await expect(rows).toHaveCount(3,{timeout:15000});
      await expect(rows.filter({hasText:'Cosmaneura account & appointments'}).locator('.connection-badge')).toHaveText(scenario==='new'?'Needs setup':'Connected',{timeout:15000});
      // The fixture confirms Google sign-in but withholds calendar access.
      // An authenticated account must not appear fully ready for both services.
      const google=rows.filter({hasText:'Google email & calendar'});
      await expect(google.locator('.connection-badge')).toHaveText(scenario==='new'?'Needs setup':'Needs attention');
      if(scenario!=='new')await expect(google).toContainText('Review calendar access');
      const microsoft=rows.filter({hasText:'Microsoft email & calendar'});
      await expect(microsoft.locator('.connection-badge')).toHaveText(scenario==='failure'?'Needs attention':'Needs setup');
      await expect(microsoft).toContainText(scenario==='failure'?'Current status is unknown':scenario==='new'?'Sign in to connect your account.':'Continue sign-in, then return to check the result.');
      const managed=page.getByRole('region',{name:'Managed by your practice',exact:true});
      const coming=page.getByRole('region',{name:'Coming soon',exact:true});
      await expect(managed.getByRole('article')).toHaveCount(2);
      await expect(coming.getByRole('article')).toHaveCount(2);
      await expect(managed.locator('button.connection-card')).toHaveCount(0);
      await expect(coming.locator('button.connection-card')).toHaveCount(0);
      await expect(managed.getByText('Ask your practice administrator to finish setup.',{exact:true})).toHaveCount(2);
      await expect(coming.getByText('No connection or request is started here.',{exact:true})).toHaveCount(2);
    }
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    // Keep the original touch-row size budget on actionable connection rows;
    // explanatory administrator/coming-soon articles are not touch targets.
    for(const row of await rows.all()){
      const box=await row.boundingBox();expect(box!.height).toBeGreaterThanOrEqual(44);expect(box!.height).toBeLessThan(190);
    }
    const accessibility=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa','wcag22aa']).analyze();
    expect(accessibility.violations).toEqual([]);
    await page.screenshot({path:info.outputPath(`${scenario}.png`),fullPage:true});
  });
}

test('keyboard navigation preserves status and progressively reveals saved-work recovery',async({page})=>{
  const google=page.locator('button.connection-card').filter({hasText:'Google email & calendar'});
  await expect(google.locator('.connection-badge')).toHaveText('Needs attention');
  await google.focus();await page.keyboard.press('Enter');
  await expect(page.getByRole('heading',{name:'Google email & calendar',exact:true})).toBeFocused();
  await page.getByRole('button',{name:'All connections',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Connections',exact:true})).toBeFocused();
  const scheduling=page.getByRole('region',{name:'Managed by your practice',exact:true}).getByRole('article').filter({hasText:'Scheduling & Google sign-in'});
  await expect(scheduling.getByText('Ask your practice administrator to finish setup.',{exact:true})).toBeVisible();
  const disclosure=scheduling.locator('details');
  await expect(disclosure).not.toHaveAttribute('open');
  await disclosure.locator('summary').focus();await page.keyboard.press('Enter');
  await expect(disclosure).toHaveAttribute('open','');
  await expect(disclosure).toContainText('This does not connect an account.');
  await disclosure.getByRole('button',{name:'Review saved Scheduling & Google sign-in work',exact:true}).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading',{name:'Scheduling & Google sign-in',exact:true})).toBeFocused();
  await expect(page.getByText('Review your saved work and exact unresolved requests. Current access is still required for source content and new work.',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'All connections'}).click();
  await expect(page.getByRole('heading',{name:'Connections',exact:true})).toBeFocused();
  await expect(google.locator('.connection-badge')).toHaveText('Needs attention');
  await expect(page.locator('.connection-card').filter({hasText:'Microsoft email & calendar'}).locator('.connection-badge')).toHaveText('Needs setup');
});
