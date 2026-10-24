import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_MESSAGES_ENABLED','true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {workspaceApi,WorkspaceApiError} from './workspace-api';
import {handoffReviewHash,type HandoffReviewInput} from './handoff-review-api';
import {memoryDraftStorage} from './draft-test-fixture';
import {DraftJournal} from './draft-journal';
import {PRESENTATION_KEY} from './session/presentation';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let root:Root,host:HTMLDivElement;
const visible=(element:Element)=>!element.closest('[hidden]');
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(item=>visible(item)&&item.textContent?.trim()===name);
const click=async(name:string)=>{await vi.waitFor(()=>expect(button(name)).toBeTruthy());await act(async()=>button(name)!.click());};
const input=async(element:HTMLTextAreaElement,value:string)=>{await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(element,value);element.dispatchEvent(new Event('input',{bubbles:true}));});};
beforeEach(async()=>{
  vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);localStorage.clear();history.replaceState(null,'','#cosmas/home');
  window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();
  await installFixtures(true);host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
async function open(mode:'messages'|'workspace'){
  localStorage.setItem(PRESENTATION_KEY,mode);await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));
  if(mode==='messages'){
    await vi.waitFor(()=>expect(host.querySelector('.messages-row')).toBeTruthy());await act(async()=>(host.querySelector('.messages-row') as HTMLButtonElement).click());
  }else{
    await vi.waitFor(()=>expect(host.querySelector('.notebook-list-row .practice-home-note')).toBeTruthy());await act(async()=>(host.querySelector('.notebook-list-row .practice-home-note') as HTMLButtonElement).click());
    await vi.waitFor(()=>expect(host.querySelector('#team-question')).toBeTruthy());await act(async()=>{const chief=[...host.querySelectorAll<HTMLButtonElement>('.team-roster button')].find(item=>item.textContent?.includes('Chief of Staff'));chief!.click();});
  }
  await vi.waitFor(()=>expect((host.querySelector('#team-question') as HTMLTextAreaElement)?.disabled).toBe(false));
}
describe('presentation parity',()=>{
  it.each(['messages','workspace'] as const)('uses the same save and message actions from %s',async mode=>{
    await open(mode);
    expect([...host.querySelectorAll('.conversation-review-card')].map(item=>item.getAttribute('aria-label'))).toEqual(['Visit Prep draft','Scribe draft','Follow-up draft']);
    const append=vi.spyOn(workspaceApi,'append'),ask=vi.spyOn(workspaceApi,'ask');
    if(mode==='messages'){await click('Details');await click('Notebook and recording');}else await click('Private note');
    await input(host.querySelector('#team-notebook')!,'Invented jottings for parity.');await click('Save notebook revision');
    await vi.waitFor(()=>expect(append).toHaveBeenCalledOnce());expect(append.mock.calls[0][2]).toMatchObject({expected_revision:5,kind:'scratchpad',content:'Invented jottings for parity.'});
    await vi.waitFor(()=>expect(button('Save notebook revision')!.disabled).toBe(true));
    if(mode==='messages')await click('‹ Back to chat');else await click('Conversation');
    const composer=host.querySelector<HTMLTextAreaElement>('#team-question')!;await input(composer,'Review these invented notes.');
    await act(async()=>composer.closest('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
    await vi.waitFor(()=>expect(ask).toHaveBeenCalledOnce());expect(ask.mock.calls[0][2]).toMatchObject({expected_revision:6,role:'chief',content:'Review these invented notes.'});
    expect(ask.mock.calls[0][2].idempotency_key).toMatch(/^[a-f0-9-]{36}$/);
    await vi.waitFor(()=>expect(composer.value).toBe(''));
  });
  it('focuses a Details task and restores the reader position on return',async()=>{
    await open('messages');const history=host.querySelector<HTMLDivElement>('.mobile-chat-scroll')!;
    history.scrollTop=120;await act(async()=>history.dispatchEvent(new Event('scroll',{bubbles:true})));
    await click('Details');await click('Team activity and drafts');
    expect(document.activeElement).toBe(host.querySelector('.messages-thread-header h1'));
    expect(document.activeElement?.textContent).toBe('Activity');expect(history.scrollTop).toBe(0);
    await click('‹ Back to chat');expect(history.scrollTop).toBe(120);
  });
  it('cannot send the previous bot draft while an inbox conversation restores',async()=>{
    await open('messages');const chief='Keep Chief draft when opening Follow-up.',followUp='Send only this separate invented Follow-up draft.';
    const composer=host.querySelector<HTMLTextAreaElement>('#team-question')!;
    await input(composer,chief);await click('‹ Messages');await click('New message');
    await act(async()=>{[...host.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')].find(item=>item.querySelector('strong')?.textContent==='Follow-up')!.click();});
    await vi.waitFor(()=>expect([...host.querySelectorAll<HTMLButtonElement>('.notebook-list-row .practice-home-note')].find(visible)).toBeTruthy());
    await act(async()=>{[...host.querySelectorAll<HTMLButtonElement>('.notebook-list-row .practice-home-note')].find(visible)!.click();});
    await vi.waitFor(()=>expect(composer.disabled).toBe(false));await input(composer,followUp);await click('‹ Messages');
    const row=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('.messages-row')].find(item=>item.querySelector('strong')?.textContent?.startsWith(name));
    await vi.waitFor(()=>expect(row('Chief of Staff')).toBeTruthy());await act(async()=>row('Chief of Staff')!.click());
    await vi.waitFor(()=>expect(composer.value).toBe(chief));await click('‹ Messages');
    const load=DraftJournal.prototype.load,ask=vi.spyOn(workspaceApi,'ask');let release!:()=>void;
    const held=new Promise<void>(resolve=>{release=resolve;});vi.spyOn(DraftJournal.prototype,'load').mockImplementation(async function(this:DraftJournal,address){if(address.endsWith(':conversation:follow_up'))await held;return load.call(this,address);});
    await vi.waitFor(()=>expect(row('Follow-up')).toBeTruthy());await act(async()=>row('Follow-up')!.click());
    try{
      await vi.waitFor(()=>expect(host.querySelector('.messages-thread-header h1')?.textContent).toBe('Follow-up'));
      expect(composer.disabled).toBe(true);expect(composer.value).toBe(chief);
      expect(host.querySelector<HTMLButtonElement>('.team-send')!.disabled).toBe(true);
      await act(async()=>{composer.closest('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));composer.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));});
      expect(ask).not.toHaveBeenCalled();
    }finally{await act(async()=>release());}
    await vi.waitFor(()=>expect(composer.disabled).toBe(false));expect(composer.value).toBe(followUp);
    await act(async()=>composer.closest('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
    await vi.waitFor(()=>expect(ask).toHaveBeenCalledOnce());expect(ask.mock.calls[0][2]).toMatchObject({role:'follow_up',content:followUp});
  });
  it('switches layouts without replacing the composer or notebook editor',async()=>{
    await open('messages');const composer=host.querySelector<HTMLTextAreaElement>('#team-question')!,notebook=host.querySelector('#team-notebook');await input(composer,'Keep this invented draft.');
    await click('Settings');await act(async()=>{(host.querySelector('input[name="cosmas-layout"]:not(:checked)') as HTMLInputElement).click();});await click('Done');
    expect(host.querySelector('main')?.getAttribute('data-presentation')).toBe('workspace');expect(host.querySelector('#team-question')).toBe(composer);expect(host.querySelector('#team-notebook')).toBe(notebook);expect(composer.value).toBe('Keep this invented draft.');
    await click('Settings');await act(async()=>{(host.querySelector('input[name="cosmas-layout"]:not(:checked)') as HTMLInputElement).click();});await click('Done');
    expect(host.querySelector('#team-question')).toBe(composer);expect(composer.value).toBe('Keep this invented draft.');
  });
  it.each(['messages','workspace'] as const)('reviews the exact saved draft and returns to the originating chat from %s',async mode=>{
    await open(mode);const composer=host.querySelector<HTMLTextAreaElement>('#team-question')!;await input(composer,'Keep my Chief directions.');
    const fetch=window.fetch;let envelope:unknown;const send=vi.spyOn(window,'fetch').mockImplementation(async(...args)=>{const response=await fetch(...args);envelope=await response.clone().json();return response;});
    const card=host.querySelectorAll('.conversation-review-card')[2];await act(async()=>card.querySelector<HTMLButtonElement>('button')!.click());
    await vi.waitFor(()=>expect(button('Accept draft for next work')?.disabled).toBe(false));
    expect(host.querySelector('.handoff-review-context')?.textContent).toBe('Jordan · sleep diary follow-up');
    await click('Accept draft for next work');await vi.waitFor(()=>expect(host.querySelector('.handoff-review')?.textContent).toContain('Draft accepted'));
    const [url,request]=send.mock.calls[0],body=JSON.parse(request!.body as string) as HandoffReviewInput;
    expect(body).toMatchObject({expected_revision:5,decision:'accepted',feedback:''});
    const path=new URL(String(url)).pathname.split('/'),workspaceId=path[2],handoffId=path[4];
    const saved=await workspaceApi.read(identity,workspaceId),handoff=saved.handoffs!.find(item=>item.id===handoffId)!;
    expect(body).toMatchObject({attempt_id:handoff.attempt_id,result_entry_id:handoff.result_entry_id,result_sha256:handoff.result_sha256});
    expect((envelope as {request_sha256:string}).request_sha256).toBe(await handoffReviewHash(workspaceId,handoffId,body));
    await click('Back to chat');expect(host.querySelector('#team-question')).toBe(composer);expect(composer.value).toBe('Keep my Chief directions.');
    expect(host.querySelector('.handoff-review')).toBeNull();
    expect(host.querySelectorAll('.conversation-review-card')[2].textContent).toContain('Draft accepted');
  });
  it.each(['messages','workspace'] as const)('retains change feedback and prepares a bound revision from %s',async mode=>{
    await open(mode);const send=vi.spyOn(window,'fetch');await act(async()=>host.querySelector<HTMLButtonElement>('.conversation-review-card button')!.click());
    await vi.waitFor(()=>expect(button('Request changes')?.disabled).toBe(false));await click('Request changes');
    await input(host.querySelector<HTMLTextAreaElement>('textarea[aria-label="Change request"]')!,'Clarify the invented contact preference.');
    await click('Save change request');await vi.waitFor(()=>expect(button('Prepare revised draft')?.disabled).toBe(false));
    await click('Prepare revised draft');await vi.waitFor(()=>expect(host.querySelector('.handoff-review')?.textContent).toContain('Draft queued'));
    const reviewBody=JSON.parse(send.mock.calls[0][1]!.body as string),revisionBody=JSON.parse(send.mock.calls[1][1]!.body as string),wid=new URL(String(send.mock.calls[0][0])).pathname.split('/')[2];
    const saved=await workspaceApi.read(identity,wid),parent=saved.handoffs!.find(item=>item.review?.decision==='changes_requested')!,revision=saved.handoffs!.find(item=>item.id===parent.review!.revision_handoff_id)!;
    expect(revisionBody).toMatchObject({expected_revision:6,review_id:parent.review!.id});expect(revision.revision_request).toMatchObject({parent_handoff_id:parent.id,review_id:parent.review!.id,result_sha256:reviewBody.result_sha256,feedback:'Clarify the invented contact preference.'});
    expect(button('Accept draft for next work')?.disabled).toBe(true);
    await click('Back to chat');expect(host.querySelector('.handoff-review')).toBeNull();
  });
  it.each(['messages','workspace'] as const)('replays the same save after a lost response from %s',async mode=>{
    await open(mode);const append=workspaceApi.append;let lost=false;
    const save=vi.spyOn(workspaceApi,'append').mockImplementation(async(...args)=>{const result=await append(...args);if(!lost){lost=true;throw new WorkspaceApiError(503);}return result;});
    if(mode==='messages'){await click('Details');await click('Notebook and recording');}else await click('Private note');
    await input(host.querySelector('#team-notebook')!,'Save these invented notes exactly once.');await click('Save notebook revision');
    await vi.waitFor(()=>expect(button('Retry same save')?.disabled).toBe(false));
    const first=structuredClone(save.mock.calls[0][2]);await click('Retry same save');await vi.waitFor(()=>expect(save).toHaveBeenCalledTimes(2));
    expect(save.mock.calls[1][2]).toEqual(first);await vi.waitFor(()=>expect(button('Retry same save')).toBeUndefined());
    const stored=await workspaceApi.read(identity,save.mock.calls[0][1]);expect(stored.entries.filter(entry=>entry.content===first.content)).toHaveLength(1);
  });

});
