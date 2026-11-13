import { Capacitor, registerPlugin, type PluginListenerHandle } from '@capacitor/core';

export type AppleCredential = {status: 'credential'; token: string} |
  {status: 'canceled' | 'error' | 'dismissed'};
export interface AppleSignInPlugin {
  environment(options: {publishableKey: string}): Promise<{enabled: boolean}>;
  mount(options: {id: string; x: number; y: number; width: number; height: number}): Promise<void>;
  unmount(options: {id: string}): Promise<void>;
  credential(options: {id: string}): Promise<AppleCredential>;
  finish(options: {id: string}): Promise<void>;
  addListener(event: 'appleTapped', listener: (value: {id: string}) => void): Promise<PluginListenerHandle>;
}
export const AppleSignIn = registerPlugin<AppleSignInPlugin>('CosmasAppleSignIn');
export function nativeAppleSignInAvailable() {
  return Capacitor.getPlatform() === 'ios' && Capacitor.isPluginAvailable('CosmasAppleSignIn');
}
