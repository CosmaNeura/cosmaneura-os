import {useEffect,useId,useState} from 'react';
import {isRoutineClockTime} from './routine-api';
import './RoutineTimeInput.css';

/** View changes neither edit the draft nor schedule work. */
export function RoutineTimeInput({label,value,onChange,disabled=false}: {
  label:string;value:string;onChange:(value:string)=>void;disabled?:boolean;
}) {
  const id=useId(),hintId=id+'-hint',canUsePicker=value===''||isRoutineClockTime(value);
  const [preferText,setPreferText]=useState(!canUsePicker);
  // Incomplete recovered text must never pass through native time sanitization.
  const usingText=preferText||!canUsePicker;
  useEffect(()=>{if(!canUsePicker)setPreferText(true);},[canUsePicker]);
  return <div className="routine-time">
    <label htmlFor={id}>{label}<input id={id} type={usingText?'text':'time'} value={value}
      disabled={disabled} maxLength={5} placeholder={usingText?'HH:MM':undefined}
      autoComplete="off" spellCheck={false} aria-describedby={usingText?hintId:undefined}
      aria-invalid={!canUsePicker||undefined}
      onChange={event=>{if(!disabled)onChange(event.target.value);}}/></label>
    <div className="routine-time__controls">
      <button type="button" aria-controls={id} aria-label={`${usingText?'Use time picker for':'Type'} ${label.toLowerCase()}`}
        disabled={disabled||usingText&&!canUsePicker}
        onClick={()=>{if(!disabled&&(!usingText||canUsePicker))setPreferText(!usingText);}}>
        {usingText?'Use time picker':'Type time'}</button>
      {usingText&&<p id={hintId}>{canUsePicker?'Enter HH:MM in 24-hour time.':'Enter a valid 24-hour time as HH:MM, or clear it to use the picker.'}</p>}
    </div>
  </div>;
}
