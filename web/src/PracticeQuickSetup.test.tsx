import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {PracticeAccessGate} from './PracticeAccessGate';
import {practiceAccessApi} from './practice-access-api';
import {WorkspaceApiError} from './workspace-api';
import {validatePracticeSetup,validateCompletePracticeSetup,type PracticeSetupStatus} from './practice-access-contract';
let root:Root,container:HTMLDivElement;
const identity={mode:'clerk_jwt' as const,getToken:async()=> 'invented.token'};
const available:PracticeSetupStatus={contract_version:1,state:'solo_setup_available',practice:null,display_name:null,can_start_practice:true};
const ready:PracticeSetupStatus={contract_version:1,state:'owner_ready',practice:{display_name:'Invented solo practice',specialty:null},display_name:'Invented clinician',can_start_practice:false};
beforeEach(()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});container=document.createElement('div');document.body.append(container);root=createRoot(container);
  vi.spyOn(practiceAccessApi,'read').mockResolvedValue({contract_version:1,state:'request_required',role:null,request:null});
  vi.spyOn(practiceAccessApi,'setup').mockResolvedValue(available);vi.spyOn(practiceAccessApi,'confirmSetup').mockResolvedValue(ready);
  vi.spyOn(practiceAccessApi,'request').mockRejectedValue(new Error('Join is separate'));
});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.restoreAllMocks();});
const button=(label:string)=>[...container.querySelectorAll('button')].find(b=>b.textContent===label)!;
const click=async(label:string)=>{expect(button(label)).toBeDefined();await act(async()=>button(label).click());};
const field=(label:string)=>[...container.querySelectorAll('label')].find(l=>l.textContent?.startsWith(label))!.querySelector('input')!;
async function input(label:string,value:string){await act(async()=>{const item=field(label);Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(item,value);item.dispatchEvent(new Event('input',{bubbles:true}));});}
async function render(id=identity){await act(async()=>root.render(<PracticeAccessGate identity={id} accountControls={<button>Account</button>}>{context=><p>Home: {context.role}</p>}</PracticeAccessGate>));}
async function setup(){await render();await click('Set up my practice');await input('Practice name','Invented solo practice');await input('Your name','Invented clinician');}
it('takes a reserved solo owner directly to Home with only practice and name confirmation',async()=>{
  await setup();expect(container.textContent).not.toContain('Waiting for your practice owner');await click('Continue to my workspace');
  expect(container.textContent).toContain('Home: owner');expect(practiceAccessApi.request).not.toHaveBeenCalled();
  expect(practiceAccessApi.confirmSetup).toHaveBeenCalledWith(identity,{idempotency_key:expect.any(String),practice_name:'Invented solo practice',display_name:'Invented clinician',specialty:null,confirm:true},expect.any(AbortSignal));
});
it('prefills an existing owner',async()=>{
  vi.mocked(practiceAccessApi.read).mockResolvedValue({contract_version:1,state:'connected',role:'owner',request:null});
  vi.mocked(practiceAccessApi.setup).mockResolvedValue({...ready,state:'owner_setup'});await render();
  expect(field('Practice name').value).toBe('Invented solo practice');expect(field('Your name').value).toBe('Invented clinician');
  await click('Continue to my workspace');expect(container.textContent).toContain('Home: owner');
});
it('checks interrupted setup before explicitly retrying exactly the same command',async()=>{
  vi.mocked(practiceAccessApi.confirmSetup).mockRejectedValueOnce(new WorkspaceApiError(503));await setup();await click('Continue to my workspace');
  expect(button('Continue to my workspace').disabled).toBe(true);await click('Check setup');
  expect(field('Practice name').value).toBe('Invented solo practice');expect(field('Practice name').disabled).toBe(true);
  await click('Continue to my workspace');const calls=vi.mocked(practiceAccessApi.confirmSetup).mock.calls;
  expect(calls).toHaveLength(2);expect(calls[0][1]).toEqual(calls[1][1]);expect(container.textContent).toContain('Home: owner');
});
it('recovers completed setup by read without another write',async()=>{
  vi.mocked(practiceAccessApi.confirmSetup).mockRejectedValueOnce(new WorkspaceApiError(503));await setup();await click('Continue to my workspace');
  vi.mocked(practiceAccessApi.read).mockResolvedValue({contract_version:1,state:'connected',role:'owner',request:null});
  vi.mocked(practiceAccessApi.setup).mockResolvedValue(ready);await click('Check setup');
  expect(container.textContent).toContain('Home: owner');expect(practiceAccessApi.confirmSetup).toHaveBeenCalledOnce();
});
it('clears private setup after denial and ignores a prior identity response',async()=>{
  await setup();vi.mocked(practiceAccessApi.confirmSetup).mockRejectedValueOnce(new WorkspaceApiError(403));await click('Continue to my workspace');
  expect(container.textContent).not.toContain('Invented solo practice');expect(container.querySelector('input')).toBeNull();
  let finish!:(value:PracticeSetupStatus)=>void;vi.mocked(practiceAccessApi.setup).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
  await render({...identity});vi.mocked(practiceAccessApi.setup).mockResolvedValue({...available,state:'join_existing',can_start_practice:false});
  await render({...identity});await act(async()=>finish(ready));expect(container.textContent).not.toContain('Home: owner');
});
it('keeps ownership and setup fields closed',()=>{
  for(const change of [{can_start_practice:false},{is_owner:true},{state:'owner_ready'}])expect(()=>validatePracticeSetup({...available,...change})).toThrow();
  const command={idempotency_key:crypto.randomUUID(),practice_name:'Invented practice',display_name:'Invented clinician',specialty:null,confirm:true};
  for(const change of [{confirm:1},{specialty:''},{is_owner:true},{practice_name:' padded '}])expect(()=>validateCompletePracticeSetup({...command,...change})).toThrow();
});
