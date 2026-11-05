import './calendar-agenda.css';

type CalendarProvider='google'|'outlook';
type AgendaEvent={id:string;subject:string;starts_at:string;ends_at:string;all_day:boolean;cancelled:boolean};
type EventSpan={start:Date;end:Date};
const localDay=(date:Date)=>`${date.getFullYear().toString().padStart(4,'0')}-${(date.getMonth()+1).toString().padStart(2,'0')}-${date.getDate().toString().padStart(2,'0')}`;

function recordedDay(value:string):Date|null {
 if(typeof value!=='string'||!/^\d{4}-\d\d-\d\d$/.test(value))return null;
 const [year,month,day]=value.split('-').map(Number),date=new Date(0);
 date.setFullYear(year,month-1,day);date.setHours(0,0,0,0);
 return date.getFullYear()===year&&date.getMonth()===month-1&&date.getDate()===day?date:null;
}
function instant(value:string):Date|null {
 if(typeof value!=='string'||!/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)$/.test(value)||!recordedDay(value.slice(0,10)))return null;
 const [hour,minute,second]=value.slice(11,19).split(':').map(Number);
 if(hour>23||minute>59||second>59)return null;
 const date=new Date(value);return Number.isFinite(date.getTime())?date:null;
}
function eventSpan(event:AgendaEvent,provider:CalendarProvider):EventSpan|null {
 // Outlook's UTC all-day timestamps do not establish the original calendar day.
 if(event.all_day&&provider==='outlook')return null;
 const start=event.all_day?recordedDay(event.starts_at):instant(event.starts_at),end=event.all_day?recordedDay(event.ends_at):instant(event.ends_at);
 return start&&end&&end.getTime()>start.getTime()?{start,end}:null;
}
export const calendarAgendaHasDates=(event:AgendaEvent,provider:CalendarProvider)=>eventSpan(event,provider)!==null;
const fullDay=(date:Date)=>date.toLocaleDateString(undefined,{weekday:'long',year:'numeric',month:'long',day:'numeric'});
const calendarDate=(date:Date)=>date.toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric'});
const dateTime=(date:Date)=>date.toLocaleString(undefined,{year:'numeric',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'shortOffset'});
const clockTime=(date:Date)=>date.toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit',timeZoneName:'shortOffset'});

export function calendarAgendaWhen(event:AgendaEvent,provider:CalendarProvider,compact=false):string {
 if(event.all_day&&provider==='outlook')return 'All day · Check the day in Outlook Calendar';
 const span=eventSpan(event,provider);
 if(!span)return 'Date or time unavailable · Review the exact calendar source';
 if(event.all_day){
  const lastDay=new Date(span.end);lastDay.setDate(lastDay.getDate()-1);
  return `All day · ${calendarDate(span.start)}${localDay(span.start)===localDay(lastDay)?'':` – ${calendarDate(lastDay)}`}`;
 }
 const format=compact&&localDay(span.start)===localDay(span.end)?clockTime:dateTime;
 return `${format(span.start)} – ${format(span.end)}`;
}

/** Explicit navigation only. Tied times retain the loaded source order. */
export function nextCalendarAgendaEvent<T extends AgendaEvent>(events:T[],selectedId:string|null,clock:number,provider:CalendarProvider):T|null {
 if(!Number.isFinite(clock))return null;
 const eligible=events.map((event,index)=>({event,index,span:eventSpan(event,provider)}))
  .filter(item=>!item.event.cancelled&&item.span!==null&&item.span.end.getTime()>clock)
  .sort((a,b)=>a.span!.start.getTime()-b.span!.start.getTime()||a.index-b.index);
 const selected=eligible.findIndex(item=>item.event.id===selectedId);
 return eligible[selected+1]?.event??null;
}

export function CalendarAgenda<T extends AgendaEvent>({events,provider,startsOn,selectedId,disabled,onChoose}:{events:T[];provider:CalendarProvider;startsOn:string;selectedId:string|null;disabled:boolean;onChoose:(id:string)=>void}) {
 const groups=new Map<string,{label:string;note?:string;items:Array<{event:T;index:number;start:number}>}>();
 events.forEach((event,index)=>{
  const span=eventSpan(event,provider),unknownAllDay=event.all_day&&provider==='outlook';
  // A continuing event belongs to the first displayed day; its full range stays visible.
  const day=span?localDay(span.start):null,key=day?(recordedDay(startsOn)&&day<startsOn?startsOn:day):unknownAllDay?'outlook-all-day':'date-unavailable';
  if(!groups.has(key))groups.set(key,{label:day?fullDay(recordedDay(key)!):unknownAllDay?'All-day events · Full loaded summary':'Date or time unavailable',
   ...(unknownAllDay?{note:'Their original calendar dates are unavailable. Check their day in Outlook Calendar.'}:!day?{note:'Check the exact calendar source before relying on these dates.'}:{}),items:[]});
  groups.get(key)!.items.push({event,index,start:span?.start.getTime()??0});
 });
 return <div className="calendar-agenda">
  {[...groups.entries()].sort(([a],[b])=>a.localeCompare(b)).map(([key,group])=><section className="calendar-agenda-day" key={key} aria-label={group.label}>
   <h5>{group.label}</h5>{group.note&&<p>{group.note}</p>}
   <ul>{group.items.sort((a,b)=>a.start-b.start||a.index-b.index).map(({event})=><li key={event.id}>
    <button type="button" data-calendar-event={event.id} disabled={disabled} aria-pressed={event.id===selectedId} onClick={()=>onChoose(event.id)}>
     <strong>{event.subject||'(Untitled event)'}</strong><span>{calendarAgendaWhen(event,provider,true)}</span>{event.cancelled&&<small>Cancelled event</small>}
    </button>
   </li>)}</ul>
  </section>)}
 </div>;
}
