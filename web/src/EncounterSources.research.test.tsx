import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect,it,vi} from 'vitest';
import {EncounterSources} from './EncounterSources';
import type {Workspace,WorkspaceEntry} from './workspace-api';
import {teamUuid} from './team-setup-test-fixture';

it('distinguishes a proven saved Research snapshot from an ordinary reference with the same label and text',async()=>{
 vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 try{
  const packet:WorkspaceEntry={id:teamUuid(501),revision:2,kind:'evidence',content:'Invented public excerpt.',source_label:'Research · public source excerpts',origin:'authenticated_human',ticket:null,created_at:'2026-10-25T12:00:00Z',research_packet:{contract:'research.saved_packet_marker.v1',run_id:teamUuid(502),entry_id:teamUuid(501),entry_revision:2}},ordinary={...packet,id:teamUuid(503),revision:3,research_packet:undefined},invalid={...packet,id:teamUuid(504),revision:4};const workspace:Workspace={id:teamUuid(500),appointment_id:null,label:'Invented visit',revision:4,entries:[packet,ordinary,invalid],work_candidates:[]};
  await act(async()=>root.render(<EncounterSources workspace={workspace} selectedSource={packet.id} locked={false} source="" evidence="" setSource={()=>{}} setEvidence={()=>{}} onSave={()=>{}} onNotebook={()=>{}}/>));
  expect(host.querySelector('section[aria-label="Saved sources"] h2')?.textContent).toBe('Saved visit sources');expect(host.querySelector('[aria-label="Scribe sources"]')).toBeNull();
  expect(host.querySelector('#source-'+packet.id)?.textContent).toContain('Saved public Research snapshot · source claims require review');for(const entry of [ordinary,invalid]){expect(host.querySelector('#source-'+entry.id)?.textContent).toContain('Reference note · entered by you, unverified');expect(host.querySelector('#source-'+entry.id)?.textContent).toContain(entry.content);expect(host.querySelector('#source-'+entry.id)?.textContent).not.toContain('Saved public Research snapshot');}
 }finally{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();}
});
