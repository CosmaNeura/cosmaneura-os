import {expect,it} from 'vitest';
import {CLIPBOARD_CLEAR_TEXT,validateCopyToEhrAuditMetadata,validateCopyToEhrPackage} from './copy-to-ehr-api';
import {taylorMorganPackage} from './copy-to-ehr-fixtures.test-support';

it('accepts a closed package with plain labeled sections and separate extras',()=>{
  const pkg=validateCopyToEhrPackage(taylorMorganPackage());
  expect(pkg.sections.map(section=>section.key)).toEqual(['subjective','objective','assessment','plan']);
  expect(pkg.full_note).toContain('Subjective\nTaylor Morgan reports');
  expect(pkg.full_note).not.toMatch(/^#/m);
  expect(pkg.extras.map(extra=>extra.key)).toEqual(['patient_instructions','orders']);
  expect(pkg.visit_copy_to_ehr_status).toBe('unset');
  expect(CLIPBOARD_CLEAR_TEXT).toBe(' ');
});

it('rejects a leading hash in section text or the full note',()=>{
  expect(()=>validateCopyToEhrPackage(taylorMorganPackage({
    sections:[{key:'subjective',label:'Subjective',text:'#AI macro would open'}],
    section_notes:{subjective:'Subjective\nplain'},
    full_note:'Subjective\nplain',
  }))).toThrow();
  expect(()=>validateCopyToEhrPackage(taylorMorganPackage({
    full_note:'# Assessment\nInvented viral pharyngitis.',
  }))).toThrow();
});

it('keeps audit metadata content-free',()=>{
  const meta=validateCopyToEhrAuditMetadata({
    event:'copy_to_ehr.copied',
    profile_id:'atlas_md',
    outcome:'ok',
    duration_ms:120,
    correlation_id:'11111111-1111-4111-8111-111111111111',
  });
  expect(meta.event).toBe('copy_to_ehr.copied');
  expect(JSON.stringify(meta)).not.toContain('Taylor');
  expect(JSON.stringify(meta)).not.toContain('sore throat');
});
