import {createRoot} from 'react-dom/client';
import {EncounterWorkspace} from '../src/EncounterWorkspace';
import {openDraftStore} from '../src/draft-store';
import {identity,installFixtures} from './fixtures';
import '../src/styles.css';
import '../src/encounter-workspace.css';
async function start(){
await installFixtures();
createRoot(document.getElementById('root')!).render(<>
  <aside style={{padding:'10px 20px',background:'#e7efe9',color:'#203d32',font:'14px system-ui'}}>
    <details><summary style={{minHeight:44,alignContent:'center',cursor:'pointer'}}><strong>CosmaBot rehearsal · invented information only</strong></summary>
      <p>Real interface with scripted services. Example saved notes stay in this tab. Working drafts and simulated audio are encrypted in this browser and can be recovered after reload. Your microphone stays off. Account sign-in, public lookups and external delivery are unavailable. Do not enter real information.</p>
    </details>
  </aside>
  <EncounterWorkspace authenticated={identity} draftStorage={options=>openDraftStore({...options,native:false})}/>
</>);

}
void start();
