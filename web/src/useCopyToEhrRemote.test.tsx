import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {useCopyToEhrRemote} from './useCopyToEhrRemote';
import {copyToEhrRemoteApi,type CopyToEhrRemoteSession} from './copy-to-ehr-remote-api';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';

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
let latest:ReturnType<typeof useCopyToEhrRemote>;
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>'synthetic-token'};

function Probe({enabled=true}:{enabled?:boolean}){
  latest=useCopyToEhrRemote({identity,enabled,role:'phone'});
  return <p data-connection={latest.connection}>{latest.error||latest.noteNotSent?'alert':'ok'}</p>;
}

function session(overrides:Partial<CopyToEhrRemoteSession>={}):CopyToEhrRemoteSession{
  return {
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
    ...overrides,
  };
}

beforeEach(()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
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

async function render(enabled=true){
  await act(async()=>root.render(<Probe enabled={enabled}/>));
}

it('shows that the note was not sent when a highlight fails and never hides the failure',async()=>{
  vi.mocked(copyToEhrRemoteApi.current).mockResolvedValue(session());
  vi.mocked(copyToEhrRemoteApi.highlight).mockRejectedValue(new Error('offline'));
  await render();
  await act(async()=>{await latest.joinCurrentSession();});
  expect(latest.connection).toBe('connected');
  await act(async()=>{await latest.sendHighlight('subjective');});
  expect(latest.noteNotSent).toBe(true);
  expect(latest.error).toMatch(/not sent/i);
  expect(latest.connection).toBe('failed');
});

it('joins the computer session without carrying note text on highlight success',async()=>{
  vi.mocked(copyToEhrRemoteApi.current).mockResolvedValue(session());
  vi.mocked(copyToEhrRemoteApi.highlight).mockResolvedValue({
    seq:1,
    section_key:'subjective',
    draft_revision:1,
    at:'2026-11-09T18:01:00Z',
  });
  await render();
  await act(async()=>{await latest.joinCurrentSession();});
  const ok=await act(async()=>latest.sendHighlight('subjective'));
  expect(ok).toBe(true);
  expect(latest.latestHighlight).toEqual({
    seq:1,
    section_key:'subjective',
    draft_revision:1,
    at:'2026-11-09T18:01:00Z',
  });
  expect(JSON.stringify(latest.latestHighlight)).not.toMatch(/sore throat|Taylor|note_text|full_note/i);
});
