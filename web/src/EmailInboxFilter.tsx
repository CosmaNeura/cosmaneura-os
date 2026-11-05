import {useId} from 'react';
import './email-inbox-filter.css';

type Header={id:string;subject:string;sender:string;is_read:boolean};

export function filterLoadedEmail<T extends Header>(items:T[],query:string,unreadOnly:boolean):T[]{
  const words=query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return items.filter(item=>(!unreadOnly||!item.is_read)&&words.every(word=>
    `${item.subject}\n${item.sender}`.toLocaleLowerCase().includes(word)));
}

/** Keep the loaded-list order, including when the current email is outside filters. */
export function nextLoadedUnreadEmail<T extends Header>(items:T[],filtered:T[],selectedId:string|null):T|undefined{
  const selectedIndex=selectedId===null?-1:items.findIndex(item=>item.id===selectedId);
  if(selectedId!==null&&selectedIndex===-1)return;
  const matchingIds=new Set(filtered.map(item=>item.id));
  return items.find((item,index)=>index>selectedIndex&&!item.is_read&&matchingIds.has(item.id));
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
      <div className="email-inbox-read-filter" role="group" aria-label="Read status in loaded emails">
        <button type="button" disabled={disabled} aria-pressed={!unreadOnly}
          onClick={()=>onUnreadChange(false)}>All loaded emails</button>
        <button type="button" disabled={disabled} aria-pressed={unreadOnly}
          onClick={()=>onUnreadChange(true)}>Unread only</button>
      </div>
      {filtered&&<button type="button" disabled={disabled}
        onClick={()=>{onQueryChange('');onUnreadChange(false);}}>Clear filters</button>}
    </div>
    <p role="status">{filtered?`${shown} of ${total} loaded emails match.`:`Search these ${total} loaded emails.`}
      {selectedOutside?' Your selected email stays below.':''}</p>
    {filtered&&shown===0&&total>0&&<p>{unreadOnly
      ?query.trim()?'No unread matches. Choose All loaded emails to include read emails and keep this search, or try another sender or subject.':'No unread emails in this loaded list. Choose All loaded emails to include read emails.'
      :'No matches in the loaded emails. Try another sender or subject, or clear the filters.'}</p>}
  </div>;
}
