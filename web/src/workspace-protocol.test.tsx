import {act,useEffect,useState} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import observed from '../../tests/fixtures/workspace-compatibility.json';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {WorkspaceCompatibilityGate} from './WorkspaceCompatibilityGate';
import {PracticeAccessGate} from './PracticeAccessGate';
import {PracticeAccessPanel} from './PracticeAccessPanel';
import {accessFixture as accessRow,accessConnected} from './practice-access-test-fixture';
import {practiceAccessApi} from './practice-access-api';
import {workspaceApi,WorkspaceApiError} from './workspace-api';
import {admitWorkspaceProtocol,REQUIRED_WORKSPACE_CONTRACTS,requireWorkspaceProtocol,validateWorkspaceCompatibility,workspaceFetch,workspaceProtocolGeneration,workspaceProtocolPhase} from './workspace-protocol';

const api='https://api.example.invalid';
const descriptor=()=>({contract_version:1,workspace_protocol:1,requests_require_protocol:true,contracts:{...REQUIRED_WORKSPACE_CONTRACTS}});
const response=(value:unknown,status=200,protocol:string|null='1')=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store',...(protocol===null?{}:{'X-Cosmas-Workspace-Protocol':protocol})}});
const identity=()=>({mode:'clerk_jwt' as const,getToken:vi.fn(async()=> 'invented.fresh.token')});
const options={method:'GET',headers:{'X-Cosmas-Workspace-Protocol':'1'}};
let root:Root,container:HTMLDivElement;
beforeEach(()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});
  vi.stubEnv('VITE_API_BASE',api);vi.stubEnv('VITE_WORKSPACE_HOSTED_API_ORIGIN',api);
  vi.stubEnv('VITE_WORKSPACE_WEB_ORIGIN','https://workspace.example.invalid');
  vi.stubGlobal('window',{location:{href:'https://workspace.example.invalid/'},setInterval:window.setInterval.bind(window),clearInterval:window.clearInterval.bind(window)});
  vi.stubEnv('VITE_WORKSPACE_HOSTED_CLIENT','web');vi.stubEnv('VITE_WORKSPACE_DATA_MODE','synthetic');
  vi.stubEnv('VITE_COSMAS_ENV','early_adopter_beta');vi.stubEnv('VITE_WORKSPACE_HOSTED_ENABLED','true');
  vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');
  vi.stubGlobal('fetch',vi.fn());
  container=document.createElement('div');document.body.append(container);root=createRoot(container);
});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.restoreAllMocks();vi.unstubAllGlobals();vi.unstubAllEnvs();});
const click=async()=>act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Retry')!.click());
const ready=(id:ReturnType<typeof identity>)=>admitWorkspaceProtocol(id,workspaceProtocolGeneration(id));

it('rejects the older signed observation and accepts only current required contracts',()=>{
  expect(()=>validateWorkspaceCompatibility(observed)).toThrow();
  expect(validateWorkspaceCompatibility(descriptor())).toEqual(descriptor());
  for(const value of [{...descriptor(),workspace_protocol:2},{...descriptor(),requests_require_protocol:false},
    {...descriptor(),contracts:{...REQUIRED_WORKSPACE_CONTRACTS,team:1}}, {...descriptor(),contracts:{}},
    {...descriptor(),contracts:{...REQUIRED_WORKSPACE_CONTRACTS,private_name:'do not show'}}])expect(()=>validateWorkspaceCompatibility(value)).toThrow();
  expect(validateWorkspaceCompatibility({...descriptor(),contracts:{...REQUIRED_WORKSPACE_CONTRACTS,new_optional:1}})).toBeTruthy();
});

it('checks compatibility before onboarding and uses the existing signed bounded API',async()=>{
  const id=identity(),check=vi.spyOn(practiceAccessApi,'read').mockResolvedValue({contract_version:1,state:'request_required',role:null,request:null});
  vi.spyOn(practiceAccessApi,'setup').mockResolvedValue({contract_version:1,state:'join_existing',practice:null,display_name:null,can_start_practice:false});
  vi.mocked(fetch).mockResolvedValueOnce(response(descriptor()));
  await act(async()=>root.render(<WorkspaceCompatibilityGate identity={id} accountControls={<button>Account</button>}>
    <PracticeAccessGate identity={id} accountControls={null}>{()=> <p>Private workspace</p>}</PracticeAccessGate>
  </WorkspaceCompatibilityGate>));
  expect(fetch).toHaveBeenCalledOnce();const [url,init]=vi.mocked(fetch).mock.calls[0];
  expect(url).toBe(api+'/practice-access/compatibility');expect(init).toMatchObject({method:'GET',credentials:'omit',redirect:'error',cache:'no-store'});
  expect(new Headers(init?.headers).get('X-Cosmas-Workspace-Protocol')).toBe('1');
  expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer invented.fresh.token');
  expect(check).toHaveBeenCalledOnce();expect(container.textContent).toContain('Join an existing practice');
});

