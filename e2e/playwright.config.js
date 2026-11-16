import {defineConfig} from '@playwright/test';
export default defineConfig({
  testDir: './tests', testIgnore:['**/history.spec.js','**/completion.spec.js','**/generation.spec.js','**/intelligent.spec.js','**/meal-order.spec.js','**/workload-quality.spec.js','**/advanced-workload.spec.js'], timeout:90000, expect:{timeout:10000}, workers:1,
  reporter:[['list'],['json',{outputFile:'../test-results/playwright-results.json'}],['html',{open:'never',outputFolder:'../test-results/playwright-report'}]],
  outputDir:'../test-results/browser',
  use:{actionTimeout:15000,baseURL:'http://127.0.0.1:8876',channel:'msedge',headless:true,viewport:{width:1440,height:1000},screenshot:'only-on-failure',trace:'retain-on-failure'},
  globalSetup:'./global-setup.mjs',
});

