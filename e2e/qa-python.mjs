import {spawnSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

// Opt-in isolated interpreter; no activation or application environment changes.
export function qaPython(root) {
 const interpreter=path.resolve(root,process.env.DAYCRAFT_QA_PYTHON||'.venv/Scripts/python.exe');
 if(!fs.existsSync(interpreter)||!fs.statSync(interpreter).isFile())throw Error(`QA Python does not exist: ${interpreter}`);
 const result=spawnSync(interpreter,['-c','import json,sys; print(json.dumps(list(sys.version_info[:2])))'],{
  cwd:root,windowsHide:true,encoding:'utf8',timeout:10000,
 });
 if(result.error||result.status!==0)throw Error(`QA Python could not run: ${interpreter}: ${result.error?.message||result.stderr||result.status}`);
 let version;try{version=JSON.parse(result.stdout.trim())}catch{throw Error(`QA interpreter did not identify as Python: ${interpreter}`)}
 if(!Array.isArray(version)||version[0]!==3||version[1]<11)throw Error(`QA Python 3.11+ is required: ${interpreter}`);
 return interpreter;
}
