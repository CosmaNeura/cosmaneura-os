export type GoogleNavigationConfig={clientId:string;callbackUri:string};
export function googleNavigationConfig(clientId?:string,callbackUri?:string):GoogleNavigationConfig|null;
export function validGoogleNavigationUrl(href:unknown,config:GoogleNavigationConfig|null):boolean;
