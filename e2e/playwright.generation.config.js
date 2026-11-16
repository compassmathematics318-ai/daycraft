import base from './playwright.config.js';

export default {...base,testIgnore:[],testMatch:'**/generation.spec.js',globalSetup:'./generation-setup.mjs',reporter:[['list'],['json',{outputFile:'../test-results/generation-repair/browser-results.json'}],['html',{open:'never',outputFolder:'../test-results/generation-repair/browser-report'}]],outputDir:'../test-results/generation-repair/browser'};
