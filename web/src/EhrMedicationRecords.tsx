import type {EhrMedicationList,EhrRecordedDateState} from './ehr-read-api';

const dateValue=(value:string|null,state:EhrRecordedDateState)=>state==='date_recorded'?value:state==='no_date_recorded'?'No date recorded':'Unknown';
const recordedValue=(value:string|boolean)=>typeof value==='boolean'?value?'Yes':'No':value===''?'(blank)':value;

export function EhrMedicationRecords({medications}:{medications:EhrMedicationList}){
 return <section aria-label="Review medication records">
  <h4>Medication records for this patient</h4>
  <p>The appointment and patient were checked again for this read. Records may include unfinished orders and history. Review the directions, recorded dates and limits below.</p>
  <p>{medications.coverage==='more_rows_available'?'This page is incomplete. More medication records are available; only the rows shown here will be saved.':medications.coverage==='unknown'?'Completeness is unknown. Other medication records may be missing; only the rows shown here will be saved.':'The end of the returned results was reported. This snapshot is not the full chart.'}</p>
  <p className="team-fine">Returned rows: {medications.items.length}.{medications.total_count!==null?' Reported total: '+medications.total_count+'.':''} Appointment-list coverage and medication-record coverage are separate.</p>
  <p className="team-fine">Optional details not listed were not provided. Dates and types are shown as recorded in Elation, without an assumed timezone or current medication status.</p>
  {medications.items.length?<ul aria-label="Returned medication records">{medications.items.map((row,index)=><li key={index}>
   <strong>{row.medication_name}</strong>
   <dl>{([
    ['Strength',row.strength],['Route',row.route],['Form',row.form],['Directions',row.directions],
    ['Medication type in Elation',row.medication_type],['Order type in Elation',row.order_type],
    ['Documented medication in Elation',row.is_doc_med],['Marked permanent in Elation',row.is_permanent],
    ['Start date',row.start_date],['Document date',row.document_date],
    ['Signed date',dateValue(row.signed_date,row.signature_state)],
    ['Discontinuation date',dateValue(row.discontinue_date,row.discontinuation_state)],
    ['Deleted date',dateValue(row.deleted_date,row.deletion_state)],
   ] as [string,string|boolean|null][]).filter(([,value])=>value!==null).map(([label,value])=><div key={label}><dt>{label}</dt><dd>{recordedValue(value!)}</dd></div>)}</dl>
  </li>)}</ul>:<p>No medication rows were returned. This does not establish that the patient takes no medications.</p>}
  <p>These are medication records, not a reconciled current medication list or proof of dispensing, transmission or use. Dispensing history is not included.</p>
  <p className="team-fine">Only the displayed snapshot is saved. It does not prescribe or update the EHR.</p>
 </section>;
}
