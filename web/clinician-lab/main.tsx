import {createRoot} from 'react-dom/client';
import {EncounterWorkspace} from '../src/EncounterWorkspace';
import {memoryDraftStorage} from '../src/draft-test-fixture';
import {identity,installFixtures} from './fixtures';
import '../src/encounter-workspace.css';
installFixtures();
createRoot(document.getElementById('root')!).render(<>
  <aside style={{padding:'10px 20px',background:'#e7efe9',color:'#203d32',font:'14px system-ui'}}>
    <strong>Clinician usability test · invented patient only.</strong> Real interface with scripted services and saved example drafts.
    Notebook and private review changes stay in this browser tab. The recorder uses simulated audio; your microphone stays off. Account sign-in and external actions are unavailable. Do not enter real information.
  </aside>
  <EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>
</>);
