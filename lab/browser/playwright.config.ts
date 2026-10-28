import {defineConfig} from '@playwright/test';
import {fileURLToPath} from 'node:url';
const web=fileURLToPath(new URL('../../web/',import.meta.url));
export default defineConfig({
  testDir:'.',testMatch:'*.spec.ts',timeout:25000,workers:2,fullyParallel:true,
  outputDir:process.env.LAB_BROWSER_OUTPUT??'test-results',
  reporter:[['list'],['json',{outputFile:process.env.LAB_BROWSER_REPORT??'test-results/results.json'}]],
  // Keep routine and failing runs text-only; retries must not multiply chat images.
  use:{baseURL:'http://127.0.0.1:5187',trace:'off',screenshot:'off',video:'off'},
  projects:[{name:'desktop',use:{viewport:{width:1280,height:900}}},{name:'phone',use:{viewport:{width:390,height:844}}}],
  webServer:{command:`node ${web}node_modules/vite/bin/vite.js --config ${web}vite.ux-lab.config.ts`,url:'http://127.0.0.1:5187',reuseExistingServer:true,timeout:15000},
});
