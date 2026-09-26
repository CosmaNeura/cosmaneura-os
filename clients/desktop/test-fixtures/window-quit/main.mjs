import {app, BrowserWindow, session} from 'electron';
import {appendFileSync} from 'node:fs';
import {join, isAbsolute, relative} from 'node:path';
import {tmpdir} from 'node:os';
import {cleanupOnConfirmedQuit} from '../../close-protection.mjs';
import {installDesktopLastWindowPolicy} from '../../startup-recovery.mjs';

const directory=process.env.COSMAS_QUIT_TEST_DIRECTORY, mode=process.env.COSMAS_QUIT_TEST_MODE;
if(!directory||!isAbsolute(directory)||!relative(tmpdir(),directory).startsWith('cosmas-window-quit-')||
  !['app-quit','window-close'].includes(mode))throw Error('Invalid isolated quit test');
const log=event=>appendFileSync(join(directory,'events.jsonl'),JSON.stringify({event})+'\n');
app.setName('Cosmas isolated quit regression');
app.setPath('userData',join(directory,'state'));app.setPath('sessionData',join(directory,'state'));
app.setActivationPolicy('prohibited');
installDesktopLastWindowPolicy(app,()=>false);
cleanupOnConfirmedQuit(app,()=>log('cleanup'),{beforeCleanup:async()=>{
  log('capture-close-start');await Promise.resolve();await Promise.resolve();log('capture-close-finish');
},onFailure:()=>log('cleanup-failed')});
app.on('quit',(_event,code)=>log('quit:'+code));
void app.whenReady().then(async()=>{
  session.defaultSession.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']},(_request,callback)=>callback({cancel:true}));
  const window=new BrowserWindow({show:false,webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true}});
  window.on('closed',()=>{log('window-closed');app.quit();});
  await window.loadURL('data:text/html,<title>Isolated quit regression</title>');
  setTimeout(()=>{log('watchdog');app.exit(70);},6000);
  if(mode==='app-quit')app.quit();else window.close();
}).catch(()=>{log('startup-failed');app.exit(71);});
