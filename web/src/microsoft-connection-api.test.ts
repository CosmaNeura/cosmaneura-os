import {afterEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_MICROSOFT_CONNECTION_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');});
vi.mock('./workspace-auth-headers',()=>({assertCurrentDesktopSession:()=>{},workspaceAuthHeaders:async()=>new Headers({'Content-Type':'application/json','Authorization':'Bearer invented'})}));
import {microsoftConnectionRequest,validateMicrosoftResponse,validMicrosoftAuthorizationUrl} from './microsoft-connection-api';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
const status={state:'connected',account:{label:'Invented account',email:'invented@example.invalid'},connected_at:new Date().toISOString()};
afterEach(()=>vi.unstubAllGlobals());
it('sends the closed no-store command and validates the private account response',async()=>{
 const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify(status),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));vi.stubGlobal('fetch',fetcher);
 expect(await microsoftConnectionRequest(identity,'status')).toMatchObject({state:'connected'});
 expect(fetcher.mock.calls[0][1]).toMatchObject({method:'POST',body:'{"action":"status"}',credentials:'omit',redirect:'error'});
 expect(fetcher.mock.calls[0][1].headers.get('X-Cosmas-Microsoft-Connection')).toBe('1');
});
it('rejects stale native identity before dispatch and after a late response',async()=>{
 let current=false;const native={...identity,nativeSession:{revision:'invented',isCurrent:()=>current}};
 const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);await expect(microsoftConnectionRequest(native,'status')).rejects.toThrow();expect(fetcher).not.toHaveBeenCalled();
 current=true;fetcher.mockImplementation(async()=>{current=false;return new Response(JSON.stringify(status),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});});
 await expect(microsoftConnectionRequest(native,'status')).rejects.toThrow();
});
it('rejects credentials, malformed data and extra grants',()=>{
 expect(()=>validateMicrosoftResponse({...status,access_token:'never-allowed'},'status')).toThrow();
 expect(()=>validateMicrosoftResponse({kind:'mail',account:status.account,more:false,observed_at:new Date().toISOString(),items:[{id:'1',subject:'x',sender:'x',received_at:'invalid',is_read:true}]},'mail')).toThrow();
 const q=new URLSearchParams({client_id:'22222222-2222-4222-8222-222222222222',redirect_uri:'https://api.example.invalid/connections/microsoft/callback',response_type:'code',response_mode:'query',scope:'offline_access User.Read Mail.Read Calendars.Read',state:'s'.repeat(43),prompt:'select_account',code_challenge_method:'S256',code_challenge:'c'.repeat(43)});
 const url=()=>`https://login.microsoftonline.com/11111111-1111-4111-8111-111111111111/oauth2/v2.0/authorize?${q}`;
 expect(validMicrosoftAuthorizationUrl(url())).toBe(true);q.set('scope','Mail.Send');expect(validMicrosoftAuthorizationUrl(url())).toBe(false);
});
