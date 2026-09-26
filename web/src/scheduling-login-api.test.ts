import {afterEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>vi.stubEnv('VITE_WORKSPACE_SCHEDULING_LOGIN_ENABLED','true'));
vi.mock('./scheduling-api',()=>({SCHEDULING_BUILD:true}));
vi.mock('./workspace-auth-headers',()=>({assertCurrentDesktopSession:()=>{},workspaceAuthHeaders:async()=>new Headers({'Content-Type':'application/json','Authorization':'Bearer invented'})}));
import {schedulingLoginRequest} from './scheduling-login-api';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
afterEach(()=>vi.unstubAllGlobals());
it('uses the closed command and validates the no-store status without persisting a credential',async()=>{
 const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify({state:'connected',label:'Invented practice',connected_at:new Date().toISOString()}),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));vi.stubGlobal('fetch',fetcher);
 expect(await schedulingLoginRequest(identity,'status')).toMatchObject({state:'connected'});
 expect(fetcher.mock.calls[0][1]).toMatchObject({method:'POST',body:'{"action":"status"}',credentials:'omit',redirect:'error'});
 expect(fetcher.mock.calls[0][1].headers.get('X-Cosmas-Scheduling-Login')).toBe('1');
});
it('rejects stale native sessions and already-canceled calls before sending',async()=>{
 const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);
 await expect(schedulingLoginRequest({...identity,nativeSession:{revision:'invented',isCurrent:()=>false}},'start')).rejects.toThrow();
 const cancel=new AbortController();cancel.abort();await expect(schedulingLoginRequest(identity,'start',cancel.signal)).rejects.toThrow();expect(fetcher).not.toHaveBeenCalled();
});
