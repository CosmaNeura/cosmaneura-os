import {useId} from 'react';

type Header={id:string;subject:string;sender:string;is_read:boolean};

export function filterLoadedEmail<T extends Header>(items:T[],query:string,unreadOnly:boolean):T[]{
  const words=query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return items.filter(item=>(!unreadOnly||!item.is_read)&&words.every(word=>
    `${item.subject}\n${item.sender}`.toLocaleLowerCase().includes(word)));
}

export function EmailInboxFilter({query,onQueryChange,unreadOnly,onUnreadChange,shown,total,selectedOutside,disabled}:{
  query:string;onQueryChange:(value:string)=>void;unreadOnly:boolean;onUnreadChange:(value:boolean)=>void;
  shown:number;total:number;selectedOutside:boolean;disabled:boolean;
}){
  const id=useId(),filtered=!!query.trim()||unreadOnly;
  return <div className="email-inbox-filter">
    <label htmlFor={id}>Find an email</label>
    <input id={id} type="search" value={query} maxLength={200} autoComplete="off"
      placeholder="Sender or subject" disabled={disabled} onChange={event=>onQueryChange(event.target.value)}/>
    <div className="email-inbox-filter-options">
      <label><input type="checkbox" checked={unreadOnly} disabled={disabled}
        onChange={event=>onUnreadChange(event.target.checked)}/>Unread only</label>
      {filtered&&<button type="button" disabled={disabled}
        onClick={()=>{onQueryChange('');onUnreadChange(false);}}>Clear filters</button>}
    </div>
    <p role="status">{filtered?`${shown} of ${total} loaded emails match.`:`Search these ${total} loaded emails.`}
      {selectedOutside?' Your selected email stays below.':''}</p>
    {filtered&&shown===0&&total>0&&<p>No matches in the loaded emails. Try another sender or subject, or clear the filters.</p>}
  </div>;
}
