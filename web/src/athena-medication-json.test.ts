import {athenaMedicationSection} from './athena-medication-json';
import {describe,expect,it} from 'vitest';
import fixture from './__fixtures__/athena-medication-numeric.json';
import {parseAthenaMedicationJson,athenaMedicationRecordedJson,isAthenaMedicationNumber,athenaMedicationInt64} from './athena-medication-json';

// Shared wire fixture only; actual provider reader/formatter qualification and
// field-schema fixtures are separate. Never infer a clinical status from this data.
describe('Athena medication lossless JSON numbers',()=>{
 it('retains every original numeric token, grouping, repeated reference, null and conflicting recorded statement',()=>{
  const parsed=parseAthenaMedicationJson(fixture.raw_section_json);
  expect(parsed.canonical).toBe(fixture.expected_section_json);
  const section=parsed.value as Record<string,unknown>,groups=section.medications as Record<string,unknown>[][];
  expect(groups).toHaveLength(3);expect(groups[1]).toEqual([]);expect(groups[0][0].medicationentryid).toBe(groups[2][0].medicationentryid);
  expect(section.nomedicationsreported).toBe(true);expect(groups[0][0].status).toBe('PEND');
  expect(isAthenaMedicationNumber(groups[0][0].quantity)).toBe(true);
  expect(groups[0][0].quantity).toMatchObject({raw:'0.50'});
  const sig=groups[0][0].structuredsig as Record<string,unknown>;
  expect(sig.tiny).toMatchObject({raw:'1e-7'});expect(sig.signedzero).toMatchObject({raw:'-0'});
  expect(sig.minimum).toMatchObject({raw:'-9223372036854775808'});expect(sig.maximum).toMatchObject({raw:'9223372036854775807'});
  expect(sig.opaque).toMatchObject({'\ue000':{raw:'0.500'},'😀':{raw:'1E+3'}});
  expect((groups[0][0].events as Record<string,unknown>[])[0].userdisplayname).toBeNull();
  expect(section.sectionnote).toBe('Invented notes: café 🧪\r\nNo clinical instruction is inferred.');
 });
 it('accepts only the exact canonical public string for review while preserving strings as strings',()=>{
  expect(athenaMedicationRecordedJson(fixture.expected_section_json)).toEqual(parseAthenaMedicationJson(fixture.raw_section_json).value);
  expect(()=>athenaMedicationRecordedJson(fixture.raw_section_json)).toThrow();
  expect(()=>athenaMedicationRecordedJson(fixture.expected_section_json+'\n')).toThrow();
  const value=athenaMedicationRecordedJson('{"number":0.50,"string":"0.50"}') as Record<string,unknown>;
  expect(isAthenaMedicationNumber(value.number)).toBe(true);expect(value.string).toBe('0.50');expect(isAthenaMedicationNumber(value.string)).toBe(false);
 });
 it('uses Unicode codepoint key order and ASCII string escaping without changing original numeric spelling',()=>{
  const parsed=parseAthenaMedicationJson('{"😀":1E+03,"\ue000":-0,"é":"🧪"}');
  expect(parsed.canonical).toBe('{"\\u00e9":"\\ud83e\\uddea","\\ue000":-0,"\\ud83d\\ude00":1E+03}');
 });
 it.each(['0','-0','0.50','1e-7','1E+003','9223372036854775807','-9223372036854775808', '1'.repeat(128)])('keeps numeric lexeme %s without numeric conversion',token=>{
  const parsed=parseAthenaMedicationJson('{"x":'+token+'}');
  expect(parsed.canonical).toBe('{"x":'+token+'}');expect((parsed.value as Record<string,unknown>).x).toMatchObject({raw:token});
 });
 it('bounds a numeric token before interpreting or expanding it',()=>{
  expect(()=>parseAthenaMedicationJson('{"x":'+'1'.repeat(129)+'}')).toThrow();
  expect(parseAthenaMedicationJson('{"x":1e999999999}').canonical).toBe('{"x":1e999999999}');
 });
});

