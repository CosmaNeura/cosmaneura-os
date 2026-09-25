import {describe,it,expect} from "vitest";
import golden from "../../tests/fixtures/capture_continuity.json";
import {parseCaptureContinuity} from "../../clients/scribe-review/creator-review-api";

describe("reviewed recording recovery evidence",()=>{
  it("retains the receiver hash and gap without inventing a native start",()=>{
    expect(parseCaptureContinuity(golden)).toEqual(golden);
    expect(golden.starts).toEqual([]);
    expect(golden.recovery.interruptions[0].decision).toBe("finish_capture");
  });
  it.each(["unknown", "missing", "repeated", "after_finish", "position", "old_version", "reason_type"])("rejects %s evidence",kind=>{
    const value:any=structuredClone(golden), gap=value.recovery.interruptions[0];
    if(kind==="unknown")value.recovery.missing_speech="invented";
    if(kind==="missing")delete value.recovery;
    if(kind==="repeated")value.recovery.interruptions.push({...gap});
    if(kind==="after_finish")value.recovery.interruptions.push({...gap,receipt_id:crypto.randomUUID(),gap_id:crypto.randomUUID()});
    if(kind==="position")gap.next_sequence_number=true;
    if(kind==="old_version")value.schema_version="1.0";
    if(kind==="reason_type")gap.reason_code=[gap.reason_code];
    expect(()=>parseCaptureContinuity(value)).toThrow();
  });
});
