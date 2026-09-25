import {act,useState} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {InboxDueDateInput} from './InboxDueDateInput';
import {isInboxCalendarDate} from './inbox-contract';

it.each(['0001-01-01','0004-02-29','0400-02-29','1600-02-29','2000-02-29','2024-02-29',
  '1900-02-28','2100-02-28','2026-04-30','9999-12-31'])('accepts exact supported Gregorian day %s',value=>{
  expect(isInboxCalendarDate(value)).toBe(true);
});
it.each(['','0000-01-01','10000-01-01','-001-01-01','+2026-01-01','1900-02-29','2100-02-29',
  '2026-02-29','2024-02-30','2026-04-31','2026-00-01','2026-13-01','2026-01-00','2026-01-32',
  '2026-1-01','2026-01-1','2026-09-','2026-09','2026-09-01 ',' 2026-09-01','2026/09/01',
  '2026-09-01T00:00:00Z',null,undefined,20260901])('rejects noncanonical or impossible day %s without coercion',value=>{
  expect(isInboxCalendarDate(value)).toBe(false);
});

let host:HTMLDivElement,root:Root,update:(value:string)=>void,lock:(value:boolean)=>void;
const changed=vi.fn(),submitted=vi.fn();
function Harness({initial}:{initial:string}){
  const [value,setValue]=useState(initial),[disabled,setDisabled]=useState(false),[confirmed,setConfirmed]=useState(true);
  update=setValue;lock=setDisabled;
  return <form onSubmit={event=>{event.preventDefault();submitted();}}>
    <InboxDueDateInput label="Due date" value={value} disabled={disabled} onChange={next=>{changed(next);setValue(next);}}/>
    <label><input type="checkbox" checked={confirmed} onChange={event=>setConfirmed(event.target.checked)}/>Existing confirmation</label>
    <output>{value}</output>
  </form>;
}
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();
  host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});
const field=()=>{const input=host.querySelector<HTMLLabelElement>('.inbox-due-date > label')?.control;if(!(input instanceof HTMLInputElement))throw Error('Missing associated date input');return input;};
const button=()=>host.querySelector<HTMLButtonElement>('.inbox-due-date button')!;
async function render(value:string){await act(async()=>root.render(<Harness initial={value}/>));}
async function click(){await act(async()=>button().click());}
async function type(value:string){await act(async()=>{
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(field(),value);
  field().dispatchEvent(new Event('input',{bubbles:true}));
});}

it.each(['','2026-09-30','0001-01-01','9999-12-31'])('retains native date entry by default for %s',async value=>{
  await render(value);expect(field().type).toBe('date');expect(field().value).toBe(value);
  expect(field().min).toBe('0001-01-01');expect(field().max).toBe('9999-12-31');
  expect(host.querySelector<HTMLLabelElement>('.inbox-due-date > label')!.htmlFor).toBe(field().id);
  expect(button().textContent).toBe('Type date');expect(changed).not.toHaveBeenCalled();
});

it('switches only the view and retains raw date text and existing confirmations',async()=>{
  await render('2024-02-29');const id=field().id;
  await click();expect(field().type).toBe('text');expect(field().value).toBe('2024-02-29');
  expect(field().id).toBe(id);expect(field().maxLength).toBe(10);expect(field().placeholder).toBe('YYYY-MM-DD');
  expect(host.textContent).toContain('Enter YYYY-MM-DD.');
  expect(field().getAttribute('aria-describedby')).toBe(host.querySelector('.inbox-due-date__hint')!.id);
  expect(button().textContent).toBe('Use calendar');await click();expect(field().type).toBe('date');
  expect(field().value).toBe('2024-02-29');expect(changed).not.toHaveBeenCalled();expect(submitted).not.toHaveBeenCalled();
  expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(true);
});

it.each(['2026-09-','2026-02-30','0000-01-01','2026-9-01',' 2026-09-'])('shows incomplete or invalid restored text exactly: %s',async value=>{
  await render(value);expect(field().type).toBe('text');expect(field().value).toBe(value);
  expect(host.querySelector('output')!.value).toBe(value);expect(field().getAttribute('aria-invalid')).toBe('true');
  expect(button().textContent).toBe('Use calendar');expect(button().disabled).toBe(true);
  expect(host.textContent).toContain('Enter a valid calendar date as YYYY-MM-DD, or clear it to use the calendar.');
  await click();expect(field().value).toBe(value);expect(changed).not.toHaveBeenCalled();
});

it('keeps typing mode as an incomplete date becomes valid and returns to calendar only explicitly',async()=>{
  await render('2024-02-');await type('2024-02-29');expect(changed).toHaveBeenCalledExactlyOnceWith('2024-02-29');
  expect(field().type).toBe('text');expect(field().value).toBe('2024-02-29');expect(button().disabled).toBe(false);
  expect(field().hasAttribute('aria-invalid')).toBe(false);await click();expect(field().type).toBe('date');
  expect(changed).toHaveBeenCalledTimes(1);
});

it('allows an incomplete date to be cleared without restoring or inventing a date',async()=>{
  await render('2026-09-');await type('');expect(field().type).toBe('text');expect(field().value).toBe('');
  expect(button().disabled).toBe(false);await click();expect(field().type).toBe('date');expect(field().value).toBe('');
  expect(changed).toHaveBeenCalledExactlyOnceWith('');
});

it('preserves later invalid draft props and stays in text mode after a valid replacement',async()=>{
  await render('2026-09-30');await act(async()=>update('2026-09-'));
  expect(field().type).toBe('text');expect(field().value).toBe('2026-09-');expect(changed).not.toHaveBeenCalled();
  await act(async()=>update('2026-10-01'));expect(field().type).toBe('text');expect(field().value).toBe('2026-10-01');
  await click();expect(field().type).toBe('date');expect(changed).not.toHaveBeenCalled();
});

it('passes typed input exactly without trimming, date rollover or padding',async()=>{
  await render('');await click();await type('2026-02-30');expect(field().value).toBe('2026-02-30');
  expect(changed).toHaveBeenLastCalledWith('2026-02-30');expect(button().disabled).toBe(true);
  await type(' 2026-2-');expect(field().value).toBe(' 2026-2-');expect(changed).toHaveBeenLastCalledWith(' 2026-2-');
  expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(true);
});

it('passes a native date change once without submitting or changing mode',async()=>{
  await render('2026-09-30');await type('2026-10-01');expect(field().type).toBe('date');
  expect(changed).toHaveBeenCalledExactlyOnceWith('2026-10-01');expect(submitted).not.toHaveBeenCalled();
});

it('respects disabled fields and toggles in both modes',async()=>{
  await render('2026-09-30');await act(async()=>lock(true));expect(field().disabled).toBe(true);expect(button().disabled).toBe(true);
  await click();expect(field().type).toBe('date');expect(changed).not.toHaveBeenCalled();
  await act(async()=>lock(false));await click();await act(async()=>lock(true));await click();
  expect(field().type).toBe('text');expect(field().disabled).toBe(true);expect(button().disabled).toBe(true);
  expect(field().value).toBe('2026-09-30');expect(changed).not.toHaveBeenCalled();
});
