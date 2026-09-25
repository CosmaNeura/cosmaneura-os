import {expect,it} from "vitest";
import {appointmentRequestKey,validAppointmentRequest} from "./appointment-request";
import {id,item} from "./appointment-test-fixture";

const command=()=>({kind:"execute" as const,ticket:id(10),body:{operation_id:id(12),revision_id:id(11),payload_hash:"a".repeat(64),mode:"submit" as const}});
it.each(["submit","reconcile","retry"])("accepts only the exact saved %s command",mode=>{
 const value={...command(),body:{...command().body,mode}};
 expect(validAppointmentRequest(value)).toBe(true);
 if(validAppointmentRequest(value))expect(appointmentRequestKey(value)).toBe(id(12));
});
it.each(["ticket","operation","revision","hash","mode","array","extra","key","slot","approval"])("refuses recovered execute %s substitution",fault=>{
 const value=command();
 if(fault==="ticket")value.ticket="../other";
 if(fault==="operation")value.body.operation_id="";
 if(fault==="revision")value.body.revision_id="unbound";
 if(fault==="hash")value.body.payload_hash="A".repeat(64);
 if(fault==="mode")Object.assign(value.body,{mode:"auto"});
 if(fault==="array")Object.assign(value.body,{mode:["submit"]});
 if(fault==="extra")Object.assign(value,{retry:true});
 if(fault==="key")Object.assign(value.body,{idempotency_key:id(99)});
 if(fault==="slot")Object.assign(value.body,{slot:item().intent.slot});
 if(fault==="approval")Object.assign(value.body,{approved:true});
 expect(validAppointmentRequest(value)).toBe(false);
});
it("retains the old proposal and decision contracts without introducing execution",()=>{
 const prepare={kind:"prepare" as const,body:{bot:{address:"follow_up",team_revision:1},action:"book" as const,slot:item().intent.slot,share:true as const,idempotency_key:id(15)}};
 const decide={kind:"decide" as const,ticket:id(10),body:{revision_id:id(11),payload_hash:"a".repeat(64),choice:"approve" as const}};
 for(const value of [prepare,decide]){const before=JSON.stringify(value);expect(validAppointmentRequest(value)).toBe(true);expect(JSON.stringify(value)).toBe(before);}
 expect(appointmentRequestKey(prepare)).toBe(id(15));expect(appointmentRequestKey(decide)).toBe(id(11));
 expect(validAppointmentRequest({...prepare,body:{...prepare.body,action:["book"]}})).toBe(false);
});