describe('Athena medication JSON structural refusal',()=>{
 it.each(['{"x":01}','{"x":+1}','{"x":NaN}','{"x":Infinity}','{"x":0.}','{"x":.5}','{"x":-}','{"x":1e}','{"x":1e+}','{"x":1} trailing','{"x":1,}','[1,]','{"x":"unescaped\nnewline"}','{"x":"\\q"}','{"x":true false}'])('rejects malformed JSON %s',raw=>{
  expect(()=>parseAthenaMedicationJson(raw)).toThrow();
 });
 it('decodes legitimate surrogate pairs and refuses lone surrogates rather than replacing them',()=>{
  expect(parseAthenaMedicationJson('{"emoji":"\\ud83e\\uddea"}').canonical).toBe('{"emoji":"\\ud83e\\uddea"}');
  for(const raw of ['{"x":"\\ud800"}','{"x":"\\udc00"}','{"x":"\\ud800a"}'])expect(()=>parseAthenaMedicationJson(raw)).toThrow();
 });
 it('rejects duplicate keys, including escaped spellings, rather than overwriting clinical values',()=>{
  expect(()=>parseAthenaMedicationJson('{"x":1,"x":2}')).toThrow();
  expect(()=>parseAthenaMedicationJson('{"a":1,"\\u0061":2}')).toThrow();
 });
 it('keeps unknown opaque object keys as data without prototype mutation',()=>{
  const value=athenaMedicationRecordedJson('{"__proto__":{"polluted":true},"nested":[null,{},[],"",false]}') as Record<string,unknown>;
  expect(Object.getPrototypeOf(value)).toBeNull();expect(Object.hasOwn(value,'__proto__')).toBe(true);
  expect(value.nested).toEqual([null,{},[],'',false]);expect(({} as Record<string,unknown>).polluted).toBeUndefined();
 });
});

describe('Athena medication codec exact bounded shape',()=>{
 it('does not confuse opaque numeric-looking objects with internal numeric tokens',()=>{
  const value=athenaMedicationRecordedJson('{"__proto__":{"kind":"number"},"kind":"number","raw":"0.50","token":"1e-7"}');
  expect(isAthenaMedicationNumber(value)).toBe(false);expect(value).toMatchObject({kind:'number',raw:'0.50',token:'1e-7'});
 });
 it('preserves escaped controls except NUL and refuses raw controls',()=>{
  const raw='{"control":"\\u0001\\b\\f\\n\\r\\t\\u001f"}';expect(parseAthenaMedicationJson(raw).canonical).toBe(raw);
  expect(()=>parseAthenaMedicationJson('{"x":"\\u0000"}')).toThrow();expect(()=>parseAthenaMedicationJson('{"\\u0000":true}')).toThrow();
  expect(()=>parseAthenaMedicationJson('{"x":"'+String.fromCharCode(1)+'"}')).toThrow();
 });
 it('counts root depth as zero and all container and scalar nodes exactly',()=>{
  expect(()=>parseAthenaMedicationJson('['.repeat(16)+'0'+']'.repeat(16))).not.toThrow();expect(()=>parseAthenaMedicationJson('['.repeat(17)+'0'+']'.repeat(17))).toThrow();
  const group=(n:number)=>'['+Array(n).fill('0').join(',')+']';
  const atLimit='['+[...Array(15).fill(group(256)),group(239)].join(',')+']';expect(()=>parseAthenaMedicationJson(atLimit)).not.toThrow();
  expect(()=>parseAthenaMedicationJson('['+[...Array(15).fill(group(256)),group(240)].join(',')+']')).toThrow();
 });
 it('enforces collection, key, string and input byte bounds without numeric coercion',()=>{
  const object=(n:number)=>'{'+Array.from({length:n},(_,i)=>'"k'+i+'":null').join(',')+'}';
  expect(()=>parseAthenaMedicationJson(object(64))).not.toThrow();expect(()=>parseAthenaMedicationJson(object(65))).toThrow();
  expect(()=>parseAthenaMedicationJson('['+Array(256).fill('null').join(',')+']')).not.toThrow();expect(()=>parseAthenaMedicationJson('['+Array(257).fill('null').join(',')+']')).toThrow();
  expect(()=>parseAthenaMedicationJson('{"'+'é'.repeat(128)+'":"'+'🧪'.repeat(4096)+'"}')).not.toThrow();
  expect(()=>parseAthenaMedicationJson('{"'+'é'.repeat(129)+'":true}')).toThrow();expect(()=>parseAthenaMedicationJson('"'+'🧪'.repeat(4097)+'"')).toThrow();
  expect(()=>parseAthenaMedicationJson(' '.repeat(65535)+'0')).not.toThrow();expect(()=>parseAthenaMedicationJson(' '.repeat(65536)+'0')).toThrow();
 });
});


