import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {resolveBetaFeatureProfile} from '../../clients/shared/beta-feature-profile.mjs';

const environment=(globalThis as typeof globalThis&{process?:{env:Record<string,string|undefined>}}).process?.env;
const base=environment?.COSMAS_STANDALONE_UI_LAB_URL;
const realFetch=globalThis.fetch.bind(globalThis);
let root:Root|undefined;
afterEach(async()=>{if(root)await act(async()=>root!.unmount());root=undefined;document.body.replaceChildren();vi.unstubAllGlobals();vi.unstubAllEnvs();});

it.skipIf(!base)('admits the standalone renderer and exercises its owned practice against an actual isolated API',async()=>{
  expect(base).toMatch(/^http:\/\/127\.0\.0\.1:[0-9]+$/);
  const phase=environment!.COSMAS_STANDALONE_UI_LAB_PHASE;
  expect(['setup','workflows']).toContain(phase);
  const fsModule='node:fs/promises';
  const {readFile,writeFile}=await import(/* @vite-ignore */fsModule) as {
    readFile:(path:string,encoding:string)=>Promise<string>;writeFile:(path:string,value:string)=>Promise<void>};
  const token=(await readFile(environment!.COSMAS_STANDALONE_UI_LAB_TOKEN_FILE!,'utf8')).trim();
  expect(token.split('.')).toHaveLength(3);
  const utilModule='node:util';
  const {transferableAbortController}=await import(/* @vite-ignore */utilModule) as {transferableAbortController:()=>AbortController};
  const abort=transferableAbortController();vi.stubGlobal('AbortController',abort.constructor);vi.stubGlobal('AbortSignal',abort.signal.constructor);
  const cryptoModule='node:crypto';const {webcrypto}=await import(/* @vite-ignore */cryptoModule) as {webcrypto:Crypto};
  vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('indexedDB',new IDBFactory());
  vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  const logical='https://api.example.invalid',page='https://workspace.example.invalid';
  const profile=resolveBetaFeatureProfile({VITE_WORKSPACE_FEATURE_PROFILE:'standalone-practice-v1',
    VITE_WORKSPACE_HOSTED_CLIENT:'web',VITE_WORKSPACE_DATA_MODE:'synthetic',
    VITE_WORKSPACE_HOSTED_API_ORIGIN:logical,VITE_API_BASE:logical,VITE_WORKSPACE_WEB_ORIGIN:page,
    VITE_CLERK_PUBLISHABLE_KEY:'pk_test_invented_lab_only',VITE_COSMANEURA_WEB_ORIGIN:'',
    VITE_CAPTURE_UPLOAD_ORIGINS:'',VITE_WORKSPACE_CAPTURE_MODE:'disabled'});
  for(const [key,value] of Object.entries(profile.env))vi.stubEnv(key,value);
  const originalWindow=window;
  vi.stubGlobal('window',new Proxy(originalWindow,{get(target,key){return key==='location'?new URL(page+'/'):Reflect.get(target,key);}}));
  const calls:{method:string;path:string;status:number}[]=[];
  const teams:{method:string;revision:unknown}[]=[];
  const refused:string[]=[];
  vi.stubGlobal('fetch',async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=typeof input==='string'?input:input instanceof URL?input.href:input.url;
    const path=new URL(url).pathname;
    if(!url.startsWith(logical+'/')||/(?:^|\/)(?:core|scribe|capture|prep)(?:\/|-|$)/.test(path)){
      refused.push(path);throw new Error('Standalone lab refused an external or platform request');
    }
    // Explicit lab-only transport mapping. No live DNS, Clerk endpoint or
    // production account is used; the real API verifies the offline signed JWT.
    const response=await realFetch(base+url.slice(logical.length),init);
    calls.push({method:init?.method??'GET',path,status:response.status});
    const bytes=await response.arrayBuffer();
    if(path==='/provider-team'&&response.status===200)teams.push({method:init?.method??'GET',revision:JSON.parse(new TextDecoder().decode(bytes)).revision});
    return new Response(bytes,{status:response.status,headers:response.headers});
  });
  const {WorkspaceCompatibilityGate}=await import('./WorkspaceCompatibilityGate');
  const {PracticeAccessGate}=await import('./PracticeAccessGate');
  const {EncounterWorkspace}=await import('./EncounterWorkspace');
  const identity={mode:'clerk_jwt' as const,getToken:async()=>token};
  const host=document.createElement('div');document.body.append(host);root=createRoot(host);
  const controls=<span>Invented offline lab identity</span>;
  const render=()=>root!.render(<WorkspaceCompatibilityGate identity={identity} accountControls={controls}>
    <PracticeAccessGate identity={identity} accountControls={controls}>{access=>phase==='setup'
      ?<p data-independent-practice="ready">Independent practice admitted: {access.role}</p>
      :<EncounterWorkspace authenticated={identity} practiceAccess={access} accountControls={controls}/>}</PracticeAccessGate>
  </WorkspaceCompatibilityGate>);
  async function wait(check:()=>void){const end=performance.now()+15000;while(performance.now()<end){let passed=false;
    await act(async()=>{await new Promise(resolve=>setTimeout(resolve,10));try{check();passed=true;}catch{}});if(passed)return;}check();}
  const visible=(element:Element)=>!element.closest('[hidden]');
  const button=(label:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>visible(b)&&b.textContent?.trim()===label);
  async function click(label:string){await wait(()=>{expect(button(label),`${label}: ${host.textContent}`).toBeTruthy();expect(button(label)!.disabled,label).toBe(false);});await act(async()=>button(label)!.click());}
  async function change(field:HTMLInputElement|HTMLTextAreaElement,value:string){await act(async()=>{
    Object.getOwnPropertyDescriptor(field instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value')!.set!.call(field,value);
    field.dispatchEvent(new Event('input',{bubbles:true}));});}
  const started=performance.now();await act(render);
  if(phase==='setup'){
    await wait(()=>expect(button('Continue to my workspace')??button('Set up my practice'),host.textContent??'').toBeTruthy());
    if(!button('Continue to my workspace'))await click('Set up my practice');
    const field=(label:string)=>[...host.querySelectorAll('label')].find(el=>visible(el)&&el.textContent?.startsWith(label))!.querySelector<HTMLInputElement>('input')!;
    await change(field('Practice name'),'Cosmas MD · Standalone synthetic');
    await change(field('Your name'),'Invented practice owner');
    await click('Continue to my workspace');
    await wait(()=>expect(host.querySelector('[data-independent-practice="ready"]')?.textContent).toContain('owner'));
    expect(calls.filter(call=>call.method==='POST'&&call.path==='/practice-access/setup/complete')).toHaveLength(1);
  }else{
    await wait(()=>expect(host.querySelector('[aria-label="Practice Home"]')??host.querySelector('.messages-inbox'),host.textContent??'').toBeTruthy());
    await wait(()=>expect(host.querySelector('.team-roster button'),host.textContent??'').toBeTruthy());
    if(button('Use this team')){
      await click('Use this team');
      await wait(()=>expect(calls.some(call=>call.method==='POST'&&call.path==='/provider-team')).toBe(true));
      await writeFile(environment!.COSMAS_STANDALONE_UI_LAB_REPORT!+'.checkpoint.json',JSON.stringify({phase,calls},null,2)+'\n');
      expect(calls.find(call=>call.method==='POST'&&call.path==='/provider-team')?.status).toBe(200);
    }
    if(!host.querySelector('.messages-inbox')){
      await click('Settings');
      await act(async()=>{await new Promise(resolve=>setTimeout(resolve,100));});
      await writeFile(environment!.COSMAS_STANDALONE_UI_LAB_REPORT!+'.settings.json',JSON.stringify({phase,teams,calls,
        messagesFlag:import.meta.env.VITE_MESSAGES_ENABLED,
        controls:[...host.querySelectorAll('.settings-hub label,.settings-hub button,.settings-hub h1')].filter(visible).map(element=>({tag:element.tagName,text:element.textContent?.trim(),html:element.outerHTML}))},null,2)+'\n');
      await wait(()=>expect([...host.querySelectorAll('label')].find(label=>visible(label)&&label.textContent==='Messages')?.querySelector('input')).toBeTruthy());
      const messages=[...host.querySelectorAll('label')].find(label=>visible(label)&&label.textContent==='Messages')!.querySelector<HTMLInputElement>('input')!;
      await act(async()=>messages.click());await click('Done');
    }
    await wait(()=>expect(host.querySelector('.messages-inbox'),host.textContent??'').toBeTruthy());
    await click('New message');
    const chiefStart=host.querySelector<HTMLButtonElement>('.messages-bot-choices button')!;
    const chiefName=chiefStart.querySelector('strong')!.textContent!;
    expect(chiefName).toContain('Chief');expect(chiefStart.disabled).toBe(false);
    await act(async()=>chiefStart.click());
    await wait(()=>expect(host.querySelector('[aria-label="Practice Home"]'),host.textContent??'').toBeTruthy());
    if(button('Use this team'))await click('Use this team');
    await click('Visits and notes');
    await wait(()=>expect([...host.querySelectorAll<HTMLButtonElement>('.team-encounter-option')].filter(visible)).toHaveLength(2));
    const appointment=[...host.querySelectorAll<HTMLButtonElement>('.team-encounter-option')].filter(visible)[0];
    expect(appointment.textContent).toContain('Invented Alex Example');
    await act(async()=>appointment.click());
    await wait(()=>expect(host.querySelector<HTMLTextAreaElement>('#team-question')?.disabled,host.textContent??'').toBe(false));
    const draft='Invented standalone Chief directions. Keep these unsent while reviewing my own practice.';
    await change(host.querySelector<HTMLTextAreaElement>('#team-question')!,draft);
    await click('Details');expect(button('Notebook and recording')).toBeUndefined();await click('Notebook');
    await wait(()=>expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')?.disabled,host.textContent??'').toBe(false));
    const note=`Invented standalone practice planning note, saved only in this isolated CosmaBot database. Qualification ${new Date().toISOString()}.`;
    await change(host.querySelector<HTMLTextAreaElement>('#team-notebook')!,note);
    await click('Save notebook revision');
    await wait(()=>expect(calls.some(call=>call.method==='POST'&&/\/workspaces\/[^/]+\/entries$/.test(call.path)&&call.status===200)).toBe(true));
    expect(host.querySelector('[aria-label="Scribe recording"]')).toBeNull();
    expect(calls.some(call=>call.path.includes('/ask'))).toBe(false);
    await click(`‹ Back to ${chiefName}`);
    await wait(()=>expect(host.querySelector<HTMLTextAreaElement>('#team-question')?.value).toBe(draft));
    await click('‹ Messages');
    await wait(()=>expect(host.querySelector('.messages-row'),host.textContent??'').toBeTruthy());
    await act(async()=>host.querySelector<HTMLButtonElement>('.messages-row')!.click());
    await wait(()=>expect(host.querySelector<HTMLTextAreaElement>('#team-question')?.value).toBe(draft));
    await click('Details');await click('Notebook');
    await wait(()=>expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')?.value).toBe(note));
    await click(`‹ Back to ${chiefName}`);
    await click('Visits');
    await wait(()=>expect(button('Find another visit')).toBeTruthy());
    await click('Find another visit');
    await wait(()=>expect(host.querySelector('.settings-hub:not([hidden]) h1')?.textContent).toBe('Connections'));
    await wait(()=>expect(calls.some(call=>call.path==='/connections/catalog'&&call.status===200)).toBe(true));
    expect(button('Add connection')).toBeTruthy();
    expect(host.querySelector('.settings-hub:not([hidden])')?.textContent).not.toContain('Cosmaneura account & appointments');
    await click('Done');
    await wait(()=>expect(button('Find another visit')).toBeTruthy());
    await click('Current notebook');
    await wait(()=>expect(host.querySelector<HTMLTextAreaElement>('#team-question')?.value).toBe(draft));
    await click('Details');await click('Notebook');
    await wait(()=>expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')?.value).toBe(note));
  }
  expect(refused).toEqual([]);
  expect(calls.some(call=>call.path==='/practice-access/compatibility'&&call.status===200)).toBe(true);
  await writeFile(environment!.COSMAS_STANDALONE_UI_LAB_REPORT!,JSON.stringify({completed:true,phase,
    synthetic_only:true,actual_signed_offline_api:true,actual_DOM_controls:true,
    logical_client_profile:profile.manifest,api_transport:'explicit logical HTTPS to owned loopback lab mapping',
    real_clerk_login:false,real_users_tested:false,physical_devices_tested:false,
    external_provider_requests:0,refused_requests:refused,calls,automated_elapsed_ms:performance.now()-started},null,2)+'\n');
},90000);
