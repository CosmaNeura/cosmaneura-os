import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{
  vi.stubEnv('VITE_COSMAS_ENV','synth_os');
  vi.stubEnv('VITE_WORKSPACE_ENABLED','true');
  vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');
  vi.stubEnv('VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED','true');
  vi.stubEnv('VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED','true');
});
vi.mock('./workspace-auth-headers',()=>({assertCurrentDesktopSession:()=>{},workspaceAuthHeaders:async()=>new Headers({'Content-Type':'application/json','Authorization':'Bearer invented-test-only'})}));
import {GoogleConnectionPanel} from './GoogleConnectionPanel';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';

const account={label:'Invented calendar member',email:'calendar@example.invalid'};
const connected={state:'connected',account,connected_at:'2026-10-26T10:00:00Z',capabilities:{mail:true,calendar:true}};
const summary={kind:'calendar',account,observed_at:'2026-10-26T10:05:00Z',more:false,items:[{id:'invented_event',subject:'Invented planning time',starts_at:'2026-10-27T14:00:00Z',ends_at:'2026-10-27T14:30:00Z',all_day:false,cancelled:false}]};
const response=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
let host:HTMLDivElement,root:Root,identity:AuthenticatedWorkspaceIdentity;
const opened=vi.fn(),denied=vi.fn(),fetcher=vi.fn<typeof fetch>();
beforeEach(()=>{
  vi.resetAllMocks();vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('fetch',fetcher);
  identity={mode:'clerk_jwt',getToken:async()=>null};host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});
const mount=(locks:{calendarWorkLocked?:boolean;messageWorkLocked?:boolean}={})=>act(async()=>root.render(<GoogleConnectionPanel identity={identity} onAuthenticationLost={denied} onOpenCalendarWork={opened} {...locks}/>));
const button=(label:string)=>[...host.querySelectorAll('button')].find(b=>b.textContent===label);
async function click(label:string){await act(async()=>{const target=button(label);expect(target,label).toBeDefined();expect(target!.disabled,label).toBe(false);target!.click();});}
const commands=()=>fetcher.mock.calls.map(([url,init])=>({path:new URL(String(url)).pathname,body:JSON.parse(String(init?.body)),header:new Headers(init?.headers).get('X-Cosmas-Google-Connection')}));
const calendarRow=()=>host.querySelector('[data-connection-operation="google.calendar_summaries"]')!;

it('verifies the basic calendar read through the real session transport while work is enabled and separately available',async()=>{
  fetcher.mockResolvedValueOnce(response(connected)).mockResolvedValueOnce(response(summary)).mockResolvedValueOnce(response({...summary,observed_at:'2026-10-26T10:06:00Z'}));
  await mount();
  expect(calendarRow().textContent).toContain('Permission granted; a read has not been verified.');
  expect(button('📅 Work with calendar')).toBeDefined();
  await click('View next 7 days');
  expect(host.querySelector('[aria-label="Upcoming Google events"]')?.textContent).toContain('Invented planning time');
  expect(calendarRow().textContent).toContain('Verified in this session');
  expect(opened).not.toHaveBeenCalled();
  await click('Refresh calendar');
  await click('📅 Work with calendar');
  expect(opened).toHaveBeenCalledOnce();expect(denied).not.toHaveBeenCalled();
  expect(commands()).toEqual([
    {path:'/connections/google/session',body:{action:'status',include_capabilities:true},header:'1'},
    {path:'/connections/google/session',body:{action:'calendar'},header:'1'},
    {path:'/connections/google/session',body:{action:'calendar'},header:'1'},
  ]);
  for(const [,init] of fetcher.mock.calls)expect(init).toMatchObject({method:'POST',credentials:'omit',redirect:'error',cache:'no-store'});
  await mount({calendarWorkLocked:true});expect(button('Refresh calendar')?.disabled).toBe(true);expect(button('📅 Work with calendar')?.disabled).toBe(true);
  await mount({messageWorkLocked:true});expect(button('Refresh calendar')?.disabled).toBe(true);
  expect(fetcher).toHaveBeenCalledTimes(3);
});

it('offers explicit calendar consent instead of a content read when permission is missing, even with work enabled',async()=>{
  const params=new URLSearchParams({client_id:'invented.apps.googleusercontent.com',redirect_uri:'https://api.example.invalid/connections/google/callback',response_type:'code',access_type:'offline',include_granted_scopes:'false',scope:'openid email https://www.googleapis.com/auth/gmail.metadata https://www.googleapis.com/auth/calendar.events.readonly',state:'s'.repeat(43),prompt:'consent select_account',code_challenge_method:'S256',code_challenge:'c'.repeat(43)});
  fetcher.mockResolvedValueOnce(response({...connected,capabilities:{mail:true,calendar:false}})).mockResolvedValueOnce(response({authorization_url:`https://accounts.google.com/o/oauth2/v2/auth?${params}`,expires_at:new Date(Date.now()+600000).toISOString()}));
  await mount();expect(calendarRow().textContent).toContain('Permission needed');expect(button('View next 7 days')).toBeUndefined();expect(button('📅 Work with calendar')).toBeDefined();
  await mount({calendarWorkLocked:true});expect(button('Add calendar access')?.disabled).toBe(true);
  await mount();await click('Add calendar access');
  expect(host.querySelector('a')?.textContent).toBe('Continue with Google');
  expect(commands().map(c=>({path:c.path,body:c.body}))).toEqual([{path:'/connections/google/session',body:{action:'status',include_capabilities:true}},{path:'/connections/google/session',body:{action:'start'}}]);
  expect(opened).not.toHaveBeenCalled();expect(denied).not.toHaveBeenCalled();
});

it('removes basic calendar proof and titles when the current account changes, without opening work or replaying the read',async()=>{
  fetcher.mockResolvedValueOnce(response(connected)).mockResolvedValueOnce(response(summary)).mockResolvedValueOnce(response({...connected,account:{label:'Other invented member',email:'other@example.invalid'}}));
  await mount();await click('View next 7 days');expect(calendarRow().textContent).toContain('Verified in this session');
  await click('Check Google connection');
  expect(host.textContent).not.toContain('Invented planning time');expect(calendarRow().textContent).not.toContain('Verified in this session');expect(button('Refresh calendar')).toBeUndefined();expect(button('View next 7 days')).toBeDefined();
  expect(commands().map(c=>c.body.action)).toEqual(['status','calendar','status']);expect(opened).not.toHaveBeenCalled();expect(denied).not.toHaveBeenCalled();
});
