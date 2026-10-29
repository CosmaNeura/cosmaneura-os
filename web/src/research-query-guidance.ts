import type {ResearchSource,ResearchTopic} from './research-contract';

// New-query guidance is separate from the wire validator: older saved requests
// must still load and resolve with their original query and idempotency key.
export function researchQueryIssue(sources:readonly ResearchSource[],query:string):string|null {
 if(sources.includes('npi_registry')&&!/^[0-9]{10}$/.test(query))
  return 'NPI Registry needs a 10-digit NPI. Enter the NPI or deselect NPI Registry to use a different query.';
 if(sources.includes('cms_coverage')&&!/^(?:NCD\s*)?[0-9]{1,8}(?::[0-9]{1,8})?$/i.test(query))
  return 'CMS Coverage needs an NCD ID, such as 123 or 123:2 for a specific version. Enter the ID or deselect CMS Coverage to use a different query.';
 return null;
}

export function researchQueryGuidance(topic:ResearchTopic,sources:readonly ResearchSource[]) {
 if(sources.includes('npi_registry'))return {label:'Public NPI to look up',placeholder:'For example, 1234567890',help:'Enter the public 10-digit NPI, without spaces or a provider name.'};
 if(sources.includes('cms_coverage'))return {label:'Public NCD ID to look up',placeholder:'For example, 123 or NCD 123:2',help:'Enter an NCD ID. Add :version if you need a particular version. This source does not search policy wording or full LCD content.'};
 if(topic==='drug_safety')return {label:'Public drug query',placeholder:'Enter a medication name…',help:'Use a medication name. For openFDA, use the generic name; RxNorm provides names and identifiers.'};
 if(topic==='trials')return {label:'Public question',placeholder:'For example, myocardial infarction AND stem cell',help:''};
 if(topic==='coverage'||topic==='provider_data')return {label:'Public query',placeholder:'Enter a public value for the selected source…',help:'Mapped datasets look for an exact value in the configured field. Check the selected source description before searching.'};
 return {label:'Public question',placeholder:'For example, recent reviews of treatment options…',help:''};
}

export function researchSourceFailure(source:ResearchSource,code:string,query:string):string {
 // A historical invalid identifier retains the existing backend error code.
 // Explain that input without reclassifying a malformed publisher response.
 if(code==='invalid_source_response')return researchQueryIssue([source],query)
  ??'The source response could not be verified. No records from this source were accepted. Try a new reviewed search later.';
 switch(code){
  case 'no_matching_record':return 'No matching record was returned. Check the query or identifier, then review a revised search. This does not establish that evidence is absent.';
  case 'source_rate_limited':return 'The source is limiting requests. Wait a little, then review a new search.';
  case 'source_timeout':return 'The source took too long to respond. Try a new reviewed search later, or choose another source.';
  case 'source_not_configured':return 'This source is not connected. Check the research connection or choose another source.';
  default:return 'The source is unavailable. Try a new reviewed search later, or choose another source.';
 }
}
