import {createRoot} from 'react-dom/client';
import {useEffect} from 'react';
import {notifyWorkspaceLifecycle} from '../src/workspace-lifecycle';
import {EncounterWorkspace} from '../src/EncounterWorkspace';
import {openDraftStore} from '../src/draft-store';
import {identity,installFixtures} from './fixtures';
import {installTextRehearsal} from './text-rehearsal';
import '../src/styles.css';
import '../src/encounter-workspace.css';
import './rehearsal.css';
function RehearsalReady(){useEffect(()=>{notifyWorkspaceLifecycle('ready');},[]);return null;}
async function start(){
await installFixtures();
const root=document.getElementById('root')!,query=new URLSearchParams(location.search);
root.dataset.nativeRehearsal=String(!!identity.nativeSession);
const stopTextRehearsal=installTextRehearsal(root);import.meta.hot?.dispose(stopTextRehearsal);
createRoot(root).render(<>
  <RehearsalReady/>
  <aside className="rehearsal-notice" style={{padding:'10px 20px',background:'#e7efe9',color:'#203d32',font:'14px system-ui'}}>
    <details><summary style={{minHeight:44,alignContent:'center',cursor:'pointer'}}><strong>CosmaBot rehearsal · invented information only{query.get('text-size')==='200'?' · Text 200%':''}{query.get('long-names')==='1'?' · Long names':''}</strong></summary>
      <p>Real interface with scripted services. Example saved notes stay in this tab. Working drafts and simulated audio are encrypted in this browser and can be recovered after reload. Your microphone stays off. Account sign-in, public lookups and external delivery are unavailable. Do not enter real information.</p>
    </details>
  </aside>
  <EncounterWorkspace authenticated={identity} draftStorage={options=>openDraftStore({...options,native:false})}/>
</>);

}
void start();
