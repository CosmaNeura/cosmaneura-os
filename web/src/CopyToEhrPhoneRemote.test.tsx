import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {CopyToEhrPhoneRemote} from './CopyToEhrPhoneRemote';
import {copyToEhrRemoteApi} from './copy-to-ehr-remote-api';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
import {WorkspaceApiError} from './workspace-api';

vi.mock('./copy-to-ehr-remote-api',()=>({
  copyToEhrRemoteApi:{
    create:vi.fn(),
    current:vi.fn(),
    highlight:vi.fn(),
    events:vi.fn(),
    end:vi.fn(),
  },
}));

let root:Root;
let host:HTMLDivElement;
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>'synthetic-token'};
const onUseLocalCopy=vi.fn();

beforeEach(()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  onUseLocalCopy.mockReset();
  host=document.createElement('div');
  document.body.append(host);
  root=createRoot(host);
});

afterEach(async()=>{
  await act(async()=>root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function render(props:Partial<Parameters<typeof CopyToEhrPhoneRemote>[0]>={}){
  await act(async()=>root.render(
    <CopyToEhrPhoneRemote
      identity={identity}
      enabled
      onUseLocalCopy={onUseLocalCopy}
      {...props}
    />,
  ));
}

it('offers local Copy to EHR when the computer session is missing',async()=>{
  vi.mocked(copyToEhrRemoteApi.current).mockRejectedValue(new WorkspaceApiError(404,'copy_to_ehr_remote_session_unavailable'));
  await render();
  await act(async()=>{await Promise.resolve();});
  expect(host.textContent).toMatch(/Copy to EHR on this phone/);
  await act(async()=>host.querySelector('button')!.click());
  expect(onUseLocalCopy).toHaveBeenCalledOnce();
});

it('shows highlight controls for an open remote session without note text',async()=>{
  vi.mocked(copyToEhrRemoteApi.current).mockResolvedValue({
    session_id:'11111111-1111-4111-8111-111111111111',
    status:'open',
    draft_id:'22222222-2222-4222-8222-222222222222',
    draft_revision:1,
    section_keys:['subjective','plan'],
    visit_key:'visit-taylor-morgan',
    created_at:'2026-11-09T18:00:00Z',
    last_activity_at:'2026-11-09T18:00:00Z',
    ended_at:null,
    end_reason:null,
  });
  await render();
  await act(async()=>{await Promise.resolve();await Promise.resolve();});
  expect(host.textContent).toMatch(/Highlight Subjective/);
  expect(host.textContent).toMatch(/Highlight Plan/);
  expect(host.textContent).not.toMatch(/sore throat|write-back|sync|integration/i);
});

it('tells the clinician the note was not sent when the remote connection fails',async()=>{
  vi.mocked(copyToEhrRemoteApi.current).mockRejectedValue(new Error('network down'));
  await render();
  await act(async()=>{await Promise.resolve();await Promise.resolve();});
  const alert=host.querySelector('[role="alert"]');
  expect(alert?.textContent).toMatch(/note was not sent/i);
  expect(host.textContent).toMatch(/Copy to EHR on this phone/);
});
