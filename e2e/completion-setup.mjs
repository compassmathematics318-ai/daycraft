import {spawn} from 'node:child_process';
import path from 'node:path';
import fs from 'node:fs';
import {randomUUID} from 'node:crypto';

export default async function setup(){
 const root=path.resolve(import.meta.dirname,'..'),run=Date.now(),url='http://127.0.0.1:8876/health';
 try{const response=await fetch(url,{signal:AbortSignal.timeout(1000)});if(response)throw Error('QA port8876 already in use.')}catch(error){if(!String(error).includes('fetch failed'))throw error}
 fs.mkdirSync(path.join(root,'test-results'),{recursive:true});
 process.env.DAYCRAFT_COMPLETION_DB=path.join(root,'test-results',`completion-e2e-${run}.sqlite`);
 const token=randomUUID(),log=fs.openSync(path.join(root,'test-results',`${process.env.DAYCRAFT_QA_RUN||'completion'}-server.log`),'w');
 const child=spawn(path.join(root,'.venv','Scripts','python.exe'),['-u','e2e/server.py'],{cwd:root,windowsHide:true,stdio:['ignore',log,log],env:{...process.env,SCHEDULE_QA_TOKEN:token,SCHEDULE_BUILDER_DB:process.env.DAYCRAFT_COMPLETION_DB,SCHEDULE_BUILDER_ROUTE_CACHE:path.join(root,'test-results',`completion-routes-${run}.sqlite`),SCHEDULE_BUILDER_OFFLINE:'1'}});
 let ready=false;
 for(let n=0;n<150;n++){try{ready=(await fetch(url,{signal:AbortSignal.timeout(1000)})).ok;if(ready)break}catch{}await new Promise(r=>setTimeout(r,200))}
 if(!ready){child.kill();fs.closeSync(log);throw Error('Completion QA server failed to start; see completion server log.')}
 return async()=>{
  try{await fetch('http://127.0.0.1:8876/__qa_shutdown',{method:'POST',headers:{'x-qa-token':token},signal:AbortSignal.timeout(2000)})}catch{}
  for(let n=0;n<50;n++){try{await fetch(url,{signal:AbortSignal.timeout(1000)})}catch{fs.closeSync(log);return}await new Promise(r=>setTimeout(r,200))}
  child.kill();fs.closeSync(log);throw Error('Completion QA server did not stop cleanly.');
 };
}
