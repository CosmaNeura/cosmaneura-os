import {act,useEffect} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {SettingsHub} from './SettingsHub';
import {readConnectionCatalog} from './connection-catalog-api';
import {readConnectionSummary,personalConnectionSummary} from './connection-summary';
import {observeConnectionStatus,observeConnectionRead,connectionReadScope,connectionHealth,invalidateConnectionHealth} from './connection-operation-health';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
import type {FaxReadiness} from './fax-readiness-api';
vi.mock('./connection-catalog-api',()=>({readConnectionCatalog:vi.fn()}));
vi.mock('./connection-summary',async original=>({...await original<typeof import('./connection-summary')>(),readConnectionSummary:vi.fn()}));
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
const catalog={core:true,google:false,microsoft:false,scheduling:false,messaging:false,payments:false,portals:false};
const faxReady:FaxReadiness={contract_version:1,scope:{box_id:'00000000-0000-4000-8000-000000000001',owner_id:'00000000-0000-4000-8000-000000000002'},enabled:true,work_enabled:true,delivery_enabled:true,credential_access_configured:true,document_storage_configured:true,providers:['spruce','srfax','documo','efax'].map(id=>({id:id as FaxReadiness['providers'][number]['id'],installed_accounts:1,active_accounts:1,review_required_accounts:0,unavailable_accounts:0,prepare_enabled_accounts:1}))};
let host:HTMLDivElement,root:Root;
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.resetAllMocks();vi.mocked(readConnectionSummary).mockResolvedValue({label:'Not connected',reason:'Sign in to connect your account.',action:'Connect account',tone:'attention'});host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});
async function click(label:string){const button=[...host.querySelectorAll('button')].find(b=>!b.closest('[hidden]')&&b.textContent?.includes(label));expect(button).toBeDefined();await act(async()=>button!.click());}
const mount=(google:React.ReactNode,owner=identity)=>act(async()=>root.render(<SettingsHub open initialScreen="connections" team={<p>Team</p>} core={<p>Practice setup</p>} google={google} microsoft={<p>Microsoft</p>} messaging={<p>Messaging</p>} payments={<p>Payments</p>} portals={<p>Portals</p>} scheduling={<p>Scheduling</p>} teamSummary="Five bots" teamDirty={false} onClose={()=>{}} connectionIdentity={owner}/>));
it('shows disabled services with useful setup steps without mounting a dead editor',async()=>{
  const editor=vi.fn();function Google(){useEffect(()=>{editor();},[]);return <p>OAuth editor</p>;}
  vi.mocked(readConnectionCatalog).mockResolvedValue(catalog);await mount(<Google/>);
  expect(host.querySelectorAll('.connection-card')).toHaveLength(7);expect(host.textContent).toContain('Needs setup');
  const unavailable=[...host.querySelectorAll('.connection-card')].find(item=>item.textContent?.includes('Google email & calendar'))!;
  expect(unavailable.textContent).toContain('Availability checked');expect(unavailable.textContent).not.toContain('Account checked');
  await click('Google email & calendar');expect(editor).not.toHaveBeenCalled();expect(host.textContent).toContain('Google sign-in has not been enabled');
  expect(host.textContent).toContain('Review the requested email and calendar access');
  vi.mocked(readConnectionCatalog).mockResolvedValue({...catalog,google:true});await click('Check availability again');await click('Google email & calendar');
  expect(editor).toHaveBeenCalledOnce();expect(host.querySelector('[data-settings-screen="google"]')?.hasAttribute('hidden')).toBe(false);
});
it('does not turn a failed availability read into an available or connected badge',async()=>{
  vi.mocked(readConnectionCatalog).mockRejectedValue(new Error('offline'));await mount(<p>Google</p>);
  expect(host.textContent).toContain('Connections could not be checked');
  expect([...host.querySelectorAll('.connection-badge')].every(x=>x.textContent==='Needs attention')).toBe(true);
  expect(readConnectionSummary).not.toHaveBeenCalled();
});
it('shows independent account results without confusing enabled setup with a connection',async()=>{
  vi.mocked(readConnectionCatalog).mockResolvedValue({...catalog,google:true,microsoft:true});
  vi.mocked(readConnectionSummary).mockImplementation(async(_owner,id)=>{
    if(id==='google')return {label:'Connected',reason:'invented@example.invalid',action:'View connection',tone:'ready',checkedAt:Date.now()};
    if(id==='microsoft')throw new Error('offline');
    return {label:'Needs review',reason:'Ask your administrator.',action:'Review connection',tone:'attention'};
  });
  await mount(<p>Google</p>);
  const row=(name:string)=>[...host.querySelectorAll('.connection-card')].find(x=>x.textContent?.includes(name))!;
  expect(row('Google email & calendar').textContent).toContain('Connected');expect(row('Google email & calendar').textContent).toContain('Account checked');
  expect(row('Microsoft email').textContent).toContain('Needs attention');
  expect(row('Cosmaneura account').textContent).toContain('Needs review');
  expect(readConnectionSummary).toHaveBeenCalledTimes(3);
  expect(host.querySelectorAll('.connection-badge-ready')).toHaveLength(1);
});
it('aborts account checks on exit and ignores late private results from another owner',async()=>{
  let finish!:(value:Awaited<ReturnType<typeof readConnectionSummary>>)=>void;
  let signal!:AbortSignal;
  vi.mocked(readConnectionCatalog).mockResolvedValue(catalog);
  vi.mocked(readConnectionSummary).mockImplementationOnce((_owner,_id,s)=>{signal=s;return new Promise(resolve=>{finish=resolve;});});
  await mount(<p>Google</p>);await mount(<p>Google</p>,{...identity});
  expect(signal.aborted).toBe(true);
  await act(async()=>finish({label:'Connected',reason:'Previous private account',action:'View',tone:'ready'}));
  expect(host.textContent).not.toContain('Previous private account');expect(host.querySelector('.connection-badge-ready')).toBeNull();
});
it('ignores a late response from the previous signed-in account',async()=>{
  let finish!:(value:typeof catalog)=>void;
  vi.mocked(readConnectionCatalog).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;})).mockResolvedValue({...catalog,core:false});
  await mount(<p>Google</p>);await mount(<p>Google</p>,{...identity});
  await act(async()=>finish({...catalog,google:true}));
  expect(host.querySelector('.connection-badge-ready')).toBeNull();
});
it('checks only services actually present in this client',async()=>{
  vi.mocked(readConnectionCatalog).mockResolvedValue({...catalog,google:true,microsoft:true,scheduling:true});
  await act(async()=>root.render(<SettingsHub open initialScreen="connections" team={<p>Team</p>} core={<p>Practice setup</p>} teamSummary="Five bots" teamDirty={false} onClose={()=>{}} connectionIdentity={identity}/>));
  expect(host.querySelectorAll('.connection-card')).toHaveLength(1);
  expect(readConnectionSummary).toHaveBeenCalledOnce();
  expect(vi.mocked(readConnectionSummary).mock.calls[0][1]).toBe('core');
});
it('retains last confirmed status through both refresh phases and a failed new check',async()=>{
  const connected={label:'Connected',reason:'invented@example.invalid',action:'View connection',tone:'ready' as const,checkedAt:Date.now()};
  vi.mocked(readConnectionCatalog).mockResolvedValue({...catalog,google:true});vi.mocked(readConnectionSummary).mockResolvedValue(connected);
  await mount(<p>Google</p>);
  let catalogDone!:(v:typeof catalog)=>void,summaryDone!:(v:typeof connected)=>void;
  vi.mocked(readConnectionCatalog).mockImplementationOnce(()=>new Promise(resolve=>{catalogDone=resolve;}));
  await click('Refresh connections');
  expect(host.textContent).toContain('Checking again');expect(host.textContent).toContain('Last confirmed: Connected');expect(host.querySelector('.connection-badge-ready')).toBeNull();
  vi.mocked(readConnectionSummary).mockImplementation(()=>new Promise(resolve=>{summaryDone=resolve;}));
  await act(async()=>catalogDone({...catalog,core:false,google:true}));
  expect(host.textContent).toContain('Last confirmed: Connected');
  expect(host.querySelector('.connection-directory-status')?.textContent).toContain('Checking again');
  expect([...host.querySelectorAll('button')].find(button=>button.textContent==='Refresh connections')?.disabled).toBe(true);
  await act(async()=>summaryDone(connected));expect(host.querySelector('.connection-badge-ready')).not.toBeNull();
  vi.mocked(readConnectionCatalog).mockResolvedValue({...catalog,google:true});vi.mocked(readConnectionSummary).mockRejectedValue(new Error('offline'));
  await click('Refresh connections');expect(host.textContent).toContain('Current status is unknown');expect(host.textContent).toContain('Last confirmed: Connected');expect(host.querySelector('.connection-badge-ready')).toBeNull();
});
it('clears cached account results and rejects sibling responses after authorization is lost',async()=>{
  const connected={label:'Connected',reason:'Invented private account',action:'View connection',tone:'ready' as const,checkedAt:Date.now()};
  vi.mocked(readConnectionCatalog).mockResolvedValue({...catalog,google:true});vi.mocked(readConnectionSummary).mockResolvedValue(connected);await mount(<p>Google</p>);
  let finish!:(v:typeof connected)=>void;
  vi.mocked(readConnectionSummary).mockImplementation(async(_owner,id)=>{
    if(id==='core')return new Promise(resolve=>{finish=resolve;});
    throw new (await import('./workspace-api')).WorkspaceApiError(401);
  });
  await click('Refresh connections');await act(async()=>finish(connected));
  expect(host.textContent).not.toContain('Invented private account');expect(host.querySelector('.connection-badge-ready')).toBeNull();expect(host.textContent).not.toContain('Last confirmed:');
});
it('updates independent read proof without another account check and never carries it into a different identity',async()=>{
  invalidateConnectionHealth(identity,'google');const connected={state:'connected',account:{email:'invented@example.invalid'},connected_at:new Date(Date.now()-600000).toISOString(),capabilities:{mail:true,calendar:false}};
  vi.mocked(readConnectionCatalog).mockResolvedValue({...catalog,core:false,google:true});
  vi.mocked(readConnectionSummary).mockImplementation(async(owner,id)=>{expect(id).toBe('google');observeConnectionStatus(owner,'google',connected);return personalConnectionSummary('google',connectionHealth(owner,'google'),connected.account.email);});
  await mount(<p>Google</p>);const row=()=>[...host.querySelectorAll('.connection-card')].find(item=>item.textContent?.includes('Google email & calendar'))!;
  expect(row().textContent).toContain('Email: Not verified');expect(row().textContent).toContain('Calendar: Permission needed');expect(row().textContent).toContain('Account checked');
  await act(async()=>{observeConnectionRead(identity,'google',connectionReadScope(identity,'google'),{kind:'mail',account:connected.account,observed_at:new Date().toISOString()});});
  expect(row().textContent).toContain('Email: Verified in this session');expect(row().textContent).toContain('Last successful read:');expect(readConnectionSummary).toHaveBeenCalledOnce();
  await mount(<p>Google</p>,{...identity});expect(row().textContent).not.toContain('Verified in this session');expect(row().textContent).not.toContain('Last successful read:');expect(row().textContent).toContain('Email: Not verified');
});
it('drops a cached account label and proof when a background check changes or revokes the connection',async()=>{
  const connected={state:'connected',account:{email:'previous@example.invalid'},connected_at:new Date(Date.now()-600000).toISOString(),capabilities:{mail:true,calendar:true}};
  vi.mocked(readConnectionCatalog).mockResolvedValue({...catalog,core:false,google:true});
  vi.mocked(readConnectionSummary).mockImplementation(async(owner)=>{observeConnectionStatus(owner,'google',connected);return personalConnectionSummary('google',connectionHealth(owner,'google'),connected.account.email);});
  await mount(<p>Google</p>);expect(host.textContent).toContain(connected.account.email);
  await act(async()=>observeConnectionStatus(identity,'google',{...connected,account:{email:'new@example.invalid'}}));
  expect(host.textContent).not.toContain(connected.account.email);expect(host.textContent).toContain('Account connection changed');expect(host.textContent).not.toContain('Verified in this session');
  await act(async()=>observeConnectionStatus(identity,'google',{state:'sign_in_required',account:null,connected_at:null}));
  const row=[...host.querySelectorAll('.connection-card')].find(item=>item.textContent?.includes('Google email & calendar'))!;
  expect(row.textContent).toContain('Needs setup');expect(row.textContent).not.toContain('Account connected');expect(row.textContent).toContain('Connect account');
});
it('connects fax setup to work and withdraws stale readiness when rechecking fails',async()=>{
  const work=vi.fn();vi.mocked(readConnectionCatalog).mockResolvedValue({...catalog,core:false,messaging:true});
  vi.mocked(readConnectionSummary).mockResolvedValue({label:'Ready to prepare',reason:'One account configured.',action:'Review accounts',tone:'neutral',faxReadiness:faxReady});
  await act(async()=>root.render(<SettingsHub open initialScreen="connections" team={<p>Team</p>} messaging={<p>Account editor</p>} teamSummary="Five bots" teamDirty={false} onClose={()=>{}} connectionIdentity={identity} onOpenMessagingWork={work}/>));
  expect(vi.mocked(readConnectionSummary).mock.calls.every(call=>call[1]==='messaging')).toBe(true);
  await click('Messaging & fax');await click('Open fax work');expect(work).toHaveBeenCalledOnce();
  vi.mocked(readConnectionCatalog).mockRejectedValue(new Error('offline'));await click('Check fax setup');
  const overview=host.querySelector('[aria-label="Fax providers and next steps"]')!;
  expect(overview.textContent).toContain('could not be confirmed');
  const action=[...overview.querySelectorAll('button')].find(item=>item.textContent==='Open fax work')!;
  expect(action.disabled).toBe(true);await act(async()=>action.click());expect(work).toHaveBeenCalledOnce();
});
it('clears abandoned loading flags when entering fax setup interrupts another account check',async()=>{
  let pendingSignal!:AbortSignal,finish!:(value:Awaited<ReturnType<typeof readConnectionSummary>>)=>void;
  vi.mocked(readConnectionCatalog).mockResolvedValueOnce({...catalog,core:true,messaging:true}).mockRejectedValueOnce(new Error('offline'));
  vi.mocked(readConnectionSummary).mockImplementation(async(_owner,id,signal)=>{
    if(id==='core'){pendingSignal=signal;return new Promise(resolve=>{finish=resolve;});}
    return {label:'Ready to prepare',reason:'Configured account.',action:'Review accounts',tone:'neutral',faxReadiness:faxReady};
  });
  await mount(<p>Google</p>);await click('Messaging & fax');
  expect(pendingSignal.aborted).toBe(true);
  const overview=host.querySelector('[aria-label="Fax providers and next steps"]')!;
  expect(overview.textContent).toContain('could not be confirmed');expect(overview.textContent).not.toContain('Checking fax setup');
  const retry=[...overview.querySelectorAll('button')].find(item=>item.textContent==='Check fax setup')!;
  expect(retry.disabled).toBe(false);
  await act(async()=>finish({label:'Connected',reason:'Stale account response',action:'View',tone:'ready'}));
  expect(host.textContent).not.toContain('Stale account response');
  vi.mocked(readConnectionCatalog).mockResolvedValue({...catalog,core:true,messaging:true});
  await act(async()=>retry.click());expect(overview.textContent).toContain('available for preparing a fax draft');
});
it('uses Available only for enabled setup and Not checked when there is no account check',async()=>{
 vi.mocked(readConnectionCatalog).mockResolvedValue({...catalog,core:false,payments:true});
 await mount(<p>Google</p>);
 const payments=[...host.querySelectorAll('.connection-card')].find(item=>item.textContent?.includes('Payments'))!;
 expect(payments.querySelector('.connection-badge')?.textContent).toBe('Available');
 expect(payments.textContent).toContain('Its account and task results have not been checked');
 expect(payments.textContent).toContain('Next: Review accounts and permissions');
 expect(readConnectionSummary).not.toHaveBeenCalled();
 await act(async()=>root.render(<SettingsHub open initialScreen="connections" team={<p>Team</p>} google={<p>Google editor</p>} teamSummary="Team" teamDirty={false} onClose={()=>{}}/>));
 expect(host.querySelector('.connection-card .connection-badge')?.textContent).toBe('Not checked');
 const card=host.querySelector<HTMLButtonElement>('.connection-card')!;
 card.focus();expect(document.activeElement).toBe(card);expect(card.tagName).toBe('BUTTON');
 await act(async()=>card.click());expect(document.activeElement?.textContent).toBe('Google email & calendar');
});
it('launches fax work from the overview only with current preparation evidence and recovers after recheck',async()=>{
 const work=vi.fn(),editor=vi.fn();function Editor(){useEffect(()=>editor(),[]);return <p>Provider account editor</p>;}
 vi.mocked(readConnectionCatalog).mockResolvedValue({...catalog,core:false,messaging:true});
 vi.mocked(readConnectionSummary).mockResolvedValue({label:'Available',reason:'Account configured for drafts.',action:'Review fax options',tone:'neutral',faxReadiness:faxReady});
 await act(async()=>root.render(<SettingsHub open initialScreen="connections" team={<p>Team</p>} messaging={<Editor/>} teamSummary="Team" teamDirty={false} onClose={()=>{}} connectionIdentity={identity} onOpenMessagingWork={work}/>));
 const action=()=>host.querySelector<HTMLButtonElement>('.connection-task-action button')!;
 expect(editor).not.toHaveBeenCalled();expect(action().disabled).toBe(false);await act(async()=>action().click());expect(work).toHaveBeenCalledOnce();
 vi.mocked(readConnectionSummary).mockRejectedValueOnce(new Error('offline'));await click('Refresh connections');
 expect(action().disabled).toBe(true);await act(async()=>action().click());expect(work).toHaveBeenCalledOnce();
 expect(host.textContent).toContain('Current status is unknown');
 await click('Refresh connections');expect(action().disabled).toBe(false);expect(editor).not.toHaveBeenCalled();
});
