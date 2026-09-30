import {sessionPrepFixture} from '../src/test-fixtures/session-prep';
export type {CitedText,SessionPrep} from '../src/session-prep-api';
export async function readSessionPrep(){
  const value=sessionPrepFixture();
  const item=(text:string)=>({text,source_refs:['a'.repeat(64)]});
  value.prepared_brief={recap:item('Jordan Cypress requested help with appointment access. The medication list was not supplied.'),
    talking_points:[item('Clarify whether Jordan prefers morning calls or calls after 15:00.')],
    suggested_outline:[item('Review contact preference, consent documentation and the medication list.')],
    trajectory_and_material_changes:[],open_threads:[item('Staff action completion is not documented.')],
    cautions:[item('Contact consent is undocumented. Confirm before outreach.')],patient_reported:null};
  return value;
}
