import base from './playwright.config.js';
// Seeded saved plans exercise the real completion API; no solver is mocked.
const name=process.env.DAYCRAFT_QA_RUN||'completion';
export default {...base,testIgnore:[],testMatch:'**/completion.spec.js',globalSetup:'./completion-setup.mjs',reporter:[['list'],['json',{outputFile:`../test-results/${name}-browser-results.json`}],['html',{open:'never',outputFolder:`../test-results/${name}-browser-report`}]],outputDir:`../test-results/${name}-browser`};
