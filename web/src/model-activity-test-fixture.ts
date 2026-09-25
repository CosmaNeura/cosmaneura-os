import type {ActivityView,ModelActivityPage,AiActivityContext} from './model-activity-contract';
export const activityId=(n:number)=>'00000000-0000-4000-8000-'+String(n).padStart(12,'0');
export const activityContext:AiActivityContext={box_id:activityId(1),owner_id:activityId(2),recovery_scope:'a'.repeat(64)};
export const activityIdentity={contract_version:1 as const,box_id:activityContext.box_id,actor_id:activityContext.owner_id,recovery_scope:activityContext.recovery_scope};
export function activityPage(view:ActivityView='attention',amount=1):ModelActivityPage{
  const ids=Array.from({length:amount},(_,n)=>n+1);if(view==='recent')ids.reverse();
  return {...activityContext,contract_version:1,view,as_of:'2026-09-22T13:00:00Z',page:{limit:20,cursor:null,next_cursor:null,has_more:false},
    coverage:{rows:'durable_admissions_only',paging:'live_current_access',attention_total:view==='attention'?amount:0,recent_total:view==='recent'?amount:0,withheld_total:0,legacy_rows_included:false},
    usage:{contract_version:1,policy:{version:1,max_attempts_per_24h:50},team_revision:1,as_of:'2026-09-22T13:00:00Z',window_start:'2026-09-21T13:00:00Z',admitted_units:amount,occupied_units:amount,remaining_units:50-amount,pending_units:view==='attention'?amount:0,unknown_units:0,verified_input_tokens:null,verified_output_tokens:null,usage_complete:false,coverage:'new_admissions_and_retained_legacy_records'},
    rows:ids.map(n=>({kind:'conversation',bot:{address:'chief',agent_id:activityId(3),role:'chief',name:'Invented Chief',team_revision:1},
      encounter:{workspace_id:activityId(100+n),appointment_id:activityId(200+n),entry_id:activityId(300+n),label:'Invented visit '+n,starts_at:'2026-09-22T10:00:00Z'},
      admission:{id:activityId(400+n),state:view==='attention'?'running':'completed',unit:1,admitted_at:'2026-09-22T12:00:00Z',dispatch:'started',usage:'unknown',input_tokens:null,output_tokens:null}}))};
}
