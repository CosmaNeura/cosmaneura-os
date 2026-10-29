/** Numeric clinical values remain their original JSON lexemes. The private
 * symbol distinguishes them from arbitrary recorded objects, including objects
 * whose own fields happen to be named kind, raw, token or __proto__. */
const numeric=Symbol('Athena recorded numeric token');
export type AthenaMedicationNumber={readonly [numeric]:true;readonly raw:string};
export type AthenaMedicationJson=null|boolean|string|AthenaMedicationNumber|AthenaMedicationJson[]|{[key:string]:AthenaMedicationJson};
export const isAthenaMedicationNumber=(value:unknown):value is AthenaMedicationNumber=>!!value&&typeof value==='object'&&Object.hasOwn(value,numeric)&&(value as AthenaMedicationNumber)[numeric]===true;
const numberToken=(raw:string):AthenaMedicationNumber=>Object.freeze({[numeric]:true as const,raw});
const fail=():never=>{throw new Error('The original Athena medication details could not be verified.');};
const validString=(value:string,max:number)=>Array.from(value).length<=max&&!/[\u0000\ud800-\udfff]/u.test(value);
const quote=(value:string)=>JSON.stringify(value).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'));
/** Python's scalar ordering differs from JavaScript UTF-16 ordering for astral keys. */
export const athenaMedicationKeyOrder=(a:string,b:string)=>{
 const left=Array.from(a),right=Array.from(b);for(let i=0;i<Math.min(left.length,right.length);i++){const difference=left[i].codePointAt(0)!-right[i].codePointAt(0)!;if(difference)return difference;}return left.length-right.length;
};
export function parseAthenaMedicationJson(raw:unknown):{value:AthenaMedicationJson;canonical:string}{
 if(typeof raw!=='string'||new TextEncoder().encode(raw).length>65536)return fail();
 let at=0,nodes=0;
 const whitespace=()=>{while(/[\t\n\r ]/.test(raw[at]??'!'))at++;};
 const string=()=>{
  if(raw[at++]!=='"')return fail();let result='';
  while(at<raw.length){const ch=raw[at++];
   if(ch==='"'){if(!validString(result,4096))return fail();return result;}
   if(ch==='\\'){
    const escape=raw[at++],simple:Record<string,string>={'"':'"','\\':'\\','/':'/','b':'\b','f':'\f','n':'\n','r':'\r','t':'\t'};
    if(Object.hasOwn(simple,escape)){result+=simple[escape];continue;}
    if(escape!=='u')return fail();const hex=raw.slice(at,at+4);if(!/^[\da-fA-F]{4}$/.test(hex))return fail();
    // This converts only a Unicode escape, never a clinical number token.
    let unit=0;for(const digit of hex.toLowerCase())unit=unit*16+'0123456789abcdef'.indexOf(digit);result+=String.fromCharCode(unit);at+=4;
   }else{if(ch.charCodeAt(0)<32)return fail();result+=ch;}
  }
  return fail();
 };
 const value=(depth:number):{value:AthenaMedicationJson;canonical:string}=>{
  if(++nodes>4096||depth>16)return fail();whitespace();const ch=raw[at];
  if(ch==='"'){const text=string();return {value:text,canonical:quote(text)};}
  if(ch==='{'){
   at++;whitespace();const object:{[key:string]:AthenaMedicationJson}=Object.create(null),fields=new Map<string,string>();
   if(raw[at]!=='}')for(;;){
    if(fields.size>=64||raw[at]!=='"')return fail();const key=string();if(!validString(key,128)||Object.hasOwn(object,key))return fail();whitespace();if(raw[at++]!==':')return fail();
    const child=value(depth+1);object[key]=child.value;fields.set(key,child.canonical);whitespace();if(raw[at]==='}')break;if(raw[at++]!==',')return fail();whitespace();
   }
   at++;return {value:object,canonical:'{'+[...fields.keys()].sort(athenaMedicationKeyOrder).map(key=>quote(key)+':'+fields.get(key)).join(',')+'}'};
  }
  if(ch==='['){
   at++;whitespace();const items:AthenaMedicationJson[]=[],parts:string[]=[];
   if(raw[at]!==']')for(;;){if(items.length>=256)return fail();const child=value(depth+1);items.push(child.value);parts.push(child.canonical);whitespace();if(raw[at]===']')break;if(raw[at++]!==',')return fail();}
   at++;return {value:items,canonical:'['+parts.join(',')+']'};
  }
  for(const [token,literal] of [['true',true],['false',false],['null',null]] as const)if(raw.startsWith(token,at)){at+=token.length;return {value:literal,canonical:token};}
  const match=/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(raw.slice(at));if(!match||match[0].length>128)return fail();at+=match[0].length;return {value:numberToken(match[0]),canonical:match[0]};
 };
 const parsed=value(0);whitespace();if(at!==raw.length)return fail();return parsed;
}
/** Public records are already canonical. Validation must not repair a changed packet. */
export function athenaMedicationRecordedJson(raw:unknown):AthenaMedicationJson{const parsed=parseAthenaMedicationJson(raw);if(parsed.canonical!==raw)return fail();return parsed.value;}
/** Known integer fields keep their token too; range comparison uses digits only. */
export function athenaMedicationInt64(value:unknown):value is AthenaMedicationNumber{
 if(!isAthenaMedicationNumber(value)||! /^-?(?:0|[1-9][0-9]*)$/.test(value.raw))return false;
 const negative=value.raw.startsWith('-'),digits=negative?value.raw.slice(1):value.raw,limit=negative?'9223372036854775808':'9223372036854775807';
 return digits.length<limit.length||digits.length===limit.length&&digits<=limit;
}