it('requires the inbox contract only for Messages and resumes after the matching server is available',async()=>{
  vi.stubEnv('VITE_MESSAGES_ENABLED','false');
  expect(validateWorkspaceCompatibility(descriptor())).toBeTruthy();
  vi.stubEnv('VITE_MESSAGES_ENABLED','true');
  const id=identity(),mounted=vi.fn();function Workspace(){useEffect(()=>{mounted();},[]);return <p>Messages ready</p>;}
  vi.mocked(fetch).mockResolvedValueOnce(response(descriptor()));
  await act(async()=>root.render(<WorkspaceCompatibilityGate identity={id} accountControls={null}><Workspace/></WorkspaceCompatibilityGate>));
  expect(mounted).not.toHaveBeenCalled();expect(workspaceProtocolPhase(id)).not.toBe('ready');
  expect(container.textContent).toContain('could not confirm a compatible version');
  expect(()=>validateWorkspaceCompatibility({...descriptor(),contracts:{...REQUIRED_WORKSPACE_CONTRACTS,conversations:2}})).toThrow();
  vi.mocked(fetch).mockResolvedValueOnce(response({...descriptor(),contracts:{...REQUIRED_WORKSPACE_CONTRACTS,conversations:1}}));
  await click();expect(mounted).toHaveBeenCalledOnce();expect(container.textContent).toContain('Messages ready');
  expect(vi.mocked(fetch).mock.calls.every(([url,init])=>url===api+'/practice-access/compatibility'&&init?.method==='GET'&&init.body===undefined)).toBe(true);
});

it('holds children closed for legacy servers and outages, then retries without reloading or clearing drafts',async()=>{
  const id=identity(),mounted=vi.fn();function Workspace(){useEffect(()=>{mounted();},[]);return <p>Private draft</p>;}
  vi.mocked(fetch).mockResolvedValueOnce(response({detail:'Not found'},404,null));
  await act(async()=>root.render(<WorkspaceCompatibilityGate identity={id} accountControls={<button>Account</button>}><Workspace/></WorkspaceCompatibilityGate>));
  expect(mounted).not.toHaveBeenCalled();expect(container.textContent).toContain('could not confirm a compatible version');expect(container.textContent).toContain('Account');
  vi.mocked(fetch).mockResolvedValueOnce(response({detail:'unavailable'},503,null));await click();expect(mounted).not.toHaveBeenCalled();expect(container.textContent).toContain('Reconnect');
  vi.mocked(fetch).mockResolvedValueOnce(response(descriptor()));await click();expect(mounted).toHaveBeenCalledOnce();expect(container.textContent).toContain('Private draft');
});

it('pauses dispatch on a mid-session mismatch, keeps the editor and Stop available, and resumes only after a fresh check',async()=>{
  const id=identity(),unmount=vi.fn(),stop=vi.fn();
  function Workspace(){const [text,setText]=useState('Unsent note');useEffect(()=>unmount,[]);return <><input aria-label="Private note" value={text} onChange={e=>setText(e.target.value)}/><button onClick={stop}>Stop recording</button></>;}
  vi.mocked(fetch).mockResolvedValueOnce(response(descriptor()));
  await act(async()=>root.render(<WorkspaceCompatibilityGate identity={id} accountControls={null}><Workspace/></WorkspaceCompatibilityGate>));
  const editor=container.querySelector('input')!;
  vi.mocked(fetch).mockResolvedValueOnce(response({detail:'workspace_protocol_required'},426));
  await act(async()=>{await expect(workspaceApi.catalog(id)).rejects.toMatchObject({status:503});});
  expect(workspaceProtocolPhase(id)).toBe('blocked');expect(container.textContent).toContain('Workspace connection paused');
  expect(container.querySelector('input')).toBe(editor);expect(editor.value).toBe('Unsent note');expect(unmount).not.toHaveBeenCalled();
  await act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Stop recording')!.click());expect(stop).toHaveBeenCalledOnce();
  const calls=vi.mocked(fetch).mock.calls.length;await expect(workspaceApi.catalog(id)).rejects.toMatchObject({status:503});expect(fetch).toHaveBeenCalledTimes(calls);
  expect(()=>requireWorkspaceProtocol(id)).toThrow();
  vi.mocked(fetch).mockResolvedValueOnce(response(descriptor()));await click();
  expect(workspaceProtocolPhase(id)).toBe('ready');expect(container.querySelector('input')).toBe(editor);expect(unmount).not.toHaveBeenCalled();
  vi.mocked(fetch).mockResolvedValueOnce(response([]));expect(await workspaceApi.catalog(id)).toEqual([]);
});

