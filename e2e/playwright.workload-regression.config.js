import base from './playwright.config.js';
export default {...base,testIgnore:[],testMatch:['**/intelligent.spec.js','**/meal-order.spec.js'],
 reporter:[['list'],['json',{outputFile:'../test-results/workload-calibration/browser-regressions.json'}]],
 outputDir:'../test-results/workload-calibration/browser-regressions',use:{...base.use,trace:'off'}};
