import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {CopyToEhrStrip} from './CopyToEhrStrip';
import {taylorMorganPackage} from './copy-to-ehr-fixtures.test-support';
import {CLIPBOARD_CLEAR_TEXT} from './copy-to-ehr-api';

let root:Root,host:HTMLDivElement;
const write=vi.fn();
const audit=vi.fn();
const pkg=taylorMorganPackage();

async function render(extra:Partial<Parameters<typeof CopyToEhrStrip>[0]>={}){
  await act(async()=>root.render(<CopyToEhrStrip pkg={pkg} expectedRevision={pkg.draft_revision} onAudit={audit} {...extra}/>));
}
const button=(label:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(item=>item.textContent===label);
async function click(label:string){await act(async()=>button(label)!.click());}

beforeEach(()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
  write.mockReset();write.mockResolvedValue(undefined);audit.mockReset();
  vi.stubGlobal('navigator',{clipboard:{writeText:write}});
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});

it('copies the full labeled note only after an explicit click',async()=>{
  await render();expect(write).not.toHaveBeenCalled();
  await click('Copy full note');
  expect(write).toHaveBeenCalledExactlyOnceWith(pkg.full_note);
  expect(host.querySelector('[role=status]')?.textContent).toContain('Copied');
  expect(audit).toHaveBeenCalledWith(expect.objectContaining({event:'copy_to_ehr.opened'}));
  expect(audit).toHaveBeenCalledWith(expect.objectContaining({event:'copy_to_ehr.copied',outcome:'ok'}));
  expect(JSON.stringify(audit.mock.calls)).not.toContain('Taylor Morgan');
});

it('copies the highlighted section and advances on next highlight',async()=>{
  await render();
  await click('Copy this section');
  expect(write).toHaveBeenCalledExactlyOnceWith(pkg.section_notes.subjective);
  await click('Next highlight');
  await click('Copy this section');
  expect(write).toHaveBeenLastCalledWith(pkg.section_notes.objective);
  expect(host.textContent).toContain('Next section: Objective');
});

it('clears the clipboard with a single space',async()=>{
  await render();
  await click('Clear clipboard');
  expect(write).toHaveBeenCalledExactlyOnceWith(CLIPBOARD_CLEAR_TEXT);
  expect(host.querySelector('[role=status]')?.textContent).toContain('Clipboard cleared');
  expect(audit).toHaveBeenCalledWith(expect.objectContaining({event:'copy_to_ehr.cleared'}));
});

it('locks every copy button when the draft revision is stale',async()=>{
  await render({expectedRevision:'rev-stale'});
  expect(host.querySelector('[role=alert]')?.textContent).toContain('This draft changed');
  for(const label of ['Copy full note','Copy this section','Next highlight','Clear clipboard','Pop out']){
    expect(button(label)?.disabled).toBe(true);
  }
  await click('Copy full note');
  expect(write).not.toHaveBeenCalled();
});

it('copies section_notes text for the active section',async()=>{
  await render();
  await click('Copy this section');
  expect(write).toHaveBeenCalledExactlyOnceWith(pkg.section_notes.subjective);
});

it('shows selectable text when the clipboard is blocked',async()=>{
  write.mockRejectedValue(new DOMException('Denied','NotAllowedError'));
  await render();
  await click('Copy this section');
  expect(host.querySelector('[role=status]')?.textContent).toContain('Clipboard copy is blocked');
  const field=host.querySelector('textarea')!;
  expect(field.readOnly).toBe(true);
  expect(field.value).toBe(pkg.section_notes.subjective);
  await click('Select and copy');
  expect(document.activeElement).toBe(field);
  expect(field.selectionEnd).toBe(pkg.section_notes.subjective.length);
});

it('states clearly that a failed connection did not send the note',async()=>{
  await render({connectionFailed:true});
  expect(host.querySelector('.copy-to-ehr-not-sent')?.textContent).toContain('This note was not sent');
  expect(host.textContent).not.toMatch(/integrat|sync|write-?back/i);
  expect(audit).toHaveBeenCalledWith(expect.objectContaining({event:'copy_to_ehr.fallback_shown'}));
});

it('dismisses on Done without logging note text',async()=>{
  const done=vi.fn();
  await render({onDone:done});
  await click('Done');
  expect(done).toHaveBeenCalledOnce();
  expect(host.querySelector('.copy-to-ehr-strip')).toBeNull();
  expect(audit).toHaveBeenCalledWith(expect.objectContaining({event:'copy_to_ehr.done'}));
  expect(JSON.stringify(audit.mock.calls)).not.toContain('sore throat');
});
