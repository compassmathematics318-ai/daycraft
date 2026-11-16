import {spawn} from 'node:child_process';
import path from 'node:path';
import fs from 'node:fs';
import {randomUUID} from 'node:crypto';
import {qaPython} from './qa-python.mjs';

export default async function setup(){
 const root=path.resolve(import.meta.dirname,'..'),run=Date.now(),url='http://127.0.0.1:8876/health';
 const python=qaPython(root);
 try{const response=await fetch(url,{signal:AbortSignal.timeout(1000)});if(response)throw Error('QA port8876 already in use. Stop the previous QA server before running tests.')}catch(error){if(!String(error).includes('fetch failed'))throw error}
 fs.mkdirSync(path.join(root,'test-results'),{recursive:true});
 const token=randomUUID(),log=fs.openSync(path.join(root,'test-results','e2e-server.log'),'w');
 const child=spawn(python,['-u','e2e/server.py'],{cwd:root,windowsHide:true,stdio:['ignore',log,log],env:{...process.env,SCHEDULE_QA_TOKEN:token,SCHEDULE_BUILDER_DB:path.join(root,'test-results',`e2e-${run}.sqlite`),SCHEDULE_BUILDER_ROUTE_CACHE:path.join(root,'test-results',`routes-${run}.sqlite`),SCHEDULE_BUILDER_OFFLINE:'1'}});
 let ready=false;
 for(let n=0;n<150;n++){try{ready=(await fetch(url,{signal:AbortSignal.timeout(1000)})).ok;if(ready)break}catch{}await new Promise(r=>setTimeout(r,200))}
 if(!ready){child.kill();fs.closeSync(log);throw Error('QA server failed to start. See test-results/e2e-server.log')}
 return async()=>{
  try{await fetch('http://127.0.0.1:8876/__qa_shutdown',{method:'POST',headers:{'x-qa-token':token},signal:AbortSignal.timeout(2000)})}catch{}
  for(let n=0;n<50;n++){try{await fetch(url,{signal:AbortSignal.timeout(1000)})}catch{fs.closeSync(log);return}await new Promise(r=>setTimeout(r,200))}
  child.kill();fs.closeSync(log);throw Error('QA server did not stop after shutdown. See test-results/e2e-server.log');
 };
}