/** Closed documented Athena fields surround an opaque, lossless structured sig. */
export type AthenaMedicationRecord = Record<string,AthenaMedicationJson>;
export type AthenaMedicationSection = Record<string,AthenaMedicationJson>&{medications:AthenaMedicationRecord[][];nomedicationsreported?:boolean;sectionnote?:string};
const sectionKeys=['lastdownloaddenialreason','lastdownloaddenied','lastdownloadeddate','lastupdated','medications','nomedicationsreported','patientdownloadconsent','patientneedsdownloadconsent','sectionnote'];
const sectionBooleans=['lastdownloaddenied','nomedicationsreported','patientdownloadconsent','patientneedsdownloadconsent'];
const recordKeys=['approvedby','billingndc','createdby','earliestfilldate','encounterid','events','filldate','futuresubmitdate','isdiscontinued','issafetorenew','isstructuredsig','medication','medicationentryid','medicationid','ndcoptions','newindicator','orderingmode','organclass','patientnote','pharmacy','pharmacyncpdpid','prescribedby','providernote','quantity','quantityunit','refillsallowed','route','rxnorm','source','status','stopreason','structuredsig','therapeuticclass','unstructuredsig'];
const recordBooleans=['isdiscontinued','issafetorenew','isstructuredsig'];
const recordIntegers=['encounterid','medicationid','refillsallowed'];
const clinicalObject=(v:AthenaMedicationJson):v is Record<string,AthenaMedicationJson>=>v!==null&&typeof v==='object'&&!Array.isArray(v)&&!isAthenaMedicationNumber(v);
const clinicalClosed=(v:AthenaMedicationJson,keys:readonly string[]):v is Record<string,AthenaMedicationJson>=>clinicalObject(v)&&Object.keys(v).every(k=>keys.includes(k));
const clinicalString=(v:AthenaMedicationJson,max=4096)=>typeof v==='string'&&[...v].length<=max;
const invalidSection=():never=>{throw new Error('The original Athena medication details could not be verified.');};
export function athenaMedicationSection(raw:unknown):AthenaMedicationSection{
 const parsed=athenaMedicationRecordedJson(raw);
 if(!clinicalClosed(parsed,sectionKeys))return invalidSection();
 const section=parsed as Record<string,AthenaMedicationJson>;
 if(!Array.isArray(section.medications)||section.medications.length>25)return invalidSection();
 for(const [key,value] of Object.entries(section))if(key!=='medications'&&(sectionBooleans.includes(key)?typeof value!=='boolean':!clinicalString(value)))return invalidSection();
 let count=0;
 for(const group of section.medications){
  if(!Array.isArray(group)||group.length>25)return invalidSection();
  for(const record of group){
   if(++count>25||!clinicalClosed(record,recordKeys))return invalidSection();
   for(const [key,value]of Object.entries(record)){
    if(recordBooleans.includes(key)){if(typeof value!=='boolean')return invalidSection();}
    else if(recordIntegers.includes(key)){if(!athenaMedicationInt64(value))return invalidSection();}
    else if(key==='quantity'){if(!isAthenaMedicationNumber(value))return invalidSection();}
    else if(key==='structuredsig'){if(!clinicalObject(value))return invalidSection();}
    else if(key==='events'){
     if(!Array.isArray(value)||value.length>100)return invalidSection();
     for(const event of value){if(!clinicalClosed(event,['eventdate','type','userdisplayname']))return invalidSection();for(const [field,recorded] of Object.entries(event))if(!(field==='userdisplayname'&&recorded===null)&&!clinicalString(recorded))return invalidSection();}
    }else if(key==='ndcoptions'||key==='rxnorm'){
     if(!Array.isArray(value)||value.length>100)return invalidSection();
     for(const option of value){if(!clinicalClosed(option,[key==='ndcoptions'?'ndcoption':'rxnormidentifier'])||Object.values(option).some(v=>!clinicalString(v)))return invalidSection();}
    }else if(!clinicalString(value,key==='medicationentryid'?300:4096))return invalidSection();
   }
  }
 }
 return section as AthenaMedicationSection;
}
