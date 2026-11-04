import {useEffect,useState,type Dispatch,type SetStateAction} from 'react';

export type CalendarFocus='today'|'next7';
type CalendarFocusWindow={starts_at:number;ends_at:number;starts_on:string;ends_on:string};
type CalendarFocusEvent={starts_at:string;ends_at:string;all_day:boolean};

const localDate=(date:Date)=>`${date.getFullYear().toString().padStart(4,'0')}-${(date.getMonth()+1).toString().padStart(2,'0')}-${date.getDate().toString().padStart(2,'0')}`;
export const calendarFocusLabel=(focus:CalendarFocus)=>focus==='today'?'Today':'Next 7 days';

function focusWindow(clock:number,focus:CalendarFocus):CalendarFocusWindow {
 const start=new Date(clock);start.setHours(0,0,0,0);
 const end=new Date(start);end.setDate(end.getDate()+(focus==='today'?1:7));
 return {starts_at:start.getTime(),ends_at:end.getTime(),starts_on:localDate(start),ends_on:localDate(end)};
}

// All-day events passed here must carry recorded YYYY-MM-DD dates, as Google
// does. Outlook's all-day timestamps cannot establish their calendar dates;
// those events are displayed separately without guessing focus membership.
export function calendarEventInFocus(event:CalendarFocusEvent,window:CalendarFocusWindow):boolean {
 if(event.all_day)return /^\d{4}-\d\d-\d\d$/.test(event.starts_at)&&/^\d{4}-\d\d-\d\d$/.test(event.ends_at)&&event.starts_at<window.ends_on&&event.ends_at>window.starts_on;
 return Date.parse(event.starts_at)<window.ends_at&&Date.parse(event.ends_at)>window.starts_at;
}

export function useCalendarWorkFocus(clock:number,setClock:Dispatch<SetStateAction<number>>) {
 const [focus,setFocus]=useState<CalendarFocus>('today');
 // Advance the display at local midnight, including daylight-saving changes.
 // This only updates local UI state; the saved event and review are untouched.
 useEffect(()=>{
  const midnight=new Date(clock);midnight.setHours(24,0,0,0);
  const timer=setTimeout(()=>setClock(Date.now()),Math.max(0,midnight.getTime()-Date.now()));
  return()=>clearTimeout(timer);
 },[clock,setClock]);
 return {focus,setFocus,window:focusWindow(clock,focus)};
}

export function CalendarWorkFocus({focus,onChange,disabled}:{focus:CalendarFocus;onChange:(focus:CalendarFocus)=>void;disabled:boolean}) {
 return <><div className="google-calendar-focus" role="group" aria-label="Calendar focus">
  <button type="button" disabled={disabled} aria-pressed={focus==='today'} onClick={()=>onChange('today')}>Today</button>
  <button type="button" disabled={disabled} aria-pressed={focus==='next7'} onClick={()=>onChange('next7')}>Next 7 days</button>
 </div><p className="google-calendar-focus-note">Your local time · Loaded events only</p></>;
}
