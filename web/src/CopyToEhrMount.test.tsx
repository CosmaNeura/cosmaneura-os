import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {CopyToEhrMount} from './CopyToEhrMount';
import {taylorMorganPackage} from './copy-to-ehr-fixtures.test-support';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';

let root:Root,host:HTMLDivElement;
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>'token'};
const load=vi.fn();
const write=vi.fn();
const pkg=taylorMorganPackage();

async function render(extra:Partial<Parameters<typeof CopyToEhrMount>[0]>={}){
  await act(async()=>root.render(<CopyToEhrMount identity={identity} draftId={pkg.draft_id}
    expectedRevision={pkg.draft_revision} loadPackage={load} {...extra}/>));
}
async function wait(check:()=>void){
  for(let i=0;i<100;i+=1){
    let done=false;
    await act(async()=>{await new Promise(r=>setTimeout(r,2));try{check();done=true;}catch{/* retry */}});
    if(done)return;
  }
  check();
}
const button=(label:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(item=>item.textContent===label);

beforeEach(()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
  load.mockReset();load.mockResolvedValue(pkg);
  write.mockReset();write.mockResolvedValue(undefined);
  vi.stubGlobal('navigator',{clipboard:{writeText:write}});
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});

it('renders nothing when the flag is off and there is no fallback offer',async()=>{
  await render({enabled:false,fallbackOffer:false});
  expect(host.textContent).toBe('');
  expect(load).not.toHaveBeenCalled();
});

it('loads the package behind the flag and copies without sending the note',async()=>{
  await render({enabled:true});
  await wait(()=>expect(button('Copy full note')).toBeTruthy());
  expect(load).toHaveBeenCalledExactlyOnceWith(identity,pkg.draft_id,'atlas_md',pkg.draft_revision,expect.any(AbortSignal));
  await act(async()=>button('Copy full note')!.click());
  expect(write).toHaveBeenCalledExactlyOnceWith(pkg.full_note);
  expect(host.textContent).not.toMatch(/integrat|sync|write-?back/i);
});

it('stays dark on a 404 (flag off at the API) without blocking the visit',async()=>{
  load.mockRejectedValue(new WorkspaceApiError(404,'copy_to_ehr_unavailable'));
  await render({enabled:true});
  await wait(()=>expect(load).toHaveBeenCalled());
  expect(host.querySelector('.copy-to-ehr-strip')).toBeNull();
  expect(host.querySelector('[role=alert]')).toBeNull();
});

it('shows a visible not-sent notice on a connector-failure offer',async()=>{
  await render({enabled:false,fallbackOffer:true});
  await wait(()=>expect(host.querySelector('.copy-to-ehr-not-sent')).toBeTruthy());
  expect(host.textContent).toContain('This note was not sent');
  await wait(()=>expect(button('Copy full note')).toBeTruthy());
  expect(load).toHaveBeenCalled();
});

it('surfaces a revision mismatch without claiming the note was sent',async()=>{
  load.mockRejectedValue(new WorkspaceApiError(409,'copy_to_ehr_revision_mismatch'));
  await render({enabled:true});
  await wait(()=>expect(host.querySelector('[role=alert]')?.textContent).toContain('This draft changed'));
  expect(host.textContent).not.toMatch(/sent to|synced|wrote back/i);
});
