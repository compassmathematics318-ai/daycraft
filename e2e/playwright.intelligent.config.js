import base from './playwright.config.js';

export default {...base,testIgnore:[],testMatch:'**/intelligent.spec.js',reporter:[['list'],['json',{outputFile:'../test-results/intelligent-scheduling/browser-results.json'}],['html',{open:'never',outputFolder:'../test-results/intelligent-scheduling/browser-report'}]],outputDir:'../test-results/intelligent-scheduling/browser'};
