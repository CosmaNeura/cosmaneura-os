import {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {SettingsHub} from '../src/SettingsHub';
import {setScenario} from './fixtures';
import '../src/encounter-workspace.css';
import './style.css';
const identity={mode:'clerk_jwt' as const,getToken:async()=>null};
function Detail({name}:{name:string}){return <section><h2>{name}</h2><p>This fixture tests the connection directory and navigation. Account sign-in and service content are not simulated here.</p></section>;}
function Lab(){
  const [example,setExample]=useState('mixed'),[mobile,setMobile]=useState(false),[open,setOpen]=useState(true);
  return <><header className="lab-controls"><strong>CosmaBot · Connection UX lab</strong><span>Synthetic fixtures · no external calls</span><label>Scenario <select value={example} onChange={event=>{setScenario(event.target.value);setExample(event.target.value);setOpen(true);}}><option value="mixed">Connected and pending</option><option value="new">New account</option><option value="failure">One check fails</option><option value="offline">Offline</option><option value="slow">Slow response</option></select></label><label><input type="checkbox" checked={mobile} onChange={event=>setMobile(event.target.checked)}/> Phone width</label>{!open&&<button onClick={()=>setOpen(true)}>Open Connections</button>}</header>
    <main className={`lab-preview team-workspace${mobile?' lab-phone':''}`}><SettingsHub key={example} open={open} initialScreen="connections" connectionIdentity={identity} guidedConnections team={<Detail name="Team"/>} teamSummary="Five coworkers" teamDirty={false} onClose={()=>setOpen(false)} core={<Detail name="Cosmaneura account"/>} google={<Detail name="Gmail"/>} microsoft={<Detail name="Microsoft"/>} scheduling={<Detail name="Scheduling"/>} messaging={<Detail name="Messaging"/>} payments={<Detail name="Payments"/>} portals={<Detail name="Patient portals"/>}/></main></>;
}
createRoot(document.getElementById('root')!).render(<Lab/>);
