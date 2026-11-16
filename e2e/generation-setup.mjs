import {spawn} from 'node:child_process';
import path from 'node:path';
import fs from 'node:fs';
import {randomUUID} from 'node:crypto';
import {qaPython} from './qa-python.mjs';

export default async function setup(){
 const root=path.resolve(import.meta.dirname,'..'),run=Date.now(),url='http://127.0.0.1:8876/health';
 const python=qaPython(root);
 const source=process.env.DAYCRAFT_GENERATION_SOURCE_DB;
 if(!source)throw Error('Set DAYCRAFT_GENERATION_SOURCE_DB to a consistent SQLite backup. The personal database is never opened for writes.');
 try{const response=await fetch(url,{signal:AbortSignal.timeout(1000)});if(response)throw Error('QA port8876 already in use.')}catch(error){if(!String(error).includes('fetch failed'))throw error}
 const dir=path.join(root,'test-results','generation-repair');fs.mkdirSync(dir,{recursive:true});
 const database=path.join(dir,`generation-e2e-${run}.sqlite`);
 fs.copyFileSync(path.resolve(source),database,fs.constants.COPYFILE_EXCL);
 const token=randomUUID(),log=fs.openSync(path.join(dir,'browser-server.log'),'w');
 const child=spawn(python,['-u','e2e/server.py'],{cwd:root,windowsHide:true,stdio:['ignore',log,log],env:{...process.env,SCHEDULE_QA_TOKEN:token,SCHEDULE_BUILDER_DB:database,SCHEDULE_BUILDER_ROUTE_CACHE:path.join(dir,`routes-${run}.sqlite`),SCHEDULE_BUILDER_OFFLINE:'1'}});
 let ready=false;
 for(let n=0;n<150;n++){try{ready=(await fetch(url,{signal:AbortSignal.timeout(1000)})).ok;if(ready)break}catch{}await new Promise(r=>setTimeout(r,200))}
 if(!ready){child.kill();fs.closeSync(log);throw Error('Generation QA server failed to start; see generation-repair/browser-server.log.')}
 return async()=>{
  try{await fetch('http://127.0.0.1:8876/__qa_shutdown',{method:'POST',headers:{'x-qa-token':token},signal:AbortSignal.timeout(2000)})}catch{}
  for(let n=0;n<50;n++){try{await fetch(url,{signal:AbortSignal.timeout(1000)})}catch{fs.closeSync(log);return}await new Promise(r=>setTimeout(r,200))}
  child.kill();fs.closeSync(log);throw Error('Generation QA server did not stop cleanly.');
 };
}