it('checks signed-int64 grammar and bounds without changing integer tokens',()=>{
 const token=(text:string)=>(parseAthenaMedicationJson('{"x":'+text+'}').value as Record<string,unknown>).x;
 for(const raw of ['0','-0','9223372036854775807','-9223372036854775808']){const value=token(raw);expect(athenaMedicationInt64(value)).toBe(true);expect(value).toMatchObject({raw});}
 for(const raw of ['9223372036854775808','-9223372036854775809','0.0','1e0'])expect(athenaMedicationInt64(token(raw))).toBe(false);
 expect(athenaMedicationInt64('1')).toBe(false);expect(athenaMedicationInt64({raw:'1',kind:'number'})).toBe(false);
});

it('validates closed medication fields while retaining opaque structured sig keys and only the documented nullable event field',()=>{
 const section=parseAthenaMedicationJson('{"medications":[[{"quantity":0.50,"encounterid":-0,"medicationid":9223372036854775807,"refillsallowed":-9223372036854775808,"structuredsig":{"unknown":null,"kind":"number","__proto__":{"raw":1e-7}},"events":[{"userdisplayname":null}],"rxnorm":[{}],"ndcoptions":[{}]}]]}').canonical;
 expect(athenaMedicationSection(section).medications[0][0].quantity).toMatchObject({raw:'0.50'});
 for(const raw of ['{"medications":[],"unknown":true}','{"medications":[[{"unknown":true}]]}','{"medications":[[{"events":[{"unknown":"x"}]}]]}','{"medications":[[{"quantity":"0.5"}]]}','{"medications":[[{"medicationid":1.0}]]}','{"medications":[[{"refillsallowed":1e1}]]}','{"medications":[[{"structuredsig":[]}]]}','{"medications":[[{"events":[{"eventdate":null}]}]]}','{"medications":[[{"medication":null}]]}','{"medications":[[{"rxnorm":[{"other":"x"}]}]]}'])expect(()=>athenaMedicationSection(raw),raw).toThrow();
});
it('enforces medication group/record/event and entry-reference bounds without dropping records',()=>{
 const canonical=(raw:string)=>parseAthenaMedicationJson(raw).canonical;
 expect(athenaMedicationSection(canonical('{"medications":['+Array(25).fill('[]').join(',')+']}')).medications).toHaveLength(25);
 expect(()=>athenaMedicationSection(canonical('{"medications":['+Array(26).fill('[]').join(',')+']}'))).toThrow();
 expect(()=>athenaMedicationSection(canonical('{"medications":['+Array(2).fill('['+Array(13).fill('{}').join(',')+']').join(',')+']}'))).toThrow();
 expect(()=>athenaMedicationSection(canonical('{"medications":[[{"medicationentryid":"'+'x'.repeat(301)+'"}]]}'))).toThrow();
 expect(()=>athenaMedicationSection(canonical('{"medications":[[{"events":['+Array(101).fill('{}').join(',')+']}]]}'))).toThrow();
});
