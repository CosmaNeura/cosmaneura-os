import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED','true');});
vi.mock('./workspace-auth-headers',()=>({assertCurrentDesktopSession:()=>{},workspaceAuthHeaders:async()=>new Headers({'Content-Type':'application/json','Authorization':'Bearer invented'})}));
import {googleCalendarApi,GoogleCalendarRefusal,googleCalendarReviewProvesNoCommit,googleCalendarEventHash,googleCalendarSourceContent,googleCalendarValidUntil,validGoogleCalendarReceipt,validGoogleCalendarObservation,validGoogleCalendarReviewRequest,type GoogleCalendarReceipt} from './google-calendar-api';
import {calendarReceipt,calendarBody,calendarReview,calendarSha,calendarUuid,calendarVisit} from './google-calendar-fixtures.test-support';
import {modelCanonical} from './model-work-request';
import {teamCanonical} from './team-setup-request';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};let receipt:GoogleCalendarReceipt;
const response=(v:unknown,status=200,headers?:Record<string,string>)=>new Response(JSON.stringify(v),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store',...headers}});
beforeEach(async()=>{vi.stubGlobal('crypto',webcrypto);receipt=await calendarReceipt();});afterEach(()=>{vi.unstubAllGlobals();vi.useRealTimers();});
it('binds Unicode observation UTF8 and ASCII model event digests, with no private custody accepted',async()=>{expect(await validGoogleCalendarReceipt(receipt)).toBe(true);const event=receipt.observation.items[0];expect(await googleCalendarEventHash(event)).toBe(await calendarSha(modelCanonical(event)));expect(await googleCalendarEventHash(event)).not.toBe(await calendarSha(teamCanonical(event)));expect(await validGoogleCalendarReceipt({...receipt,custody:{grant:'never'}})).toBe(false);expect(await validGoogleCalendarReceipt({...receipt,payload_sha256:'f'.repeat(64)})).toBe(false);expect(await validGoogleCalendarReceipt({...receipt,observation:{...receipt.observation,description:'not allowed'}})).toBe(false);});
it.each(['duplicate','extra','outside','negative','window','allday','farallday','observed','label'])('rejects %s event/window contracts without broader calendar data',async mode=>{const o=structuredClone(receipt.observation);if(mode==='duplicate')o.items.push(o.items[0]);if(mode==='extra')Object.assign(o.items[0],{attendees:['never']});if(mode==='outside'){o.items[0].starts_at='2026-10-10T12:00:00Z';o.items[0].ends_at='2026-10-10T13:00:00Z';}if(mode==='negative')o.items[0].ends_at=o.items[0].starts_at;if(mode==='window')o.window.ends_at='2026-10-10T12:00:00Z';if(mode==='allday')o.items[1].ends_at='2026-10-05';if(mode==='farallday'){o.items[1].starts_at='2026-10-20';o.items[1].ends_at='2026-10-21';}if(mode==='observed')o.observed_at=o.window.ends_at;if(mode==='label')o.account.label='x'.repeat(257);expect(validGoogleCalendarObservation(o)).toBe(false);});
it('dispatches exactly one bounded observation with pinned header and key',async()=>{const fetcher=vi.fn().mockResolvedValue(response(receipt));vi.stubGlobal('fetch',fetcher);const body={action:'observe' as const,idempotency_key:receipt.observation_key};expect(await googleCalendarApi.observe(identity,body)).toEqual(receipt);expect(fetcher).toHaveBeenCalledOnce();const [url,init]=fetcher.mock.calls[0];expect(url).toMatch(/\/connections\/google\/calendar-summaries$/);expect(init).toMatchObject({body:JSON.stringify(body),method:'POST',credentials:'omit',redirect:'error',cache:'no-store'});expect(init.headers.get('X-Cosmas-Google-Calendar')).toBe('1');expect(init.headers.has('X-Cosmas-Model-Contract')).toBe(false);});
it('negotiates private-notebook support and falls back only for a named older status request refusal',async()=>{
 const status={contract_version:1,state:'connected',calendar_read:true,account:receipt.observation.account};
 const fetcher=vi.fn().mockResolvedValueOnce(response({...status,private_notebook_review:true}));vi.stubGlobal('fetch',fetcher);
 expect(await googleCalendarApi.status(identity)).toMatchObject({private_notebook_review:true});expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({action:'status',include_private_notebook:true});
 fetcher.mockClear();fetcher.mockResolvedValueOnce(response({detail:'invalid_google_calendar_request'},422)).mockResolvedValueOnce(response(status));
 expect(await googleCalendarApi.status(identity)).not.toHaveProperty('private_notebook_review');expect(fetcher.mock.calls.map(c=>JSON.parse(c[1].body))).toEqual([{action:'status',include_private_notebook:true},{action:'status'}]);
});
it('binds private review without a visit assertion and rejects a patient-linked receipt or mixed confirmations',async()=>{
 const {reviewed_visit:_,...shared}=await calendarBody(receipt),body={...shared,reviewed_private_notebook:true as const};expect(validGoogleCalendarReviewRequest(body)).toBe(true);
 expect(validGoogleCalendarReviewRequest({...body,reviewed_visit:true})).toBe(false);expect(validGoogleCalendarReviewRequest({...body,reviewed_private_notebook:false})).toBe(false);
 const value=await calendarReview(receipt,body),fetcher=vi.fn().mockResolvedValueOnce(response(value));vi.stubGlobal('fetch',fetcher);
 expect((await googleCalendarApi.review(identity,calendarVisit.id,body,receipt)).workspace.appointment_id).toBeNull();expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual(body);
 fetcher.mockResolvedValueOnce(response({...value,workspace:{...value.workspace,appointment_id:calendarUuid(900)}}));await expect(googleCalendarApi.review(identity,calendarVisit.id,body,receipt)).rejects.toMatchObject({status:502});
});
it('recognizes only the named private destination conflict as proof that no source was added',async()=>{
 const {reviewed_visit:_,...shared}=await calendarBody(receipt),body={...shared,reviewed_private_notebook:true as const};vi.stubGlobal('fetch',vi.fn().mockResolvedValue(response({detail:'google_calendar_private_notebook_required'},409)));
 const error=await googleCalendarApi.review(identity,calendarVisit.id,body,receipt).catch(e=>e);expect(error).toBeInstanceOf(GoogleCalendarRefusal);expect(googleCalendarReviewProvesNoCommit(error)).toBe(true);expect(googleCalendarReviewProvesNoCommit(new WorkspaceApiError(409))).toBe(false);
});
it('resolves or inspects original immutable observations without another provider read',async()=>{const fetcher=vi.fn().mockResolvedValueOnce(response({status:'unconfirmed',observation_id:receipt.observation_id,observation_key:receipt.observation_key})).mockResolvedValueOnce(response(receipt)).mockResolvedValueOnce(response(receipt));vi.stubGlobal('fetch',fetcher);expect(await googleCalendarApi.resolve(identity,receipt.observation_key)).toMatchObject({status:'unconfirmed'});expect(await googleCalendarApi.resolve(identity,receipt.observation_key)).toEqual(receipt);expect(await googleCalendarApi.inspect(identity,receipt)).toEqual(receipt);expect(fetcher.mock.calls.map(c=>JSON.parse(c[1].body).action)).toEqual(['resolve','resolve','inspect']);fetcher.mockResolvedValueOnce(response({...receipt,observation_key:calendarUuid(99)}));await expect(googleCalendarApi.resolve(identity,receipt.observation_key)).rejects.toMatchObject({status:502});});
it('saves exact selected source separately from a clinical note and verifies every hash/revision',async()=>{const body=await calendarBody(receipt),value=await calendarReview(receipt,body),fetcher=vi.fn().mockResolvedValueOnce(response(value));vi.stubGlobal('fetch',fetcher);expect(await googleCalendarApi.review(identity,calendarVisit.id,body,receipt)).toEqual(value);for(const wrong of [{...value,request_sha256:'f'.repeat(64)},{...value,source:{...value.source,source_sha256:'f'.repeat(64)}},{...value,workspace:{...value.workspace,entries:[{...value.workspace.entries[0],content:'changed'}]}},{...value,entry_revision:7}]){fetcher.mockResolvedValueOnce(response(wrong));await expect(googleCalendarApi.review(identity,calendarVisit.id,body,receipt)).rejects.toMatchObject({status:502});}});
it('rejects a modified event commitment or malformed anchor before dispatch',async()=>{const body=await calendarBody(receipt),fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);await expect(googleCalendarApi.review(identity,calendarVisit.id,{...body,event_sha256:'f'.repeat(64)},receipt)).rejects.toMatchObject({status:422});await expect(googleCalendarApi.review(identity,calendarVisit.id,body,{...receipt,payload_sha256:'f'.repeat(64)})).rejects.toMatchObject({status:422});expect(fetcher).not.toHaveBeenCalled();});
it('confirms an exact masked historical save but never treats withheld text as usable',async()=>{const body=await calendarBody(receipt),value=await calendarReview(receipt,body),masked={...value,source_withheld:true,workspace:{...value.workspace,revision:9,entries:value.workspace.entries.map(e=>({...e,content:'',source_label:'Unavailable calendar source',calendar_source_state:'unavailable'}))}},fetcher=vi.fn().mockResolvedValueOnce(response(masked));vi.stubGlobal('fetch',fetcher);expect(await googleCalendarApi.review(identity,calendarVisit.id,body,receipt)).toMatchObject({source_withheld:true});fetcher.mockResolvedValueOnce(response({...masked,workspace:value.workspace}));await expect(googleCalendarApi.review(identity,calendarVisit.id,body,receipt)).rejects.toMatchObject({status:502});});
it.each<Record<string,string>>([{'Cache-Control':'private'},{'Content-Type':'text/html'},{'Content-Encoding':'gzip'}])('rejects unsafe response metadata without retry',async(headers)=>{const fetcher=vi.fn().mockResolvedValue(response(receipt,200,headers));vi.stubGlobal('fetch',fetcher);await expect(googleCalendarApi.observe(identity,{action:'observe',idempotency_key:receipt.observation_key})).rejects.toMatchObject({status:502});expect(fetcher).toHaveBeenCalledOnce();});
it('limits response bytes and preserves exact read key without automatic retry',async()=>{const fetcher=vi.fn().mockResolvedValue(response({padding:'x'.repeat(131073)}));vi.stubGlobal('fetch',fetcher);await expect(googleCalendarApi.observe(identity,{action:'observe',idempotency_key:receipt.observation_key})).rejects.toMatchObject({status:502});expect(fetcher).toHaveBeenCalledOnce();});
it('refuses stale authenticated session after awaited transport before returning source contents',async()=>{let current=true;const auth:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null,nativeSession:{revision:'1',isCurrent:()=>current}};vi.stubGlobal('fetch',vi.fn(async()=>{current=false;return response(receipt);}));await expect(googleCalendarApi.observe(auth,{action:'observe',idempotency_key:receipt.observation_key})).rejects.toMatchObject({status:401});});
it('computes conservative date-only expiry without inventing an event timezone',()=>{expect(googleCalendarValidUntil(receipt.observation,receipt.observation.items[0])).toBe(Date.parse('2026-10-02T15:00:00Z'));expect(googleCalendarValidUntil(receipt.observation,receipt.observation.items[1])).toBe(Date.parse('2026-10-05T00:00:00Z'));});

