import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {PracticeHome} from './PracticeHome';
import {WorkspaceStartupShell} from './WorkspaceStartupShell';
import {DraftJournal} from './draft-journal';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {openDraftStore} from './draft-store';
import type {AccountRecoveryAccess} from './account-recovery';
import {workspaceApi,type ProviderTeam} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const id=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const team:ProviderTeam={revision:1,recovery_scope:'a'.repeat(64),template_version:'provider-team-v1',llm:{enabled:false,model:'gpt-4.1'},configuration:{practice_context:'',bots:[{role:'chief',name:'Chief',enabled:true,response_style:'brief',include_notebook:true,include_evidence:true}]},members:[{role:'chief',agent_id:id(10),name:'Chief',initials:'Ch',description:'Prepare private drafts',prompt:'Saved context',capabilities:[]}]};

function associated(container:ParentNode,labelText:string){
  const label=[...container.querySelectorAll('label')].find(item=>item.textContent?.includes(labelText));
  expect(label,labelText).toBeTruthy();
  expect(label!.htmlFor,`${labelText} htmlFor`).toBeTruthy();
  const control=document.getElementById(label!.htmlFor);
  expect(control,`${labelText} control`).toBeTruthy();
  expect(control).toBeInstanceOf(HTMLElement);
  return control as HTMLInputElement|HTMLTextAreaElement|HTMLSelectElement;
}

describe('form label htmlFor associations',()=>{
  let root:Root,container:HTMLDivElement,recovery:AccountRecoveryAccess;
  const identity={mode:'clerk_jwt' as const,getToken:vi.fn()};
  beforeEach(async()=>{
    Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.stubGlobal('crypto',webcrypto);
    vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);
    vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
    recovery={journal:new DraftJournal(await openDraftStore({scope:'a'.repeat(64),native:false,indexedDB:new IDBFactory(),crypto:webcrypto})),authorize:vi.fn().mockResolvedValue(undefined)};
    vi.spyOn(workspaceApi,'catalog').mockResolvedValue([]);
    vi.spyOn(workspaceApi,'privateDraftSummaries').mockResolvedValue({contract_version:2,drafts:[],has_more:false});
    container=document.createElement('div');document.body.append(container);root=createRoot(container);
  });
  afterEach(async()=>{await act(async()=>root.unmount());recovery.journal.close();container.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});

  it('associates Practice Home note title and search inputs with htmlFor/id and autocomplete',async()=>{
    await act(async()=>root.render(<PracticeHome identity={identity} recovery={recovery} team={team} locked={false} onUseTeam={vi.fn()} onSettings={vi.fn()} onVisits={vi.fn()} onConnections={vi.fn()} onPracticeWork={vi.fn()} onOpened={vi.fn()} onAccessLost={vi.fn()} onBusyChange={vi.fn()}/>));
    await vi.waitFor(()=>expect(vi.mocked(workspaceApi.privateDraftSummaries)).toHaveBeenCalled());
    const title=associated(container,'Note title');
    expect(title.getAttribute('autoComplete')??title.getAttribute('autocomplete')).toBe('off');
    const search=associated(container,'Search notes');
    expect(search.getAttribute('type')).toBe('search');
    expect(search.getAttribute('autoComplete')??search.getAttribute('autocomplete')).toBe('off');
    const needsReview=associated(container,'Needs review');
    expect(needsReview.getAttribute('type')).toBe('checkbox');
  });

  it('associates the startup shell note title field',async()=>{
    await act(async()=>root.render(<WorkspaceStartupShell status="Checking practice access…"/>));
    const title=associated(container,'Note title');
    expect(title.id).toBe('startup-note-title');
    expect(title.getAttribute('autoComplete')??title.getAttribute('autocomplete')).toBe('off');
  });
});
