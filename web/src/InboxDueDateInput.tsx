import {useEffect,useId,useState} from 'react';
import {isInboxCalendarDate} from './inbox-contract';
import './InboxDueDateInput.css';

export type InboxDueDateInputProps={label:string;value:string;onChange:(value:string)=>void;disabled?:boolean};

/** Changing the view never changes the saved draft or grants confirmation. */
export function InboxDueDateInput({label,value,onChange,disabled=false}:InboxDueDateInputProps){
  const id=useId(),hintId=id+'-hint',canUseCalendar=value===''||isInboxCalendarDate(value);
  const [preferText,setPreferText]=useState(!canUseCalendar);
  // Derive the view immediately so an external incomplete draft never passes
  // through date-input sanitization. Keep typing after that draft becomes valid.
  const usingText=preferText||!canUseCalendar;
  useEffect(()=>{if(!canUseCalendar)setPreferText(true);},[canUseCalendar]);
  function switchView(){
    if(disabled||usingText&&!canUseCalendar)return;
    setPreferText(!usingText);
  }
  return <div className="inbox-due-date">
    <label htmlFor={id}>{label}
    <input id={id} type={usingText?'text':'date'} value={value} disabled={disabled}
      maxLength={10} min={usingText?undefined:'0001-01-01'} max={usingText?undefined:'9999-12-31'}
      placeholder={usingText?'YYYY-MM-DD':undefined} autoComplete="off" spellCheck={false}
      aria-describedby={usingText?hintId:undefined} aria-invalid={!canUseCalendar||undefined}
      onChange={event=>{if(!disabled)onChange(event.target.value);}}/></label>
    <div className="inbox-due-date__controls">
      <button type="button" aria-controls={id} disabled={disabled||usingText&&!canUseCalendar}
        onClick={switchView}>{usingText?'Use calendar':'Type date'}</button>
      {usingText&&<p id={hintId} className="inbox-due-date__hint">{canUseCalendar?'Enter YYYY-MM-DD.':'Enter a valid calendar date as YYYY-MM-DD, or clear it to use the calendar.'}</p>}
    </div>
  </div>;
}
