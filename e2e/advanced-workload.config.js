import config from './playwright.config.js';
export default {...config,testMatch:'**/advanced-workload.spec.js',testIgnore:[],reporter:[['list'],['json',{outputFile:'../test-results/advanced-workload/playwright-results.json'}]]};
