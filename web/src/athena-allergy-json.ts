/** Athena's original section is validated without converting its int64 codes to
 * JavaScript numbers. Parsed values are for review only; the original canonical
 * string is the value saved and hashed. */
type Parsed={value:unknown;canonical:string};
const fail=():never=>{throw new Error('The original Athena allergy details could not be verified.');};
export const athenaText=(v:unknown,max:number,multiline=false):v is string=>typeof v==='string'&&Array.from(v).length<=max&&!/[\ud800-\udfff]/u.test(v)&&!(multiline?/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/:/[\u0000-\u001f\u007f]/).test(v);
export const athenaNonblank=(v:string)=>!/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*$/u.test(v);
const quote=(v:string)=>JSON.stringify(v).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'));
const keys=(a:string,b:string)=>{const l=Array.from(a),r=Array.from(b);for(let i=0;i<Math.min(l.length,r.length);i++){const d=l[i].codePointAt(0)!-r[i].codePointAt(0)!;if(d)return d;}return l.length-r.length;};
export function athenaRecordedJson(raw:unknown):Record<string,unknown>{
 if(typeof raw!=='string'||new TextEncoder().encode(raw).length>65536)return fail();let at=0,nodes=0;
 const ws=()=>{while(/[\t\n\r ]/.test(raw[at]??'!'))at++;};
 const string=()=>{const start=at++;while(at<raw.length){const ch=raw[at++];if(ch==='"'){const s:unknown=JSON.parse(raw.slice(start,at));if(!athenaText(s,12000,true))return fail();return s;}if(ch==='\\')at++;}return fail();};
 const value=(depth:number):Parsed=>{if(++nodes>12000||depth>20)return fail();ws();const ch=raw[at];
  if(ch==='"'){const v=string();return {value:v,canonical:quote(v)};}
  if(ch==='{'){at++;ws();const result:Record<string,unknown>=Object.create(null),fields=new Map<string,string>();if(raw[at]!=='}')for(;;){if(raw[at]!=='"')return fail();const key=string();if(!athenaText(key,100)||Object.hasOwn(result,key))return fail();ws();if(raw[at++]!==':')return fail();const child=value(depth+1);result[key]=child.value;fields.set(key,child.canonical);ws();if(raw[at]==='}')break;if(raw[at++]!==',')return fail();ws();}at++;return {value:result,canonical:'{'+[...fields.keys()].sort(keys).map(k=>quote(k)+':'+fields.get(k)).join(',')+'}'};}
  if(ch==='['){at++;ws();const result:unknown[]=[],canonical:string[]=[];if(raw[at]!==']')for(;;){const child=value(depth+1);result.push(child.value);canonical.push(child.canonical);ws();if(raw[at]===']')break;if(raw[at++]!==',')return fail();}at++;return {value:result,canonical:'['+canonical.join(',')+']'};}
  for(const [token,v]of [['true',true],['false',false]] as const)if(raw.startsWith(token,at)){at+=token.length;return {value:v,canonical:token};}
  const match=/^-?(?:0|[1-9]\d*)/.exec(raw.slice(at));if(!match)return fail();at+=match[0].length;const integer=BigInt(match[0]);return {value:integer<=BigInt(Number.MAX_SAFE_INTEGER)&&integer>=BigInt(Number.MIN_SAFE_INTEGER)?Number(integer):integer,canonical:String(integer)};
 };
 const parsed=value(0);ws();if(at!==raw.length||parsed.canonical!==raw||!parsed.value||typeof parsed.value!=='object'||Array.isArray(parsed.value))return fail();return parsed.value as Record<string,unknown>;
}
const object=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v);
const closed=(v:unknown,required:readonly string[],allowed:readonly string[]):v is Record<string,unknown>=>object(v)&&required.every(k=>Object.hasOwn(v,k))&&Object.keys(v).every(k=>allowed.includes(k));
const array=(v:unknown,max:number):v is unknown[]=>Array.isArray(v)&&v.length<=max;
const code=(v:unknown,min:bigint)=>((typeof v==='number'&&Number.isSafeInteger(v))||typeof v==='bigint')&&BigInt(v)>=min&&BigInt(v)<=9223372036854775807n;
const patientKeys=['firstname','middlename','lastname','dob','status','deceaseddate'] as const;
export type AthenaPatientIdentity={firstname:string;lastname:string;middlename?:string;dob?:string;status?:string;deceaseddate?:string};
export function athenaBirthDate(v:string):boolean{if(v==='')return true;const m=/^(\d\d)\/(\d\d)\/(\d{4})$/.exec(v);if(!m)return false;const month=Number(m[1]),day=Number(m[2]),year=Number(m[3]),leap=year%4===0&&(year%100!==0||year%400===0);return year>=1&&month>=1&&month<=12&&day>=1&&day<=[31,leap?29:28,31,30,31,30,31,31,30,31,30,31][month-1];}
export function athenaPatientIdentity(raw:unknown):AthenaPatientIdentity{const p=athenaRecordedJson(raw);if(!closed(p,['firstname','lastname'],patientKeys)||Object.values(p).some(v=>!athenaText(v,300))||!athenaNonblank(p.firstname as string)||!athenaNonblank(p.lastname as string)||p.dob!==undefined&&!athenaBirthDate(p.dob as string))return fail();return p as AthenaPatientIdentity;}
export const athenaPatientName=(raw:string)=>{const p=athenaPatientIdentity(raw);return [p.firstname,p.middlename,p.lastname].filter(v=>v!==undefined&&v!=='').join(' ');};
export type AthenaAllergyReaction={reactionname?:string;severity?:string;severitysnomedcode?:number|bigint;snomedcode?:number|bigint};
export type AthenaAllergyRecord={id:string;allergenname:string;allergenid?:number|bigint;categories?:string[];criticality?:string;deactivatedate?:string;deactivateduser?:string;lastmodifiedby?:string;lastmodifieddatetime?:string;note?:string;onsetdate?:string;reactions?:AthenaAllergyReaction[]};
export type AthenaAllergySection={allergies:AthenaAllergyRecord[];nkda?:boolean;sectionnote?:string;lastmodifiedby?:string;lastmodifieddatetime?:string;lastupdated?:string;notelastmodifiedby?:string;notelastmodifieddatetime?:string};
const sectionKeys=['allergies','nkda','sectionnote','lastmodifiedby','lastmodifieddatetime','lastupdated','notelastmodifiedby','notelastmodifieddatetime'];
const recordKeys=['id','allergenid','allergenname','categories','criticality','deactivatedate','deactivateduser','lastmodifiedby','lastmodifieddatetime','note','onsetdate','reactions'];
const reactionKeys=['reactionname','severity','severitysnomedcode','snomedcode'];
export function athenaAllergySection(raw:unknown):AthenaAllergySection{
 const section=athenaRecordedJson(raw);if(!closed(section,['allergies'],sectionKeys)||!array(section.allergies,25)||section.nkda!==undefined&&typeof section.nkda!=='boolean')return fail();
 for(const [k,v]of Object.entries(section))if(!['allergies','nkda'].includes(k)&&!athenaText(v,k==='sectionnote'?4000:300,k==='sectionnote'))return fail();
 const ids=new Set<string>();for(const r of section.allergies){if(!closed(r,['id','allergenname'],recordKeys)||!athenaText(r.id,80)||!athenaNonblank(r.id)||ids.has(r.id)||!athenaText(r.allergenname,1000)||!athenaNonblank(r.allergenname))return fail();ids.add(r.id);
  for(const [k,v]of Object.entries(r))if(!['allergenid','categories','reactions'].includes(k)&&!athenaText(v,k==='note'?4000:1000,k==='note'))return fail();
  if(r.allergenid!==undefined&&!code(r.allergenid,1n)||r.categories!==undefined&&(!array(r.categories,20)||r.categories.some(v=>!athenaText(v,100))))return fail();
  if(r.reactions!==undefined){if(!array(r.reactions,25))return fail();for(const reaction of r.reactions){if(!closed(reaction,[],reactionKeys))return fail();for(const [k,v]of Object.entries(reaction))if(['snomedcode','severitysnomedcode'].includes(k)?!code(v,0n):!athenaText(v,1000))return fail();}}
 }
 return section as AthenaAllergySection;
}
