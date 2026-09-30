import {afterEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');});
vi.mock('./workspace-auth-headers',()=>({assertCurrentDesktopSession:()=>{},workspaceAuthHeaders:async()=>new Headers({'Content-Type':'application/json','Authorization':'Bearer invented'})}));
import {googleConnectionRequest,validateGoogleResponse,validGoogleAuthorizationUrl} from './google-connection-api';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
const status={state:'connected',account:{label:'Invented account',email:'invented@example.invalid'},connected_at:new Date().toISOString()};
afterEach(()=>vi.unstubAllGlobals());
it('accepts bounded calendar summaries and rejects ambiguous dates or unrequested contents',()=>{
 const event={id:'invented',subject:'Invented visit',starts_at:'2026-11-01',ends_at:'2026-11-02',all_day:true,cancelled:false};
 const view={kind:'calendar',account:status.account,more:false,observed_at:new Date().toISOString(),items:[event]};
 expect(validateGoogleResponse(view,'calendar')).toEqual(view);
 for(const items of [[event,event],[{...event,starts_at:'2026-02-30'}],[{...event,description:'not projected'}],
  Array.from({length:26},(_,i)=>({...event,id:'event'+i}))]){
  expect(()=>validateGoogleResponse({...view,items},'calendar')).toThrow();
 }
});
it('projects only the known calendar-consent error from a no-store bounded response',async()=>{
 const respond=(detail:string)=>new Response(JSON.stringify({detail}),{status:409,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
 vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce(respond('google_calendar_consent_required')).mockResolvedValueOnce(respond('untrusted secret')));
 await expect(googleConnectionRequest(identity,'calendar')).rejects.toMatchObject({status:409,code:'google_calendar_consent_required'});
 await expect(googleConnectionRequest(identity,'calendar')).rejects.toMatchObject({status:409,code:undefined});
});
it('sends the closed no-store command and validates the private account response',async()=>{
 const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify(status),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));vi.stubGlobal('fetch',fetcher);
 expect(await googleConnectionRequest(identity,'status')).toMatchObject({state:'connected'});
 expect(fetcher.mock.calls[0][1]).toMatchObject({method:'POST',body:'{"action":"status"}',credentials:'omit',redirect:'error'});
 expect(fetcher.mock.calls[0][1].headers.get('X-Cosmas-Google-Connection')).toBe('1');
});
it('rejects stale native identity before dispatch and after a late response',async()=>{
 let current=false;const native={...identity,nativeSession:{revision:'invented',isCurrent:()=>current}};
 const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);await expect(googleConnectionRequest(native,'status')).rejects.toThrow();expect(fetcher).not.toHaveBeenCalled();
 current=true;fetcher.mockImplementation(async()=>{current=false;return new Response(JSON.stringify(status),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});});
 await expect(googleConnectionRequest(native,'status')).rejects.toThrow();
});
it('rejects credentials, malformed data and extra grants',()=>{
 expect(()=>validateGoogleResponse({...status,access_token:'never-allowed'},'status')).toThrow();
 expect(()=>validateGoogleResponse({kind:'mail',account:status.account,more:false,observed_at:new Date().toISOString(),items:[{id:'1',subject:'x',sender:'x',received_at:'invalid',is_read:true}]},'mail')).toThrow();
 const q=new URLSearchParams({client_id:'invented.apps.googleusercontent.com',redirect_uri:'https://api.example.invalid/connections/google/callback',response_type:'code',access_type:'offline',include_granted_scopes:'false',scope:'openid email https://www.googleapis.com/auth/gmail.metadata',state:'s'.repeat(43),prompt:'consent select_account',code_challenge_method:'S256',code_challenge:'c'.repeat(43)});
 const url=()=>`https://accounts.google.com/o/oauth2/v2/auth?${q}`;
 expect(validGoogleAuthorizationUrl(url())).toBe(true);q.set('scope','https://www.googleapis.com/auth/gmail.send');expect(validGoogleAuthorizationUrl(url())).toBe(false);
});

it('rejects duplicate and excess Gmail summaries',()=>{
 const row={id:'message_1',subject:'Invented subject',sender:'sender@example.invalid',received_at:new Date().toISOString(),is_read:false};
 const view={kind:'mail',account:status.account,more:true,observed_at:new Date().toISOString(),items:[row]};
 expect(validateGoogleResponse(view,'mail')).toEqual(view);
 expect(()=>validateGoogleResponse({...view,items:[row,row]},'mail')).toThrow();
 expect(()=>validateGoogleResponse({...view,items:Array.from({length:11},(_,i)=>({...row,id:'m'+i}))},'mail')).toThrow();
});
