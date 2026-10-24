import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_MESSAGES_ENABLED','true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');});
const observedSession=vi.hoisted(()=>({value:null as import('./session/workspace-session').WorkspaceSession|null}));
vi.mock('./session/use-workspace-session',async importOriginal=>{const original=await importOriginal<typeof import('./session/use-workspace-session')>();return {...original,useWorkspaceSession:(...args:Parameters<typeof original.useWorkspaceSession>)=>{observedSession.value=args[0];return original.useWorkspaceSession(...args);}};});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {workspaceApi,WorkspaceApiError} from './workspace-api';
import {handoffReviewHash,type HandoffReviewInput} from './handoff-review-api';
import {memoryDraftStorage} from './draft-test-fixture';
import {DraftJournal} from './draft-journal';
import {PRESENTATION_KEY} from './session/presentation';
import {conversationsApi} from './conversations-api';
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
  it.each(['empty','unconfirmed request','active model request','draft awaiting review','edited draft','handoff pending','recording saved'] as const)('compares the same session across both layouts: %s',async scenario=>{
    await open('messages');const session=observedSession.value!,base=structuredClone(session.getSnapshot().workspace!);
    const chief=base.entries.find(entry=>entry.kind==='conversation')!,handoff=base.handoffs![0],team=session.getSnapshot().team!;
    const next=structuredClone(base);next.handoffs=[];
    const pending=scenario==='unconfirmed request'?{type:'ask' as const,body:{expected_revision:base.revision,team_revision:team.revision,idempotency_key:crypto.randomUUID(),role:'chief',content:'Retained invented request'}}:null;
    if(scenario==='empty'||scenario==='unconfirmed request')next.entries=next.entries.filter(entry=>!['conversation','handoff_result'].includes(entry.kind));
    if(scenario==='active model request'){
      const turn=next.entries.find(entry=>entry.id===chief.id)!;turn.reply=null;turn.model_request={contract_version:1,request_sha256:'a'.repeat(64),request:{kind:'conversation',expected_revision:1,team_revision:team.revision,idempotency_key:crypto.randomUUID(),role:'chief'},
        bot:{address:'chief',agent_id:chief.reply!.agent_id!,role:'chief',name:'Chief of Staff',team_revision:team.revision},reason:null,
        admission:{id:crypto.randomUUID(),state:'running',unit:1,admitted_at:chief.created_at,dispatch:'started',usage:'unknown',input_tokens:null,output_tokens:null}};
    }
    if(['draft awaiting review','edited draft','handoff pending'].includes(scenario)){
      next.handoffs=[structuredClone(handoff)];
      if(scenario==='edited draft')next.handoffs[0].review_status='stale';
      if(scenario==='handoff pending')Object.assign(next.handoffs[0],{status:'queued',result_entry_id:null,result_sha256:null,review:null,review_status:'not_reviewed',attempts:[]});
    }
    const recording=scenario==='recording saved'?{identity,scope:session.recovery.journal.current!.scope,generation:session.generation.current,rows:[{recordingId:crypto.randomUUID(),title:'Invented saved recording',phase:'sealed' as const,elapsedSeconds:18,recordedChunks:18,recordedBytes:5760792,workspaceId:base.id,busy:false,localOnly:true as const,transcription:'not_requested' as const,failure:null,startupStage:null}]}:null;
    await act(async()=>{session.setWorkspace(next);session.setPending(pending);session.setPrivateRecordings(recording);});
    const expectedIds=scenario==='empty'||scenario==='unconfirmed request'?[]:[chief.id,...(['draft awaiting review','edited draft','handoff pending'].includes(scenario)?[`handoff:${handoff.id}`]:[])];
    const expectedAttention=scenario==='draft awaiting review'?['Unreviewed draft']:scenario==='edited draft'?['Review needs updating']:scenario==='handoff pending'?['Queued']:[];
    const surface=()=>({
      entries:[...host.querySelectorAll('.team-messages [data-entry-id]')].map(node=>node.getAttribute('data-entry-id')),
      attention:[...host.querySelectorAll('.team-messages .conversation-review-card [role=status]')].map(node=>node.textContent),
      actions:[...host.querySelectorAll<HTMLButtonElement>('.team-messages [data-action]')].map(node=>[node.dataset.action,node.disabled]),
      delivery:[...host.querySelectorAll('.team-messages [data-delivery]')].map(node=>[node.getAttribute('data-entry-id'),node.getAttribute('data-delivery')]),
      unconfirmed:host.querySelector('.team-recovery[aria-label="Unconfirmed model request"]')?.textContent??null,
      inProgress:host.textContent?.includes('Request in progress')??false,
    });
    const messages=surface();expect(messages.entries).toEqual(expectedIds);expect(messages.attention).toEqual(expectedAttention);
    expect(messages.delivery).toEqual(scenario==='empty'||scenario==='unconfirmed request'?[]:[[chief.id,'delivered']]);
    if(scenario==='active model request'){expect(messages.inProgress).toBe(true);expect(messages.actions).toEqual([['check_request',false]]);}
    if(scenario==='unconfirmed request'){expect(messages.unconfirmed).toContain('unconfirmed');expect(session.presentation.choose('workspace',false)).toBe(false);}
    // Fixture rendering can inspect both views of a blocked session without
    // invoking the user-facing switch or changing its admission rules.
    await act(async()=>session.setPresentationPreference('workspace'));expect(surface()).toEqual(messages);expect(observedSession.value).toBe(session);
    expect(session.getSnapshot().pending).toBe(pending);expect(session.getSnapshot().privateRecordings).toBe(recording);
    await act(async()=>session.setPresentationPreference('messages'));expect(surface()).toEqual(messages);
    if(recording)expect(recording.rows[0]).toMatchObject({phase:'sealed',recordedChunks:18,elapsedSeconds:18,transcription:'not_requested'});
  });
  it('does not announce historical review changes or new review cards as incoming messages',async()=>{
    vi.spyOn(HTMLElement.prototype,'clientHeight','get').mockImplementation(function(this:HTMLElement){return this.classList.contains('mobile-chat-scroll')?200:0;});
    vi.spyOn(HTMLElement.prototype,'scrollHeight','get').mockImplementation(function(this:HTMLElement){return this.classList.contains('mobile-chat-scroll')?1000:0;});
    await open('messages');const session=observedSession.value!,history=host.querySelector<HTMLDivElement>('.mobile-chat-scroll')!;
    await act(async()=>{history.scrollTop=200;history.dispatchEvent(new Event('scroll',{bubbles:true}));});
    const mark=vi.spyOn(conversationsApi,'mark'),updated=structuredClone(session.getSnapshot().workspace!),handoff=updated.handoffs![0];
    const card=()=>host.querySelector(`[data-entry-id="handoff:${handoff.id}"]`)!;
    expect(card().textContent).toContain('Unreviewed draft');
    handoff.review_status='current';handoff.review={id:crypto.randomUUID(),attempt_id:handoff.attempt_id!,result_entry_id:handoff.result_entry_id!,result_sha256:handoff.result_sha256!,decision:'accepted',feedback:'',created_at:'2026-10-24T12:00:00Z'};
    await act(async()=>session.setWorkspace(updated));
    expect(card().textContent).toContain('Draft accepted');expect(history.scrollTop).toBe(200);
    expect(host.querySelector('.messages-new-replies')).toBeNull();expect(mark).not.toHaveBeenCalled();
    const withNewCard=structuredClone(updated),newHandoff={...structuredClone(handoff),id:crypto.randomUUID(),review:undefined,review_status:'not_reviewed' as const};
    withNewCard.handoffs!.push(newHandoff);await act(async()=>session.setWorkspace(withNewCard));
    const added=host.querySelector(`[data-entry-id="handoff:${newHandoff.id}"]`)!;
    expect(added.textContent).toContain('Unreviewed draft');expect(added.querySelector('button')?.textContent).toBe('Review draft');
    expect(history.scrollTop).toBe(200);expect(host.querySelector('.messages-new-replies')).toBeNull();expect(mark).not.toHaveBeenCalled();
  });
  it('keeps a new reply unread above the bottom and acknowledges its exact watermark after jumping',async()=>{
    vi.spyOn(HTMLElement.prototype,'clientHeight','get').mockImplementation(function(this:HTMLElement){return this.classList.contains('mobile-chat-scroll')?200:0;});
    vi.spyOn(HTMLElement.prototype,'scrollHeight','get').mockImplementation(function(this:HTMLElement){return this.classList.contains('mobile-chat-scroll')?1000:0;});
    vi.spyOn(HTMLElement.prototype,'getBoundingClientRect').mockReturnValue({top:100,bottom:200,left:0,right:390,width:390,height:100,x:0,y:100,toJSON:()=>({})});
    const read=conversationsApi.read,oldWatermark='r1'+'0'.repeat(16)+'r'+'a'.repeat(96),newWatermark='r1'+'1'.repeat(16)+'r'+'b'.repeat(96);
    vi.spyOn(conversationsApi,'read').mockImplementation(async(...args)=>{
      const inbox=await read(...args),rows=await Promise.all(inbox.rows.map(async row=>{
        const workspace=await workspaceApi.read(identity,row.workspace_id),arrived=workspace.entries.some(entry=>entry.content==='A new invented message while reading above.'&&entry.reply);
        return {...row,watermark:arrived?newWatermark:oldWatermark};
      }));return {...inbox,rows};
    });
    const mark=vi.spyOn(conversationsApi,'mark');await open('messages');
    await vi.waitFor(()=>expect(mark.mock.calls.some(call=>call[3]?.watermark===oldWatermark&&call[3]?.manual_unread===undefined)).toBe(true));mark.mockClear();
    const history=host.querySelector<HTMLDivElement>('.mobile-chat-scroll')!;await act(async()=>{history.scrollTop=200;history.dispatchEvent(new Event('scroll',{bubbles:true}));});
    const composer=host.querySelector<HTMLTextAreaElement>('#team-question')!;await input(composer,'A new invented message while reading above.');
    await act(async()=>composer.closest('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
    await vi.waitFor(()=>expect(composer.value).toBe(''));expect(history.scrollTop).toBe(200);expect(mark).not.toHaveBeenCalled();
    await vi.waitFor(()=>expect(host.querySelector('.messages-new-replies')).toBeTruthy());
    expect(host.querySelector('.messages-new-replies')?.textContent).toBe('1 new message ↓');
    await act(async()=>host.querySelector<HTMLButtonElement>('.messages-new-replies')!.click());
    await vi.waitFor(()=>expect(mark).toHaveBeenCalledExactlyOnceWith(identity,expect.any(String),'chief',{watermark:newWatermark}));
    expect(history.scrollTop).toBe(800);expect(host.querySelector('.messages-new-replies')).toBeNull();
  });
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
  it('keeps Workspace Tools complete when Settings switches to Messages and returns to the same draft',async()=>{
    await open('workspace');const composer=host.querySelector<HTMLTextAreaElement>('#team-question')!,notebook=host.querySelector('#team-notebook');
    const session=observedSession.value!,workspaceId=session.getSnapshot().workspace!.id;
    await input(composer,'Keep this invented Tools draft.');await click('Tools');await click('Skills & settings');
    await act(async()=>{(host.querySelector('input[name="cosmas-layout"]:not(:checked)') as HTMLInputElement).click();});await click('Done');
    expect(host.querySelector('main')?.getAttribute('data-presentation')).toBe('messages');
    expect(host.querySelector('.messages-thread-header h1')?.textContent).toBe('Tools');
    expect(host.querySelector('main')?.getAttribute('data-messages-task')).toBe('Tools');
    expect(host.querySelector('.team-conversation-tools .chief-start-actions')).not.toBeNull();
    expect(visible(host.querySelector('.team-conversation-tools .chief-start-actions')!)).toBe(true);
    expect(visible(composer)).toBe(false);expect(composer.value).toBe('Keep this invented Tools draft.');
    await click('‹ Back to chat');
    expect(host.querySelector('.messages-thread-header h1')?.textContent).toBe('Chief of Staff');
    expect(host.querySelector('#team-question')).toBe(composer);expect(host.querySelector('#team-notebook')).toBe(notebook);
    expect(visible(composer)).toBe(true);expect(composer.disabled).toBe(false);expect(composer.value).toBe('Keep this invented Tools draft.');
    expect(session.getSnapshot()).toMatchObject({selected:'chief',mobilePanel:'Conversation',workspace:{id:workspaceId}});
    await click('Settings');await act(async()=>{(host.querySelector('input[name="cosmas-layout"]:not(:checked)') as HTMLInputElement).click();});await click('Done');
    expect(host.querySelector('main')?.getAttribute('data-presentation')).toBe('workspace');expect(visible(composer)).toBe(true);
    expect(host.querySelector('#team-question')).toBe(composer);expect(composer.value).toBe('Keep this invented Tools draft.');
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
