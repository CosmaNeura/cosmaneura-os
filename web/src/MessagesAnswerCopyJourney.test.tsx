import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {waitMessagesJourney as wait,MESSAGES_JOURNEY_TEST_TIMEOUT_MS} from './messages-journey-wait';
vi.hoisted(()=>{for(const name of ['VITE_MESSAGES_ENABLED','VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED'])vi.stubEnv(name,'true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {memoryDraftStorage} from './draft-test-fixture';
import {PRESENTATION_KEY} from './session/presentation';
import {workspaceApi} from './workspace-api';
import type {DraftStore} from './draft-store';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
vi.setConfig({testTimeout:MESSAGES_JOURNEY_TEST_TIMEOUT_MS});
let root:Root,host:HTMLDivElement,hold:boolean,release:(()=>void)|null;
const visible=(element:Element)=>!element.closest('[hidden]');
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(item=>visible(item)&&(item.textContent?.trim()===name||item.getAttribute('aria-label')===name))!;
async function click(name:string){await wait(()=>expect(button(name)).toBeTruthy());await wait(()=>expect(button(name).disabled).toBe(false));await act(async()=>button(name).click());}
async function type(field:HTMLTextAreaElement,value:string){await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));});}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);localStorage.clear();sessionStorage.clear();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','#cosmas/home');
 window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();await installFixtures(true);hold=false;release=null;
 const factory=memoryDraftStorage(),storage=async(options:{scope:string}):Promise<DraftStore>=>{const store=await factory(options);return {...store,async write(address,expected,value){if(hold&&address.includes(':answer-copy:')){hold=false;await new Promise<void>(resolve=>{release=resolve;});}return store.write(address,expected,value);}};};
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={storage}/>));await wait(()=>expect(host.querySelector<HTMLButtonElement>('.messages-row')?.disabled).toBe(false));await act(async()=>host.querySelector<HTMLButtonElement>('.messages-row')!.click());await wait(()=>expect(host.querySelector<HTMLTextAreaElement>('#team-question')?.disabled).toBe(false));
});
afterEach(async()=>{release?.();await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();history.replaceState(null,'','/');});

it('keeps the actual Messages navigation fenced while an answer copy saves, without freezing its own recovery or changing the unsent message',async()=>{
 const ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append'),input=host.querySelector<HTMLTextAreaElement>('#team-question')!,originalReply=host.querySelector('.team-bot-message')?.textContent;
 await type(input,'Retain this invented unsent Chief message.');await act(async()=>host.querySelector<HTMLButtonElement>('.messages-source-details')!.click());await click('Edit a copy');await wait(()=>expect(button('Copy edited copy').disabled).toBe(false));
 const field=host.querySelector<HTMLTextAreaElement>('.answer-copy-editor > label textarea')!;hold=true;await type(field,'Editable invented provider wording.');await wait(()=>expect(release).toBeTypeOf('function'));
 expect(button('‹ Messages').disabled).toBe(true);expect(button('Details').disabled).toBe(true);expect(button('Close message details').disabled).toBe(true);expect(field.disabled).toBe(false);
 await act(async()=>button('‹ Messages').click());expect(host.querySelector('[role=dialog]')).not.toBeNull();expect(input.value).toBe('Retain this invented unsent Chief message.');
 await act(async()=>release!());await wait(()=>expect(button('Copy edited copy').disabled).toBe(false));expect(button('‹ Messages').disabled).toBe(false);expect(button('Close message details').disabled).toBe(false);expect(field.value).toBe('Editable invented provider wording.');
 await click('Close message details');expect(host.querySelector('.team-bot-message')?.textContent).toBe(originalReply);expect(input.value).toBe('Retain this invented unsent Chief message.');expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();
});