it('matches the independently specified backend source text with real newlines and Unicode',()=>{
 const event=receipt.observation.items[0];
 const expected=[
  'Google calendar summary (frozen observation)',
  'Account: Invented clinician café <clinician@example.invalid>',
  'Event: Invented café follow-up 😀 <img src="https://example.invalid">',
  'Starts: 2026-10-02T13:00:00Z',
  'Ends (exclusive): 2026-10-02T15:00:00Z',
  'All day: no',
  'Status: not marked cancelled',
  'Observed: 2026-10-02T12:00:00Z',
  'Window: 2026-10-02T12:00:00Z to 2026-10-09T12:00:00Z',
  'Coverage: partial (more events available)',
  '',
  'This observed summary does not establish current availability or a booking.'
 ].join(String.fromCharCode(10));
 expect(googleCalendarSourceContent(receipt.observation,event)).toBe(expected);
 expect(googleCalendarSourceContent(receipt.observation,event)).not.toContain(String.fromCharCode(92)+'n');
});

it('preserves only the exact named service404 as a typed refusal without claiming no commit',async()=>{
 const fetcher=vi.fn().mockResolvedValue(response({detail:'google_calendar_unavailable'},404));vi.stubGlobal('fetch',fetcher);
 const cause=await googleCalendarApi.status(identity).catch(e=>e);
 expect(cause).toBeInstanceOf(GoogleCalendarRefusal);expect(cause).toMatchObject({status:404,code:'google_calendar_unavailable'});
 expect(googleCalendarReviewProvesNoCommit(cause)).toBe(false);expect(fetcher).toHaveBeenCalledOnce();
});
it.each([401,403,426])('does not reinterpret named calendar errors with authority status%s',async status=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(response({detail:'google_calendar_unavailable'},status)));
 const cause=await googleCalendarApi.status(identity).catch(e=>e);expect(cause).toBeInstanceOf(WorkspaceApiError);expect(cause).not.toBeInstanceOf(GoogleCalendarRefusal);expect(cause.status).toBe(status);
});
it.each(['unknown','extra','duplicate','invalid-json','wrong-type','wrong-content-type','encoded','oversized'])('keeps %s404 fail-closed instead of treating it as service unavailability',async mode=>{
 let body=JSON.stringify({detail:'google_calendar_unavailable'});const headers:Record<string,string>={'Content-Type':'application/json','Cache-Control':'no-store'};
 if(mode==='unknown')body=JSON.stringify({detail:'calendar_not_found'});if(mode==='extra')body=JSON.stringify({detail:'google_calendar_unavailable',extra:true});
 if(mode==='duplicate')body='{"detail":"google_calendar_unavailable","detail":"google_calendar_unavailable"}';if(mode==='invalid-json')body='{';
 if(mode==='wrong-type')body=JSON.stringify({detail:null});if(mode==='wrong-content-type')headers['Content-Type']='text/plain';if(mode==='encoded')headers['Content-Encoding']='gzip';if(mode==='oversized')body=' '.repeat(2048)+body;
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(body,{status:404,headers})));
 const cause=await googleCalendarApi.status(identity).catch(e=>e);expect(cause).toBeInstanceOf(WorkspaceApiError);expect(cause).not.toBeInstanceOf(GoogleCalendarRefusal);expect(cause.status).toBe(404);
});
