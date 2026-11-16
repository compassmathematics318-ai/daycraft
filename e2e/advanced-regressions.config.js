import base from './playwright.config.js';
export default {...base,testIgnore:[],testMatch:['**/advanced-workload.spec.js','**/workload-quality.spec.js','**/intelligent.spec.js','**/meal-order.spec.js'],
 reporter:[['list'],['json',{outputFile:'../test-results/advanced-workload/browser-regressions.json'}]],
 outputDir:'../test-results/advanced-workload/browser-regressions',use:{...base.use,trace:'off'}};
