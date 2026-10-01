import {createRoot} from 'react-dom/client';
import {EncounterWorkspace} from '../src/EncounterWorkspace';
import {memoryDraftStorage} from '../src/draft-test-fixture';
import {identity, installLiveBridge} from './bridge';
import '../src/encounter-workspace.css';

const root = createRoot(document.getElementById('root')!);
root.render(<p role="status" style={{padding: 24, fontFamily: 'system-ui'}}>Opening your local clinician test…</p>);
void installLiveBridge().then(session => {
  root.render(<>
    <aside style={{padding: '10px 20px', background: '#e7efe9', color: '#203d32', font: '14px system-ui'}}>
      <strong>Clinician test · {session.persona === 'nurse' ? 'RN' : session.persona === 'pa' ? 'PA' : 'Provider'} · round {session.round} · invented patient only.</strong>{' '}
      Notebook saves and team drafts use this local test session. Recording, public lookup, and external actions are unavailable. Only enter the supplied invented information.
    </aside>
    <EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>
  </>);
}).catch(() => {
  root.render(<main style={{padding: 24, fontFamily: 'system-ui'}}>
    <h1>Clinician test unavailable</h1>
    <p role="alert">The local test session could not be confirmed. Open a supplied test link and check that the local session service is running.</p>
    <button onClick={() => window.location.reload()}>Try again</button>
  </main>);
});
