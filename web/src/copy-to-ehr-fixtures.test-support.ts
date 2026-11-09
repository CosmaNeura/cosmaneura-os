import type {CopyToEhrPackage} from './copy-to-ehr-api';

/** Invented sore-throat package. Taylor Morgan is not a real patient. */
export function taylorMorganPackage(overrides:Partial<CopyToEhrPackage>={}):CopyToEhrPackage{
  const sections=[
    {key:'subjective',label:'Subjective',text:'Taylor Morgan reports an invented sore throat for two days. No fever tonight.'},
    {key:'objective',label:'Objective',text:'Oropharynx mildly erythematous. No exudate on this invented exam.'},
    {key:'assessment',label:'Assessment',text:'Invented viral pharyngitis.'},
    {key:'plan',label:'Plan',text:'Fluids, rest, and a follow-up if swallowing worsens. Clinician to review before saving.'},
  ];
  const full_note=sections.map(section=>`${section.label}\n${section.text}`).join('\n\n');
  return {
    profile_id:'atlas_md',
    draft_id:'visit_note_00000000000000000000000001',
    draft_revision:3,
    payload_hash:'a'.repeat(64),
    sections,
    extras:{
      patient_instructions:'Gargle warm salt water. Return if invented symptoms worsen.',
      orders:'Rapid strep if symptoms persist beyond three invented days.',
    },
    created_at:'2026-11-09T18:00:00Z',
    expires_at:'2099-01-01T00:00:00Z',
    review_state:'reviewed',
    full_note,
    ...overrides,
  };
}
