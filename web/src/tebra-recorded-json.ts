/** Original FHIR JSON is never reserialized from JS numbers. This parser checks
 * bounds, duplicate keys and unsupported modifiers while retaining numeric
 * spelling for exact-source validation. Large JSON integers remain bigint here;
 * these parsed values are only inspected, never sent, stored or used for dosing.
 */
type Parsed={value:unknown;canonical:string;number?:string};
const numberSpellings=new WeakMap<object,Map<string,string>>();
const fail=():never=>{throw new Error('Invalid original Tebra details');};
const text=(v:string,max:number,instructions=false)=>Array.from(v).length>=1&&Array.from(v).length<=max&&!/[\ud800-\udfff]/u.test(v)&&!(instructions?/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/:/[\u0000-\u001f\u007f]/).test(v);
const jsonString=(v:string)=>JSON.stringify(v).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'));
const compareKeys=(a:string,b:string)=>{const left=Array.from(a),right=Array.from(b);for(let i=0;i<Math.min(left.length,right.length);i++){const d=left[i].codePointAt(0)!-right[i].codePointAt(0)!;if(d)return d;}return left.length-right.length;};
export function tebraJson(raw:unknown,kind:'object'|'array'='object'):Record<string,unknown>|unknown[]{
 if(typeof raw!=='string'||new TextEncoder().encode(raw).length>65536)return fail();let at=0,nodes=0;
 const ws=()=>{while(/[\t\n\r ]/.test(raw[at]??'!'))at++;};
 const string=()=>{const start=at++;while(at<raw.length){const ch=raw[at++];if(ch==='"'){const s:unknown=JSON.parse(raw.slice(start,at));if(typeof s!=='string'||!text(s,12000,true))return fail();return s;}if(ch==='\\')at++;}return fail();};
 const value=(depth:number):Parsed=>{if(++nodes>12000||depth>24)return fail();ws();const ch=raw[at];
  if(ch==='"'){const v=string();return {value:v,canonical:jsonString(v)};}
  if(ch==='{'){at++;ws();const result:Record<string,unknown>=Object.create(null),fields=new Map<string,string>(),numbers=new Map<string,string>();if(raw[at]!=='}')for(;;){if(raw[at]!=='"')return fail();const key=string();if(!text(key,100)||Object.hasOwn(result,key)||key==='modifierExtension'||key==='implicitRules')return fail();ws();if(raw[at++]!==':')return fail();const parsed=value(depth+1);result[key]=parsed.value;fields.set(key,parsed.canonical);if(parsed.number!==undefined)numbers.set(key,parsed.number);ws();if(raw[at]==='}')break;if(raw[at++]!==',')return fail();ws();}at++;numberSpellings.set(result,numbers);return {value:result,canonical:'{'+[...fields.keys()].sort(compareKeys).map(k=>jsonString(k)+':'+fields.get(k)).join(',')+'}'};}
  if(ch==='['){at++;ws();const result:unknown[]=[],canonical:string[]=[],numbers=new Map<string,string>();if(raw[at]!==']')for(;;){const parsed=value(depth+1);if(parsed.number!==undefined)numbers.set(String(result.length),parsed.number);result.push(parsed.value);canonical.push(parsed.canonical);ws();if(raw[at]===']')break;if(raw[at++]!==',')return fail();}at++;numberSpellings.set(result,numbers);return {value:result,canonical:'['+canonical.join(',')+']'};}
  for(const [token,v]of [['true',true],['false',false]] as const)if(raw.startsWith(token,at)){at+=token.length;return {value:v,canonical:token};}
  const match=/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(raw.slice(at));if(!match)return fail();at+=match[0].length;const token=match[0],numeric=Number(token),isInteger=/^-?(?:0|[1-9]\d*)$/.test(token);if(!isInteger&&!Number.isFinite(numeric))return fail();return {value:isInteger&&!Number.isSafeInteger(numeric)?BigInt(token):numeric,canonical:token,number:token};
 };
 const parsed=value(0);ws();if(at!==raw.length||parsed.canonical!==raw||(kind==='array'?!Array.isArray(parsed.value):!parsed.value||typeof parsed.value!=='object'||Array.isArray(parsed.value)))return fail();return parsed.value as Record<string,unknown>|unknown[];
}
export function tebraNonnegativeIntegerMember(object:Record<string,unknown>,key:string):boolean{const token=numberSpellings.get(object)?.get(key);return token!==undefined&&/^(?:0|[1-9]\d*)$/.test(token);}

export const tebraOriginalNumber=(owner:object,key:string):string|undefined=>numberSpellings.get(owner)?.get(key);
