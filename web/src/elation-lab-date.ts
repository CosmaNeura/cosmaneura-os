import {labTimestamp} from './elation-lab-contract';

const months=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

/** Presentation only: use the validated recorded calendar and clock components.
 * Never parse an instant or substitute the device/practice time zone. Original
 * timestamp strings, report JSON, saved source text and commitments stay intact. */
export function labDocumentDate(value:unknown):string {
 if(value===undefined)return 'Not provided';
 if(value===null)return 'No value recorded';
 if(value==='')return 'Recorded blank';
 if(!labTimestamp(value))return 'Unrecognized recorded date';
 const match=/^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(\.\d{1,6})?(Z|[+-]\d\d:\d\d)?$/.exec(value)!;
 const [,year,month,day,hour,minute,second,fraction,offset]=match;
 const h=Number(hour),seconds=second==='00'&&!fraction?'':':'+second+(fraction??'');
 const clock=`${h%12||12}:${minute}${seconds} ${h<12?'AM':'PM'}`;
 const zone=offset===undefined?'time zone not provided':offset==='Z'?'UTC':'recorded offset '+offset;
 return `${months[Number(month)-1]} ${Number(day)}, ${year} · ${clock} (${zone})`;
}
