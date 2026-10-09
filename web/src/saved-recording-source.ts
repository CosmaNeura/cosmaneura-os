import type {CaptureSource,CaptureSourceStartOptions} from '../../clients/capture/src/configured/capture/source';
import type {PrivateRecordingRuntime} from './private-recording-runtime';
import {QueueInvariantError} from '../../clients/capture/src/queue/errors';

/** Imports verified saved microphone audio; no hardware permission or recorder. */
export class SavedRecordingSource implements CaptureSource {
  readonly kind='microphone' as const;
  private options:CaptureSourceStartOptions|null=null;
  constructor(private recording:Pick<PrivateRecordingRuntime,'savedChunks'>,private current:()=>boolean){}
  async start(options:CaptureSourceStartOptions){
    if(this.options||!this.current()||options.signal?.aborted)throw new QueueInvariantError('capture_saved_session_changed');
    const media=options.capabilities.media;
    if(media.media_type!=='audio/wav'||media.encoding!=='pcm_s16le'||media.sample_rate_hz!==16000||media.channels!==1)
      throw new QueueInvariantError('capture_source_unavailable');
    this.options=options;
  }
  async stop(){this.options=null;}
  async feed(first:number,total:number):Promise<number>{
    const options=this.options;
    if(!options)throw new QueueInvariantError('capture_state_conflict');
    let count=0;
    for await(const chunk of this.recording.savedChunks(first)){
      if(!this.current()||this.options!==options||options.signal?.aborted)throw new QueueInvariantError('capture_access_unavailable');
      if(count>=options.capabilities.max_chunks||first+count>=total)break;
      if(chunk.sequence!==first+count)throw new QueueInvariantError('capture_chunk_position_conflict');
      const durationMs=(chunk.wavBytes.length-44)/32;
      await options.onChunk({sequenceNumber:count,durationMs,wavBytes:chunk.wavBytes});
      count++;
      if(count>=options.capabilities.max_chunks||first+count>=total)break;
    }
    return count;
  }
}
