import base from './playwright.config.js';

export default {...base,testIgnore:[],testMatch:'**/meal-order.spec.js',use:{...base.use,hasTouch:true},reporter:[['list'],['json',{outputFile:'../test-results/meal-order/browser-results.json'}],['html',{open:'never',outputFolder:'../test-results/meal-order/browser-report'}]],outputDir:'../test-results/meal-order/browser'};
