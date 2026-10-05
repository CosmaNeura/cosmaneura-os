import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect,it,vi} from 'vitest';
import {EncounterSources} from './EncounterSources';
import type {Workspace} from './workspace-api';
it('shows a separate reviewed practice fax and withholds retained text when its source is unavailable',async()=>{
 vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);const host=document.createElement('div'),root=createRoot(host);
 const props={selectedSource:null,locked:false,source:'',evidence:'',setSource:()=>{},setEvidence:()=>{},onSave:()=>{},onNotebook:()=>{}};
 const workspace={entries:[{id:'invented-fax',kind:'fax_inbound_source',revision:4,source_label:'Received practice fax passage (human reviewed)',content:'Invented selected fax passage',created_at:'2026-10-05T12:00:00Z',practice_fax_source_state:'current'}]} as unknown as Workspace;
 try{await act(async()=>root.render(<EncounterSources {...props} workspace={workspace}/>));expect(host.textContent).toContain('Invented selected fax passage');expect(host.textContent).toContain('Reviewed fax passage');
 await act(async()=>root.render(<EncounterSources {...props} workspace={{...workspace,entries:workspace.entries.map(e=>({...e,practice_fax_source_state:'unavailable'}))}}/>));expect(host.textContent).not.toContain('Invented selected fax passage');expect(host.textContent).toContain('This fax passage is unavailable');}
 finally{await act(async()=>root.unmount());vi.unstubAllGlobals();}
});
