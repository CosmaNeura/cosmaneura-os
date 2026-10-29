/** Select native keyboard/focus behavior for invented rehearsal data only. */
export function nativeRehearsal(url:URL,topLevel:boolean):boolean {
  return url.searchParams.has('native-chat') || topLevel &&
    url.protocol==='capacitor:' && url.hostname==='localhost' &&
    !url.port && !url.username && !url.password;
}
