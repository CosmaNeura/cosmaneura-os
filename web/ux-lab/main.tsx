import {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {SettingsHub} from '../src/SettingsHub';
import {MicrosoftConnectionPanel} from '../src/MicrosoftConnectionPanel';
import {AthenaConnectionPanel} from '../src/AthenaConnectionPanel';
import {EhrPreview} from './EhrPreview';
import athenaFixture from '../src/__fixtures__/athena-connection.json';
import {failNextRead,providerRequests} from './provider-fixtures';
import {faxScenarios,setScenario} from './fixtures';
import '../src/encounter-workspace.css';
import './style.css';
const identity={mode:'clerk_jwt' as const,getToken:async()=>null};
function Detail({name}:{name:string}){return <section><h2>{name}</h2><p>This fixture tests the connection directory and navigation. Account sign-in and service content are not simulated here.</p></section>;}
function Lab(){
  const [example,setExample]=useState('mixed'),[mobile,setMobile]=useState(false),[open,setOpen]=useState(true),[navigation,setNavigation]=useState('');
  const faxFixture=example in faxScenarios;
  const providerFixture=example==='microsoft-reads'||example==='athena-retry';
  return <><header className="lab-controls"><strong>CosmaBot · Connection UX lab</strong><span>Synthetic fixtures · no external calls</span><label>Scenario <select value={example} onChange={event=>{setScenario(event.target.value);setExample(event.target.value);setOpen(true);setNavigation('');}}><option value="mixed">Connected and pending</option><option value="new">New account</option><option value="failure">One check fails</option><option value="offline">Offline</option><option value="slow">Slow response</option><option value="microsoft-reads">Microsoft · real panel, invented reads</option><option value="athena-retry">Athena · real panel, invented reads</option>{Object.entries(faxScenarios).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><label><input type="checkbox" checked={mobile} onChange={event=>setMobile(event.target.checked)}/> Phone width</label>{!open&&<button onClick={()=>setOpen(true)}>Open Connections</button>}
      {faxFixture&&<span>Open Messaging &amp; fax to inspect this fixture. Account and readiness values are simulated; no provider was verified.</span>}
      {navigation&&<output role="status" aria-label="Fixture navigation">{navigation}</output>}
    </header>
    <div className="lab-controls"><button onClick={()=>{setExample('microsoft-reads');providerRequests.length=0;}}>Test Microsoft reads</button><button onClick={()=>{setExample('athena-retry');providerRequests.length=0;}}>Test Athena retry</button><button onClick={()=>setExample('elation-review')}>Test Elation review</button>{providerFixture&&<button onClick={failNextRead}>Fail next provider read</button>}</div>
    <main className={`lab-preview team-workspace${mobile?' lab-phone':''}`}>{example==='elation-review'?<EhrPreview/>:example==='microsoft-reads'?<MicrosoftConnectionPanel identity={identity} onAuthenticationLost={()=>setNavigation('Sign-in required')}/>:example==='athena-retry'?<AthenaConnectionPanel identity={identity} connectionSha={athenaFixture.connection.command.connection_sha256} onAccessLost={()=>setNavigation('Practice access changed')}/>:<SettingsHub key={example} open={open} initialScreen="connections" connectionIdentity={identity} guidedConnections team={<Detail name="Team"/>} teamSummary="Five coworkers" teamDirty={false} onClose={()=>setOpen(false)} core={<Detail name="Cosmaneura account"/>} google={<Detail name="Gmail"/>} microsoft={<Detail name="Microsoft"/>} scheduling={<Detail name="Scheduling"/>} messaging={<Detail name="Messaging"/>} payments={<Detail name="Payments"/>} portals={<Detail name="Patient portals"/>}
      onOpenMessagingWork={faxFixture?()=>setNavigation('fax work navigation requested'):undefined}/>}</main></>;
}
createRoot(document.getElementById('root')!).render(<Lab/>);
