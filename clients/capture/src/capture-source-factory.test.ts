import {afterEach,expect,it,vi} from "vitest";
import {createCaptureSource,isIosNativePlatform} from "./capture-source-factory";

it("selects the existing native adapter only for an eligible iOS build without starting it", async () => {
  const source={kind:"microphone" as const,start:vi.fn(),stop:vi.fn()};
  const load=vi.fn(async () => ({createCapacitorIosNativeMicrophoneCaptureSource:() => source}));
  const result=await createCaptureSource({iosNativePcmEnabled:true,iosNativePlatformEligible:true,iosNativeModuleLoader:load});
  expect(result).toBe(source); expect(load).toHaveBeenCalledOnce(); expect(source.start).not.toHaveBeenCalled();
});
it("does not substitute browser capture when the selected native adapter is unavailable", async () => {
  const browser=vi.fn();
  await expect(createCaptureSource({iosNativePcmEnabled:true,iosNativePlatformEligible:true,iosNativeModuleLoader:null,
    microphoneTestEnabled:true,microphoneModuleLoader:browser})).rejects.toMatchObject({code:"audio_capture_unavailable"});
  expect(browser).not.toHaveBeenCalled();
});
it.each([[true,"ios",true],[false,"ios",false],[true,"android",false],[false,"web",false]])(
  "checks actual platform eligibility (%s/%s)", async (native,platform,expected) => {
    expect(await isIosNativePlatform(async () => ({Capacitor:{isNativePlatform:() => native as boolean,getPlatform:() => platform as string}}))).toBe(expected);
  });

afterEach(() => vi.unstubAllEnvs());
it("refuses a selected iOS source on an unavailable platform instead of generating synthetic silence", async () => {
  vi.stubEnv("VITE_WORKSPACE_CAPTURE_MODE", "ios_native");
  const browser=vi.fn();
  await expect(createCaptureSource({iosNativePcmEnabled:true,iosNativePlatformEligible:false,
    microphoneTestEnabled:true,microphoneModuleLoader:browser})).rejects.toMatchObject({code:"audio_capture_unavailable"});
  expect(browser).not.toHaveBeenCalled();
});
