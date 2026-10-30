import {useState} from 'react';
import './provider-connection-portal.css';

type RecordsSystem = 'atlas_md' | 'elation' | 'tebra' | 'athena';
const systems: {
  id: RecordsSystem;
  name: string;
  reads: string;
  access: string;
  relay: string;
  openLabel: string;
}[] = [
  {id:'atlas_md', name:'Atlas.MD', reads:'Appointments from an exported calendar file.', access:'File import only · no live chart sync', relay:'No verified Atlas.MD prescription connection. Rx Relay cannot send or sign from this app.', openLabel:'Import Atlas.MD calendar file'},
  {id:'elation', name:'Elation', reads:'Appointments, problems, medication records, and lab reports.', access:'Read only · approved practice access is checked when opened', relay:'Prescription sending is not available. A later relay would be an unsigned draft a clinician reviews in Elation, not a signed or transmitted prescription.', openLabel:'Open Elation records'},
  {id:'tebra', name:'Tebra', reads:'Appointments and medication records.', access:'Read only · approved practice access is checked when opened', relay:'Medication records can be reviewed here. Prescription sending is not available.', openLabel:'Open Tebra records'},
  {id:'athena', name:'Athena', reads:'Allergy and medication records.', access:'Read only · practice access is checked when opened', relay:'Allergy and medication records can be reviewed here. Prescription sending is not available.', openLabel:'Open Athena records'},
];

/** Provider setup for read-only EHR access and an honest Rx Relay status. Opening records never sends a prescription. */
export function ProviderConnectionPortal({locked, records}:{locked:boolean; records?:Partial<Record<RecordsSystem,()=>void>>}) {
  const [selected, setSelected] = useState<RecordsSystem>('elation');
  const system = systems.find(item => item.id === selected) ?? systems[1];
  const open = records?.[system.id];
  return <section className="provider-portal" aria-label="EHR and Rx Relay">
    <p className="provider-portal-lead">Connect the records system your practice uses. Chart access here is read only. Rx Relay does not sign or send a prescription.</p>
    <div className="provider-portal-systems" role="group" aria-label="Records system">
      {systems.map(item => <button key={item.id} type="button" aria-pressed={selected===item.id} disabled={locked} onClick={() => setSelected(item.id)}>
        <strong>{item.name}</strong><small>Read only</small>
      </button>)}
    </div>
    <article className="provider-portal-detail" aria-live="polite">
      <p className="provider-portal-badge">Read only</p>
      <h2>{system.name}</h2>
      <p>{system.reads}</p>
      <p className="provider-portal-access">{system.access}</p>
      <section className="provider-portal-relay" aria-label="Rx Relay">
        <h3>Rx Relay</h3>
        <p role="status"><strong>Not connected for sending.</strong> {system.relay}</p>
      </section>
      <button className="team-primary" type="button" disabled={locked || !open} onClick={() => open?.()}>{open ? system.openLabel : 'Not available in this app'}</button>
      {!open && <p className="provider-portal-access">Ask your practice administrator to make {system.name} available in this app before opening records.</p>}
    </article>
    <section className="provider-portal-limits" aria-label="Before a prescription can be sent">
      <h2>Before a prescription can leave this app</h2>
      <ol>
        <li>Your practice administrator approves the EHR connection.</li>
        <li>You review the exact record in CosmaBot.</li>
        <li>A licensed clinician confirms the prescription in the EHR.</li>
        <li>This beta does not sign or transmit a prescription.</li>
      </ol>
    </section>
  </section>;
}
