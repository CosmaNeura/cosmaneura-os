import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, readFile, rm} from 'node:fs/promises';
import {join, isAbsolute} from 'node:path';
import {tmpdir} from 'node:os';
import {fileURLToPath} from 'node:url';
import {spawn} from 'node:child_process';

// Supply the existing pinned Electron binary; no download, account, or app profile is used.
const binary=process.env.COSMAS_TEST_ELECTRON_BINARY;
for(const mode of ['app-quit','window-close'])test(`real Electron ${mode} finishes cleanup and exits`,{
  skip:process.platform!=='darwin'||!binary,timeout:15000,
},async()=>{
  assert.ok(isAbsolute(binary));
  const directory=await mkdtemp(join(tmpdir(),'cosmas-window-quit-'));
  await mkdir(join(directory,'state'));
  let child;
  try{
    const exit=await new Promise((resolve,reject)=>{
      child=spawn(binary,[fileURLToPath(new URL('./test-fixtures/window-quit',import.meta.url))],{
        env:{PATH:'/usr/bin:/bin',TMPDIR:tmpdir(),COSMAS_QUIT_TEST_MODE:mode,COSMAS_QUIT_TEST_DIRECTORY:directory},stdio:'ignore',
      });
      const deadline=setTimeout(()=>child.kill('SIGKILL'),10000);
      child.once('error',error=>{clearTimeout(deadline);reject(error);});
      child.once('close',(code,signal)=>{clearTimeout(deadline);resolve({code,signal});});
    });
    const events=(await readFile(join(directory,'events.jsonl'),'utf8')).trim().split('\n').map(line=>JSON.parse(line).event);
    assert.deepEqual(exit,{code:0,signal:null},JSON.stringify(events));
    assert.deepEqual(events,['window-closed','capture-close-start','capture-close-finish','cleanup','quit:0']);
  }finally{
    if(child&&child.exitCode===null&&child.signalCode===null)child.kill('SIGKILL');
    await rm(directory,{recursive:true,force:true});
  }
});
