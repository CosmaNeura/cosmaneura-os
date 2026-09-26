import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,expect,it,vi} from 'vitest';
import {EncounterWorkspace} from './EncounterWorkspace';
import {memoryDraftStorage} from './draft-test-fixture';
import vector from './__fixtures__/ai-activity/actual-main-activity.json';
import raw from './__fixtures__/ai-activity/actual-main-activity.json?raw';
const {webcrypto,createHash}=await vi.importActual<{webcrypto:Crypto;createHash:(name:string)=>{update:(value:string)=>{digest:(encoding:string)=>string}}}>('node:crypto');
let host:HTMLDivElement|undefined,root:Root|undefined;
afterEach(async()=>{if(root)await act(async()=>root!.unmount());root=undefined;host?.remove();host=undefined;vi.unstubAllGlobals();vi.unstubAllEnvs();});
it('replays the byte-identical signed main-app page, identity, team and full workspace through real API and mounted selection',async()=>{
 expect(createHash('sha256').update(raw).digest('hex')).toBe('fa800f20a30adc418ac316ecaadbc899bee8070d6ebf0d8b9c43608b4f48d7cc');expect(vector.model_calls).toBe(0);expect(vector.ledger_unchanged).toBe(true);
 vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('crypto',webcrypto);vi.stubEnv('VITE_AI_ACTIVITY_ENABLED','true');vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8000');vi.stubEnv('VITE_DESKTOP_SYNTHETIC_ENABLED','false');vi.stubEnv('VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED','false');
 const paths:string[]=[];vi.stubGlobal('fetch',vi.fn(async(url:string,options:RequestInit)=>{
   const path=new URL(url).pathname;paths.push(path);expect(options.method).toBe('GET');expect(options.body).toBeUndefined();expect(options.cache).toBe('no-store');expect(options.redirect).toBe('error');expect(new Headers(options.headers).get('Authorization')).toBe('Bearer invented-main-replay');
   const body=path==='/provider-team'?vector.current_team:path==='/provider-team/identity'?vector.signed_identity:path==='/provider-team/activity/attention'?vector.enabled:path==='/workspaces/'+vector.fresh_encounter.id?vector.fresh_encounter:path==='/provider-team/setup'?{detail:'team_setup_unavailable'}:undefined;
   expect(body,'Only reviewed GET paths are permitted: '+path).toBeDefined();return Response.json(body,{status:path==='/provider-team/setup'?404:200,headers:{'Cache-Control':'no-store'}});
 }));
 const identity={mode:'clerk_jwt' as const,getToken:async()=>'invented-main-replay'};host=document.createElement('div');document.body.append(host);root=createRoot(host);
 const button=(name:string)=>[...host!.querySelectorAll<HTMLButtonElement>('button')].find(b=>!b.closest('[hidden]')&&(b.textContent?.replace(/[←→›↗]/g,'').trim()===name||[...b.querySelectorAll('strong')].some(s=>s.textContent?.trim()===name)));
 const wait=async(check:()=>void)=>{for(let i=0;i<100;i++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,5));try{check();done=true;}catch{}});if(done)return;}check();};
 const click=async(name:string)=>{await wait(()=>{expect(button(name),name).toBeTruthy();expect(button(name)!.matches(':disabled'),name).toBe(false);});await act(async()=>button(name)!.click());};
 await act(async()=>root!.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));
 await click('Team settings');await click('Your team');await click('Team preferences');await click('AI activity');await wait(()=>expect(host!.querySelector('.ai-activity-list')?.textContent).toContain(vector.enabled.rows[0].encounter.label));
 await click('Open encounter');await wait(()=>expect(host!.querySelector('.settings-hub')?.hasAttribute('hidden')).toBe(true));
 expect(host.querySelector('#turn-'+vector.enabled.rows[0].encounter.entry_id)).toBeTruthy();expect(host.querySelector('.team-roster button[aria-pressed="true"] strong')?.textContent).toBe('Visit Prep');
 expect(paths.filter(p=>p==='/workspaces/'+vector.fresh_encounter.id)).toHaveLength(2);expect(paths.filter(p=>p==='/provider-team/activity/attention')).toHaveLength(2);expect(paths.some(p=>p.includes('/open')||p.includes('/conversation')||p.includes('/resolve'))).toBe(false);
});
