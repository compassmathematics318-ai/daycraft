import base from './playwright.config.js';
const name=process.env.DAYCRAFT_QA_RUN||'history';
export default {...base,testIgnore:[],testMatch:'**/history.spec.js',globalSetup:'./completion-setup.mjs',reporter:[['list'],['json',{outputFile:`../test-results/${name}-browser-results.json`}],['html',{open:'never',outputFolder:`../test-results/${name}-browser-report`}]],outputDir:`../test-results/${name}-browser`};
