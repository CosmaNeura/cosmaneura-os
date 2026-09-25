import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,expect,it,vi} from 'vitest';
import {validateModelActivity,type ModelActivityPage} from './model-activity-contract';
import {modelActivityApi} from './model-activity-api';
import {AiActivityPanel} from './AiActivityPanel';
import pages from './__fixtures__/ai-activity/actual-activity-pages.json';
import paging from './__fixtures__/ai-activity/actual-activity-paging.json';
import scopes from './__fixtures__/ai-activity/actual-activity-private-scopes.json';
import unknown from './__fixtures__/ai-activity/actual-activity-unconfirmed.json';
import withheld from './__fixtures__/ai-activity/actual-activity-withheld.json';
import manifest from './__fixtures__/ai-activity/SOURCE_MANIFEST.json';
const raw=import.meta.glob('./__fixtures__/ai-activity/actual-*.json',{query:'?raw',import:'default',eager:true}) as Record<string,string>;
const {createHash}=await vi.importActual<{createHash:(algorithm:string)=>{update:(value:string)=>{digest:(encoding:string)=>string}}}>('node:crypto');
const vectors=[...Object.values(pages),...Object.values(paging),...Object.values(scopes),unknown,withheld] as ModelActivityPage[];
const context=(value:ModelActivityPage)=>({box_id:value.box_id,owner_id:value.owner_id,recovery_scope:value.recovery_scope});
let root:Root|undefined,host:HTMLDivElement|undefined;
afterEach(async()=>{if(root)await act(async()=>root!.unmount());root=undefined;host?.remove();host=undefined;vi.unstubAllGlobals();vi.unstubAllEnvs();});
it('consumes the byte-identical actual signed offline-JWT/PostgreSQL activity vectors',()=>{
  for(const [name,sha] of Object.entries(manifest))expect(createHash('sha256').update(raw['./__fixtures__/ai-activity/'+name]).digest('hex')).toBe(sha);
  for(const value of vectors)expect(validateModelActivity(value,context(value),value.view,value.page.cursor)).toEqual(value);
});
it('preserves actual older uncertainty, later verified usage, withheld source and independent staff observations',()=>{
  expect(unknown.rows[0].admission.state).toBe('unknown');expect(unknown.rows[0].admission.usage).toBe('verified');
  expect(withheld.rows).toHaveLength(0);expect(withheld.coverage.withheld_total).toBeGreaterThan(0);
  expect(scopes.owner.owner_id).not.toBe(scopes.staff.owner_id);expect(scopes.owner.recovery_scope).not.toBe(scopes.staff.recovery_scope);
  expect(paging.first.rows).toHaveLength(20);expect(paging.second.rows).toHaveLength(3);expect(paging.first.page.next_cursor).toBe(paging.second.page.cursor);
});
it('runs actual response vectors through fresh identity/API checks and mounted paging with no command dispatch',async()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8000');vi.stubEnv('VITE_DESKTOP_SYNTHETIC_ENABLED','false');vi.stubEnv('VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED','false');
  const first=paging.first as ModelActivityPage,second=paging.second as ModelActivityPage,scope=context(first),opened=vi.fn();
  const fetch=vi.fn(async(url:string,options:RequestInit)=>{
    expect(options.method).toBe('GET');expect(options.body).toBeUndefined();expect(new Headers(options.headers).get('Authorization')).toBe('Bearer invented-activity-token');
    const body=url.endsWith('/identity')?{contract_version:1,box_id:scope.box_id,actor_id:scope.owner_id,recovery_scope:scope.recovery_scope}:
      url.endsWith('/'+second.page.cursor)?second:first;
    return Response.json(body,{headers:{'Cache-Control':'no-store'}});
  });vi.stubGlobal('fetch',fetch);
  const identity={mode:'clerk_jwt' as const,getToken:async()=>'invented-activity-token'};
  expect(await modelActivityApi.read(identity,scope,'attention')).toEqual(first);
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
  await act(async()=>root!.render(<AiActivityPanel identity={identity} context={scope} locked={false} onOpenEncounter={opened} onAccessLost={()=>{}}/>));
  expect(host.querySelectorAll('.ai-activity-list>li')).toHaveLength(20);
  const more=[...host.querySelectorAll('button')].find(b=>b.textContent==='More activity')!;await act(async()=>more.click());
  expect(host.querySelectorAll('.ai-activity-list>li')).toHaveLength(3);expect(host.textContent).toContain('Outcome unconfirmed');expect(opened).not.toHaveBeenCalled();expect(fetch).toHaveBeenCalledTimes(6);
});