it('does not reuse a late response across a compatibility failure and recovery',async()=>{
  const id=identity();ready(id);let finish!:(value:Response)=>void;
  vi.mocked(fetch).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
  const pending=workspaceFetch(id,api+'/workspaces',options);const observed=pending.catch(error=>error);
  vi.mocked(fetch).mockResolvedValueOnce(response({},200,null));await expect(workspaceFetch(id,api+'/provider-team',options)).rejects.toMatchObject({status:503});
  ready(id);finish(response({old:true}));expect(await observed).toMatchObject({status:503});
});

it('ignores a late native response after sign-out and does not turn transient HTTP errors into an update',async()=>{
  let current=true;const id={...identity(),nativeSession:{revision:'00000000-0000-4000-8000-000000000084',isCurrent:()=>current}};ready(id);
  vi.mocked(fetch).mockResolvedValueOnce(response({},503,null));expect((await workspaceFetch(id,api+'/workspaces',options)).status).toBe(503);expect(workspaceProtocolPhase(id)).toBe('ready');
  vi.mocked(fetch).mockImplementationOnce(async()=>{current=false;return response({},200,null);});
  await expect(workspaceFetch(id,api+'/workspaces',options)).rejects.toMatchObject({status:401});expect(workspaceProtocolPhase(id)).toBe('ready');
});

it('does not admit an identity after its gate unmounts while checking',async()=>{
  const old=identity(),next=identity();let finish!:(value:ReturnType<typeof validateWorkspaceCompatibility>)=>void;
  vi.spyOn(practiceAccessApi,'compatibility').mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;})).mockResolvedValue(validateWorkspaceCompatibility(descriptor()));
  await act(async()=>root.render(<WorkspaceCompatibilityGate identity={old} accountControls={null}><p>Old identity</p></WorkspaceCompatibilityGate>));
  await act(async()=>root.render(<WorkspaceCompatibilityGate identity={next} accountControls={null}><p>New identity</p></WorkspaceCompatibilityGate>));
  await act(async()=>finish(validateWorkspaceCompatibility(descriptor())));expect(workspaceProtocolPhase(old)).toBe('pending');expect(container.textContent).toContain('New identity');expect(container.textContent).not.toContain('Old identity');
});

it('refuses an oversized or duplicate-key handshake and never dispatches ordinary work before admission',async()=>{
  const id=identity();await expect(workspaceFetch(id,api+'/workspaces',options)).rejects.toMatchObject({status:503});expect(fetch).not.toHaveBeenCalled();
  vi.mocked(fetch).mockResolvedValueOnce(response({},200,'2'));await expect(practiceAccessApi.compatibility(id)).rejects.toMatchObject({status:426});
  vi.mocked(fetch).mockResolvedValueOnce(new Response(' '.repeat(4097),{headers:{'Content-Type':'application/json','Cache-Control':'no-store','X-Cosmas-Workspace-Protocol':'1'}}));
  await expect(practiceAccessApi.compatibility(id)).rejects.toMatchObject({status:502});
  vi.mocked(fetch).mockResolvedValueOnce(new Response('{"contract_version":1,"contract_version":1}',{headers:{'Content-Type':'application/json','Cache-Control':'no-store','X-Cosmas-Workspace-Protocol':'1'}}));
  await expect(practiceAccessApi.compatibility(id)).rejects.toMatchObject({status:502});
});


it('keeps a real owner approval and its exact recovery command mounted through a protocol pause',async()=>{
  vi.spyOn(practiceAccessApi,'setup').mockResolvedValue({contract_version:1,state:'owner_ready',practice:{display_name:'Invented practice',specialty:null},display_name:'Invented owner',can_start_practice:false});
  const id=identity();
  vi.mocked(fetch).mockResolvedValueOnce(response(descriptor()))
    .mockResolvedValueOnce(response({...accessConnected,role:'owner'}))
    .mockResolvedValueOnce(response({contract_version:1,requests:[accessRow]}));
  await act(async()=>root.render(<WorkspaceCompatibilityGate identity={id} accountControls={null}>
    <PracticeAccessGate identity={id} accountControls={null}>{access=><PracticeAccessPanel identity={id} access={access} onBusyChange={()=>{}}/>}</PracticeAccessGate>
  </WorkspaceCompatibilityGate>));
  const button=(label:string)=>[...container.querySelectorAll('button')].find(b=>b.textContent===label)!;
  await act(async()=>button('Review Ada Beta').click());
  await act(async()=>container.querySelector<HTMLInputElement>('input[type=checkbox]')!.click());
  vi.mocked(fetch).mockResolvedValueOnce(response({detail:'workspace_protocol_required'},426));
  await act(async()=>button('Approve member').click());
  expect(container.textContent).toContain('Workspace connection paused');
  expect(container.textContent).toContain('last decision is unconfirmed');
  expect(button('Recover approval')).toBeTruthy();expect(container.textContent).not.toContain('Join your practice');
  const command=vi.mocked(fetch).mock.calls[3][1]?.body;
  vi.mocked(fetch).mockResolvedValueOnce(response(descriptor())).mockResolvedValueOnce(response({...accessConnected,role:'owner'}));await click();
  expect(fetch).toHaveBeenCalledTimes(6);expect(button('Recover approval')).toBeTruthy();
  expect(vi.mocked(fetch).mock.calls[5][0]).toBe(api+'/practice-access');expect(vi.mocked(fetch).mock.calls[5][1]?.method).toBe('GET');
  vi.mocked(fetch).mockResolvedValueOnce(response({contract_version:1,request:{...accessRow,state:'approved'}}))
    .mockResolvedValueOnce(response({contract_version:1,requests:[]}));
  await act(async()=>button('Recover approval').click());
  expect(vi.mocked(fetch).mock.calls[6][1]?.body).toBe(command);
  expect(container.textContent).toContain('Ada Beta: access approved.');
});

