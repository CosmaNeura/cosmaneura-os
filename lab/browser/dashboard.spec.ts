import {test,expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
const address=process.env.LAB_REPORT_URL;
test('agent dashboard is readable, accessible, and exposes no database files',async({page,request},info)=>{
  test.skip(!address,'Set LAB_REPORT_URL to a running local report viewer.');
  const url=new URL(address!);
  expect(url.hostname).toBe('127.0.0.1');
  await page.route('**/*',route=>new URL(route.request().url()).hostname==='127.0.0.1'?route.continue():route.abort());
  await page.goto(url.href);
  await expect(page.getByRole('heading',{name:'Agent laboratory',exact:true})).toBeVisible();
  expect(await page.locator('.episode').count()).toBeGreaterThan(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  const results=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa','wcag22aa']).analyze();
  expect(results.violations).toEqual([]);
  expect((await request.get(new URL('/postgres/PG_VERSION',url).href)).status()).toBe(404);
  expect((await request.get(new URL('/artifacts.sqlite3',url).href)).status()).toBe(404);
  await page.screenshot({path:info.outputPath('dashboard.png')});
});
