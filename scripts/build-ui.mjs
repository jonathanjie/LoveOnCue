import {spawnSync} from 'node:child_process';
import {copyFileSync, existsSync} from 'node:fs';
const compiler=process.env.TSC_PATH || 'node_modules/typescript/bin/tsc';
if(!existsSync(compiler)){console.error('TypeScript is missing. Run npm install, then npm run build:ui.');process.exit(1);}
const result=spawnSync(process.execPath,[compiler,'-p','tsconfig.json'],{stdio:'inherit'});
if(result.status!==0)process.exit(result.status||1);
copyFileSync('web/src/app.css','web/dist/app.css');