it('one Retry checks compatibility then rechecks current access exactly once without another button or any write',async()=>{
  const id=identity(),read=vi.spyOn(practiceAccessApi,'read').mockImplementationOnce(async(signalIdentity)=>{
    await workspaceFetch(signalIdentity,api+'/practice-access',options);return accessConnected;
  }).mockResolvedValue(accessConnected);
  const setup=vi.spyOn(practiceAccessApi,'setup').mockResolvedValue({contract_version:1,state:'member_ready',practice:{display_name:'Invented practice',specialty:null},display_name:'Invented member',can_start_practice:false});
  vi.mocked(fetch).mockResolvedValueOnce(response(descriptor())).mockResolvedValueOnce(response({detail:'workspace_protocol_required'},426));
  await act(async()=>root.render(<WorkspaceCompatibilityGate identity={id} accountControls={null}><PracticeAccessGate identity={id} accountControls={null}>{()=> <p>Private workspace</p>}</PracticeAccessGate></WorkspaceCompatibilityGate>));
  expect(workspaceProtocolPhase(id)).toBe('blocked');expect(container.querySelectorAll('.workspace-compatibility-paused')).toHaveLength(1);
  expect([...container.querySelectorAll('button')].map(b=>b.textContent)).toEqual(['Retry']);
  vi.mocked(fetch).mockResolvedValueOnce(response(descriptor()));await click();
  expect(read).toHaveBeenCalledTimes(2);expect(setup).toHaveBeenCalledTimes(2);expect(container.textContent).toContain('Private workspace');
  expect(vi.mocked(fetch).mock.calls.every(([,init])=>init?.method==='GET'&&init?.body===undefined)).toBe(true);
});

it('waits for the prior access read to settle before consuming the successful Retry and does not loop after another failure',async()=>{
  const id=identity();let finish!:(value:typeof accessConnected)=>void;
  const read=vi.spyOn(practiceAccessApi,'read').mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}))
    .mockRejectedValue(new WorkspaceApiError(503));
  vi.spyOn(practiceAccessApi,'setup').mockResolvedValue({contract_version:1,state:'member_ready',practice:{display_name:'Invented practice',specialty:null},display_name:'Invented member',can_start_practice:false});
  vi.mocked(fetch).mockResolvedValueOnce(response(descriptor()));
  await act(async()=>root.render(<WorkspaceCompatibilityGate identity={id} accountControls={null}><PracticeAccessGate identity={id} accountControls={null}>{()=> <p>Private workspace</p>}</PracticeAccessGate></WorkspaceCompatibilityGate>));
  vi.mocked(fetch).mockResolvedValueOnce(response({detail:'workspace_protocol_required'},426));
  await act(async()=>{await expect(workspaceFetch(id,api+'/workspaces',options)).rejects.toMatchObject({status:503});});
  vi.mocked(fetch).mockResolvedValueOnce(response(descriptor()));await click();expect(read).toHaveBeenCalledOnce();
  await act(async()=>finish(accessConnected));expect(read).toHaveBeenCalledTimes(2);
  await act(async()=>{});expect(read).toHaveBeenCalledTimes(2);
});
it('requires the EHR read contract only for an explicitly enabled EHR build',()=>{vi.stubEnv('VITE_EHR_READ_ENABLED','false');expect(validateWorkspaceCompatibility(descriptor())).toBeTruthy();vi.stubEnv('VITE_EHR_READ_ENABLED','true');expect(()=>validateWorkspaceCompatibility(descriptor())).toThrow();expect(validateWorkspaceCompatibility({...descriptor(),contracts:{...REQUIRED_WORKSPACE_CONTRACTS,ehr_reads:1}})).toBeTruthy();});
