import base from './playwright.config.js';
// Keep focused lifecycle evidence separate from the last complete regression run.
const name=process.env.DAYCRAFT_QA_RUN||'lifecycle';
export default {...base,reporter:[['list'],['json',{outputFile:`../test-results/${name}-browser-results.json`}],['html',{open:'never',outputFolder:`../test-results/${name}-browser-report`}]],outputDir:`../test-results/${name}-browser`};
