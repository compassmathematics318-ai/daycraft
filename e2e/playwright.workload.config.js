import base from './playwright.config.js';
export default {...base,testIgnore:[],testMatch:'**/workload-quality.spec.js',timeout:90000,
 use:{...base.use,trace:'off'},
 reporter:[['list'],['json',{outputFile:'../test-results/workload-quality/browser-results.json'}]],
 outputDir:'../test-results/workload-quality/browser'};
