import {expect,it,vi} from 'vitest';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {ElationLabRecords,labCandidateLabel} from './ElationLabRecords';
import {elationLabFixture} from '../ux-acceptance/elation-lab-fixtures';
import {labDocumentDate} from './elation-lab-date';
import {ehrContentHash,ehrSourceContent,validEhrReceipt} from './ehr-read-api';
import {ehrWindowReceipt,ehrVerifiedReceipt} from './ehr-read-fixtures.test-support';
import {labPageReceipt,labReportReceipt} from './elation-lab-fixtures.test-support';

it('labels the report document date readably without moving its recorded calendar or offset',()=>{
 const metadata=elationLabFixture().reports[0].metadata_json;
 expect(labCandidateLabel(metadata)).toBe('Review report: Invented corrected panel. Document date: Oct 24, 2026 · 9:00 AM (recorded offset -04:00)');
});

it.each([
 ['2026-01-01T00:05:00+14:00','Jan 1, 2026 · 12:05 AM (recorded offset +14:00)'],
 ['2026-12-31T23:59:00-12:00','Dec 31, 2026 · 11:59 PM (recorded offset -12:00)'],
 ['2000-02-29T12:00:00Z','Feb 29, 2000 · 12:00 PM (UTC)'],
 ['2024-02-29T00:00:00','Feb 29, 2024 · 12:00 AM (time zone not provided)'],
 ['0099-01-01T09:01:00+00:00','Jan 1, 0099 · 9:01 AM (recorded offset +00:00)'],
 ['2026-10-24T09:05:01.120000-04:30','Oct 24, 2026 · 9:05:01.120000 AM (recorded offset -04:30)'],
 ['2026-10-24T09:05:00.000000Z','Oct 24, 2026 · 9:05:00.000000 AM (UTC)'],
 ['2026-10-24T09:05:00-00:00','Oct 24, 2026 · 9:05 AM (recorded offset -00:00)'],
 ['2026-10-24T09:05:00+05:45','Oct 24, 2026 · 9:05 AM (recorded offset +05:45)'],
 ['2026-10-24T09:05:00+23:59','Oct 24, 2026 · 9:05 AM (recorded offset +23:59)'],
] as const)('keeps the recorded calendar, clock precision and offset of %s', (original,display)=>{
 expect(labDocumentDate(original)).toBe(display);
});

it.each([
 [undefined,'Not provided'],[null,'No value recorded'],['','Recorded blank'],
] as const)('distinguishes missing, null and blank document dates (%s)',(value,display)=>{
 expect(labDocumentDate(value)).toBe(display);
});

it.each(['1900-02-29T10:00:00Z','2025-02-29T10:00:00Z','2026-04-31T10:00:00Z','2026-01-01T10:00:00+01:60','2026-01-01T24:00:00Z','2026-01-01T10:00:00Z\n',0,false])('does not normalize invalid or unrecognized recorded date %s',value=>{
 expect(labDocumentDate(value)).toBe('Unrecognized recorded date');
});

it('does not use instant parsing, the device calendar or locale conversion',()=>{
 const OriginalDate=Date;
 const parse=vi.spyOn(Date,'parse').mockImplementation(()=>{throw new Error('An instant parser must not run');});
 const format=vi.spyOn(Intl,'DateTimeFormat').mockImplementation(()=>{throw new Error('A local calendar must not run');});
 vi.stubGlobal('Date',new Proxy(OriginalDate,{construct(){throw new Error('Date construction must not run');}}));
 let display:string;
 try{display=labDocumentDate('2026-01-01T00:05:00+14:00');}
 finally{vi.unstubAllGlobals();parse.mockRestore();format.mockRestore();}
 expect(display).toBe('Jan 1, 2026 · 12:05 AM (recorded offset +14:00)');
});

it('keeps the original metadata, report JSON and saved source commitments unchanged',async()=>{
 const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');vi.stubGlobal('crypto',webcrypto);
 try{
  const visit=await ehrVerifiedReceipt(await ehrWindowReceipt()),page=await labPageReceipt(visit),report=await labReportReceipt(page);
  if(page.observation.kind!=='lab_reports'||report.observation.kind!=='verified_lab_report')throw new Error('Invented lab required');
  const before=structuredClone({page,report}),source=ehrSourceContent(report.observation),digest=await ehrContentHash(source);
  expect(labCandidateLabel(page.observation.items[0].metadata_json)).toContain('Oct 24, 2026 · 9:00 AM (recorded offset -04:00)');
  const html=renderToStaticMarkup(createElement(ElationLabRecords,{observation:report.observation,onExactDetails:()=>{}}));
  expect(html).toContain('2026-10-24T09:00:00-04:00');
  expect({page,report}).toEqual(before);expect(ehrSourceContent(report.observation)).toBe(source);
  expect(await ehrContentHash(source)).toBe(digest);expect(report.observation.item.content_sha256).toBe(digest);
  expect(await validEhrReceipt(page)).toBe(true);expect(await validEhrReceipt(report)).toBe(true);
 }finally{vi.unstubAllGlobals();}
});
