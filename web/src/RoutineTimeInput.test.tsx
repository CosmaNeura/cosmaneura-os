import {act,useState} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {RoutineTimeInput} from './RoutineTimeInput';

let host:HTMLDivElement,root:Root,replace:(v:string)=>void,lock:(v:boolean)=>void;
const changed=vi.fn(),submitted=vi.fn();
function Harness({initial}:{initial:string}){
  const [value,setValue]=useState(initial),[disabled,setDisabled]=useState(false);
  replace=setValue;lock=setDisabled;
  return <form onSubmit={event=>{event.preventDefault();submitted();}}>
    <RoutineTimeInput label="Brief time" value={value} disabled={disabled} onChange={v=>{changed(v);setValue(v);}}/>
    <output>{value}</output></form>;
}
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();
  host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});
const field=()=>host.querySelector('input')!;
const toggle=()=>host.querySelector('button')!;
async function render(value:string){await act(async()=>root.render(<Harness initial={value}/>));}
async function click(){await act(async()=>toggle().click());}
async function type(value:string){await act(async()=>{
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(field(),value);
  field().dispatchEvent(new Event('input',{bubbles:true}));
});}

it('switches a valid time between native and text entry without editing or submitting',async()=>{
  await render('09:45');const id=field().id;
  expect(field().type).toBe('time');expect(toggle().getAttribute('aria-label')).toBe('Type brief time');
  await click();expect(field().type).toBe('text');expect(field().value).toBe('09:45');expect(field().id).toBe(id);
  expect(field().maxLength).toBe(5);expect(field().placeholder).toBe('HH:MM');
  expect(host.querySelector('label')!.htmlFor).toBe(id);
  expect(document.getElementById(field().getAttribute('aria-describedby')!)?.textContent).toContain('24-hour');
  await click();expect(field().type).toBe('time');expect(field().value).toBe('09:45');
  expect(changed).not.toHaveBeenCalled();expect(submitted).not.toHaveBeenCalled();
});

it('retains incomplete recovered text until corrected without native sanitization',async()=>{
  await render('09:');expect(field().type).toBe('text');expect(field().value).toBe('09:');
  expect(field().getAttribute('aria-invalid')).toBe('true');expect(toggle().disabled).toBe(true);
  await click();expect(changed).not.toHaveBeenCalled();await type('09:15');
  expect(field().type).toBe('text');expect(toggle().disabled).toBe(false);expect(field().hasAttribute('aria-invalid')).toBe(false);
  expect(changed).toHaveBeenCalledExactlyOnceWith('09:15');await click();expect(field().type).toBe('time');
  expect(field().value).toBe('09:15');expect(changed).toHaveBeenCalledTimes(1);
});

it('never pads, trims, rolls over, or invents a typed time',async()=>{
  await render('');await click();
  for(const value of ['9:30','24:00','12:60',' 9:30']){
    await type(value);expect(field().value).toBe(value);expect(changed).toHaveBeenLastCalledWith(value);
    expect(toggle().disabled).toBe(true);
  }
  await type('');expect(field().value).toBe('');expect(toggle().disabled).toBe(false);
  await click();expect(field().type).toBe('time');expect(field().value).toBe('');expect(submitted).not.toHaveBeenCalled();
});

it('preserves later incomplete props and continues typing after a valid replacement',async()=>{
  await render('23:59');await act(async()=>replace('1:'));expect(field().type).toBe('text');expect(field().value).toBe('1:');
  await act(async()=>replace('00:00'));expect(field().type).toBe('text');expect(field().value).toBe('00:00');
  await click();expect(field().type).toBe('time');expect(field().value).toBe('00:00');expect(changed).not.toHaveBeenCalled();
});

it('passes native edits once and disables both entry modes during locked work',async()=>{
  await render('08:00');await type('10:20');expect(changed).toHaveBeenCalledExactlyOnceWith('10:20');
  await act(async()=>lock(true));expect(field().disabled).toBe(true);expect(toggle().disabled).toBe(true);
  await click();expect(field().type).toBe('time');await act(async()=>lock(false));await click();
  await act(async()=>lock(true));await click();expect(field().type).toBe('text');expect(field().disabled).toBe(true);
  expect(changed).toHaveBeenCalledTimes(1);expect(submitted).not.toHaveBeenCalled();
});
