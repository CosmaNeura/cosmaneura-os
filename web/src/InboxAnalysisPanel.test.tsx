import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {InboxAnalysisPanel} from './InboxAnalysisPanel';
import {inboxDraftSelection} from './inbox-analysis-contract';
import {inboxFixture} from './inbox-test-fixture';
import actual from './__fixtures__/inbox-analysis-w87.json';
import type {ProviderTeam,Workspace} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let root:Root,element:HTMLDivElement;
const submit=vi.fn(async(_body:import('./workspace-api').ConversationInput)=>{});
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);submit.mockClear();element=document.createElement('div');document.body.append(element);root=createRoot(element);});
afterEach(async()=>{await act(async()=>root.unmount());element.remove();vi.unstubAllGlobals();});
async function mount(changed=false){const selection=inboxDraftSelection(await inboxFixture('triaged'))!;
  const team=actual.setup.team as ProviderTeam,bot=team.configuration.bots.find(b=>b.skills?.includes('inbox_review'))!;
  const workspace={...actual.workspace,id:selection.workspace_id,revision:selection.expected_revision+(changed?1:0)} as Workspace;
  await act(async()=>root.render(<InboxAnalysisPanel selection={selection} workspace={workspace} team={team} selected={bot.instance_id!} locked={false} onSelect={()=>{}} onSubmit={submit} onClose={()=>{}} onSetup={()=>{}}/>));return selection;
}
it('requires consent and dispatches one exact selected draft even under repeated clicks',async()=>{
  const selection=await mount();const create=()=>[...element.querySelectorAll('button')].find(b=>b.textContent==='Create private draft')!;
  expect(create().disabled).toBe(true);expect(submit).not.toHaveBeenCalled();
  await act(async()=>element.querySelector('input')!.click());const button=create();
  await act(async()=>{button.click();button.click();});expect(submit).toHaveBeenCalledTimes(1);
  expect(submit.mock.calls[0][0]).toMatchObject({expected_revision:selection.expected_revision,inbox_analysis:{...selection.analysis,consented:true}});
});
it('withholds an outdated encounter selection before model dispatch',async()=>{
  await mount(true);expect(element.textContent).toContain('The encounter changed');expect(element.querySelector('input')!.disabled).toBe(true);expect(submit).not.toHaveBeenCalled();
});
