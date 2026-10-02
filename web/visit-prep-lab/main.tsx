import {createRoot} from 'react-dom/client';
import {VisitPrepPackagePanel} from '../src/VisitPrepPackagePanel';
import {workspaceApi} from '../src/workspace-api';
import '../src/encounter-workspace.css';

workspaceApi.team=async()=>({revision:1,configuration:{bots:[{role:'visit_prep',enabled:true,include_evidence:true}]},
  members:[{role:'visit_prep',capabilities:[{key:'core.visit_prep.read',state:'enabled'}]}]} as never);
const identity={mode:'clerk_jwt' as const,getToken:async()=>null};
createRoot(document.getElementById('root')!).render(<main style={{maxWidth:850,margin:'24px auto',padding:'0 12px',fontFamily:'system-ui'}}>
  <aside style={{padding:16,background:'#e7efe9',borderRadius:8}}><strong>Visit Prep branch preview · invented data only</strong>
    <p>This is the real provider panel with scripted Core replies. No login, patient record, AI service, email or SMS is connected. Do not enter real information.</p></aside>
  <VisitPrepPackagePanel identity={identity} locked={false}/>
</main>);
