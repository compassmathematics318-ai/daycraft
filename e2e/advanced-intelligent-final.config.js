import base from './playwright.config.js';
export default {...base,testIgnore:[],testMatch:'**/intelligent.spec.js',
 reporter:[['list'],['json',{outputFile:'../test-results/advanced-workload/browser-intelligent-final.json'}]],
 outputDir:'../test-results/advanced-workload/browser-intelligent-final',use:{...base.use,trace:'off'}};
