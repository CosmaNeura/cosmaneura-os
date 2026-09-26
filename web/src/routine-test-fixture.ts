import type { BriefSchedule, Routine, WorkBrief } from "./routine-api";
export const routineId = (n:number) => "00000000-0000-4000-8000-" + String(n).padStart(12,"0");
export const schedule = ():BriefSchedule => ({kind:"practice_work_brief",enabled:true,timezone:"UTC",at:"08:00",
  weekdays:[1,2,3,4,5],quiet_start:"18:00",quiet_end:"07:00",max_runs_per_seven_days:5});
export const brief = ():WorkBrief => ({id:routineId(1),scheduled_at:"2026-09-21T08:00:00Z",completed_at:"2026-09-21T08:00:04Z",local_date:"2026-09-21",
  kind:"practice_work_brief",items:[{ticket_id:routineId(2),revision_id:routineId(3),payload_hash:"a".repeat(64),version:2,state:"sent",
    body:"Confirm invented appointment",due_date:"2026-09-20",responsible:{id:routineId(4),name:"Invented provider",available:true},pending_offer:false,human_completion:false}],
  matching_items:1,counts:{open:1,overdue:1,awaiting_acceptance:0,responsible_unavailable:0,verified_complete:0},withheld_sources:false,truncated:false,model_used:false});
export const routine = (bot="chief"):Routine => ({bot,agent_id:routineId(5),revision:1,team_revision:1,configuration:schedule(),status:"already_run",
  next_scheduled_at:"2026-09-22T08:00:00Z",runs:[{id:routineId(1),scheduled_at:"2026-09-21T08:00:00Z",completed_at:"2026-09-21T08:00:04Z",local_date:"2026-09-21"}]});
