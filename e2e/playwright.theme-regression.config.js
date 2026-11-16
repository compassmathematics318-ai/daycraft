import base from './playwright.config.js';
export default {...base,testMatch:['**/zz-projects.spec.js','**/zzz-tasks.spec.js'],grep:/project cards, metadata form|weekly task library, editor/,reporter:[['list'],['json',{outputFile:'../test-results/theme-regression-results.json'}]],outputDir:'../test-results/theme-regression-browser'};
