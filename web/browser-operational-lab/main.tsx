import React from 'react';
import {createRoot} from 'react-dom/client';
import {EncounterWorkspace} from '../src/EncounterWorkspace';
import {workspaceApi} from '../src/workspace-api';
import {emit,evidence} from './capture-source';
import '../src/styles.css';
const base=import.meta.env.VITE_API_BASE,params=new URLSearchParams(location.search);
const packet=(window as typeof window&{operationalSeed?:{workspace:{id:string};token:string}}).operationalSeed??await fetch(`${base}/lab/case?persona=${params.get('persona')}&round=${params.get('round')}`).then(r=>{if(!r.ok)throw new Error('Seed failed');return r.json();});
const identity={mode:'clerk_jwt' as const,getToken:async()=>packet.token};
let root=createRoot(document.getElementById('root')!);
function mount(){root.render(<EncounterWorkspace authenticated={identity}/>);}
const lab={packet:{workspace:packet.workspace},read:()=>workspaceApi.read(identity,packet.workspace.id),work:async()=>{const r=await fetch(`${base}/lab/work`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workspace_id:packet.workspace.id})});if(!r.ok)throw new Error(await r.text());return r.json();},inspect:()=>fetch(`${base}/lab/inspect?workspace_id=${packet.workspace.id}`).then(r=>r.json()),emit,evidence,reopen:async()=>{root.unmount();await new Promise(r=>setTimeout(r,20));root=createRoot(document.getElementById('root')!);mount();}};
Object.assign(window,{operationalLab:lab});mount();
