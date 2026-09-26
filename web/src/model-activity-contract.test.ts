import {expect,it} from 'vitest';
import {validateModelActivity,validActivityCursor} from './model-activity-contract';
import {activityContext,activityPage,activityId} from './model-activity-test-fixture';
import {WorkspaceApiError} from './workspace-api';
it('preserves an unknown instant in the negotiated practice-local time contract',()=>{
  const value=activityPage();value.contract_version=2;
  value.rows[0].encounter.starts_at=null;value.rows[0].encounter.source_local_start='2026-09-23T09:00:00.123456';
  expect(validateModelActivity(value,activityContext,'attention')).toEqual(value);
  value.contract_version=1;expect(()=>validateModelActivity(value,activityContext,'attention')).toThrow();
});
it.each(['2026-02-30T09:00:00','2026-09-23T09:00:00Z','2026-09-23T25:00:00'])('rejects a false local source time %s',local=>{
  const value=activityPage();value.contract_version=2;
  value.rows[0].encounter.starts_at=null;value.rows[0].encounter.source_local_start=local;
  expect(()=>validateModelActivity(value,activityContext,'attention')).toThrow();
});
it.each(['attention','recent'] as const)('validates closed %s activity with ordered observations and exact scope',view=>{const value=activityPage(view,20);expect(validateModelActivity(value,activityContext,view)).toEqual(value);});
it('binds the echoed page and rejects a repeated next cursor',()=>{const value=activityPage('attention',20),cursor='a1'+'b'.repeat(128);value.page={limit:20,cursor,next_cursor:'a1'+'c'.repeat(128),has_more:true};expect(validateModelActivity(value,activityContext,'attention',cursor)).toEqual(value);expect(()=>validateModelActivity(value,activityContext,'attention')).toThrow();value.page.next_cursor=cursor;expect(()=>validateModelActivity(value,activityContext,'attention',cursor)).toThrow();});
it.each(['a1'+'a'.repeat(127),'a1'+'A'.repeat(128),'a2'+'a'.repeat(128),'a1'+'a'.repeat(129),null,123])('rejects malformed cursor %s',cursor=>expect(validActivityCursor(cursor)).toBe(false));
it.each(['open','owner','scope','version','view','late','duplicate','order','bot','label','token','dispatch','usage','partial','count','has_more','limit','legacy','nested_open','boolean_count','token_bound','inherited'])('rejects invalid activity: %s',fault=>{
  const value=activityPage('attention',2) as any;
  if(fault==='open')value.prompt='private';if(fault==='owner')value.owner_id=activityId(99);if(fault==='scope')value.recovery_scope='b'.repeat(64);if(fault==='version')value.contract_version=true;
  if(fault==='view')value.rows[0].admission.state='completed';if(fault==='late')value.rows[0].admission.admitted_at='2027-01-01T00:00:00Z';
  if(fault==='duplicate')value.rows[1].admission.id=value.rows[0].admission.id;if(fault==='order')value.rows.reverse();
  if(fault==='bot')value.rows[0].bot.name='x'.repeat(41);if(fault==='label')value.rows[0].encounter.label='x'.repeat(201);
  if(fault==='token')value.rows[0].admission.input_tokens=0;if(fault==='dispatch')value.rows[0].admission.dispatch='unconfirmed';if(fault==='usage')value.usage.remaining_units=99;
  if(fault==='partial')value.usage.usage_complete=true;if(fault==='count')value.coverage.attention_total=0;if(fault==='has_more')value.page.has_more=true;
  if(fault==='limit')value.page.limit=21;if(fault==='legacy')value.coverage.legacy_rows_included=true;if(fault==='nested_open')value.rows[0].encounter.body='private';
  if(fault==='boolean_count')value.coverage.withheld_total=false;if(fault==='token_bound'){value.usage.verified_input_tokens=1e12;value.usage.verified_output_tokens=0;}
  const target=fault==='inherited'?Object.create(value):value;
  expect(()=>validateModelActivity(target,activityContext,'attention')).toThrow(WorkspaceApiError);
});
it('preserves verified zero tokens and explicitly partial aggregate usage',()=>{const value=activityPage();value.usage.verified_input_tokens=0;value.usage.verified_output_tokens=0;value.rows[0].admission={...value.rows[0].admission,usage:'verified',input_tokens:0,output_tokens:0};expect(validateModelActivity(value,activityContext,'attention').usage.usage_complete).toBe(false);});
it('allows empty withheld live pages without claiming complete history',()=>{const value=activityPage('recent',0);value.coverage.withheld_total=7;value.page.cursor='a1'+'a'.repeat(128);expect(validateModelActivity(value,activityContext,'recent',value.page.cursor).coverage.withheld_total).toBe(7);});
it('orders admissions by full server timestamp precision before UUID and rejects a future microsecond',()=>{
  const value=activityPage('attention',2);value.as_of='2026-09-22T13:00:00.000001Z';value.usage.as_of=value.as_of;
  value.rows[0].admission.id=activityId(402);value.rows[1].admission.id=activityId(401);
  value.rows[0].admission.admitted_at='2026-09-22T12:00:00.000001Z';value.rows[1].admission.admitted_at='2026-09-22T12:00:00.000002Z';
  expect(validateModelActivity(value,activityContext,'attention')).toEqual(value);
  value.rows[1].admission.admitted_at='2026-09-22T13:00:00.000002Z';expect(()=>validateModelActivity(value,activityContext,'attention')).toThrow();
});
it('does not accept usage timestamp mismatch hidden by millisecond rounding',()=>{const value=activityPage();value.as_of='2026-09-22T13:00:00.000001Z';value.usage.as_of='2026-09-22T13:00:00.000002Z';expect(()=>validateModelActivity(value,activityContext,'attention')).toThrow();});
it('returns independent closed data',()=>{const value=activityPage(),copy=validateModelActivity(value,activityContext,'attention');value.rows[0].encounter.label='Changed later';expect(copy.rows[0].encounter.label).toBe('Invented visit 1');});

it.each(['usage','policy','admission','array'])('rejects non-JSON %s accessors without invoking them',part=>{const value=activityPage();let invoked=false;const getter={get:()=>{invoked=true;throw new Error('private');},enumerable:true,configurable:true};if(part==='usage')Object.defineProperty(value.usage,'admitted_units',getter);if(part==='policy')Object.defineProperty(value.usage.policy!,'version',getter);if(part==='admission')Object.defineProperty(value.rows[0].admission,'state',getter);if(part==='array')Object.defineProperty(value.rows,'0',getter);expect(()=>validateModelActivity(value,activityContext,'attention')).toThrow(WorkspaceApiError);expect(invoked).toBe(false);});
