/**
 * Browser side of the voice path: join the Agora RTC channel, publish the mic (with Agora's speech
 * processing), and play the EarShot agent. Transcripts come from the backend bus, not from here.
 */
import AgoraRTC, { type IAgoraRTCClient, type IMicrophoneAudioTrack, type IRemoteAudioTrack } from 'agora-rtc-sdk-ng';
import type { VoiceSession } from './api';

AgoraRTC.setLogLevel(3); // warnings and errors only

export class VoiceCall {
  private rtc: IAgoraRTCClient;
  private mic: IMicrophoneAudioTrack | null = null;
  private agentMuted = false;
  private agentAudio: IRemoteAudioTrack | null = null;
  private readonly session: VoiceSession;
  /** True after the voice mic was disabled for a machine recording. Unmute then replaces the track. */
  private silenced = false;
  private micChain: Promise<void> = Promise.resolve();

  constructor(session: VoiceSession, onAutoplayBlocked: () => void) {
    this.session = session;
    this.rtc = AgoraRTC.createClient({ mode: 'rtc', codec: 'vp8' });
    AgoraRTC.onAutoplayFailed = onAutoplayBlocked;
  }

  async join(): Promise<void> {
    const { app_id, channel, token, uid } = this.session;
    this.rtc.on('user-published', async (user, mediaType) => {
      if (mediaType !== 'audio' || String(user.uid) !== this.session.agent_uid) return;
      await this.rtc.subscribe(user, 'audio');
      this.agentAudio = user.audioTrack ?? null;
      this.agentAudio?.setVolume(this.agentMuted ? 0 : 100);
      this.agentAudio?.play();
    });
    this.rtc.on('user-unpublished', (user) => {
      if (String(user.uid) === this.session.agent_uid) this.agentAudio = null;
    });
    await this.rtc.join(app_id, channel, token, uid);
    this.mic = await this.openMic();
    await this.rtc.publish([this.mic]);
  }

  private openMic(): ReturnType<typeof AgoraRTC.createMicrophoneAudioTrack> {
    // speech_standard is the preset conversational AI expects. AEC/ANS/AGC stay on for the voice path.
    return AgoraRTC.createMicrophoneAudioTrack({ encoderConfig: 'speech_standard', AEC: true, ANS: true, AGC: true });
  }

  /** 0..1 loudness of the agent's voice. */
  agentLevel(): number {
    return this.agentAudio?.getVolumeLevel() ?? 0;
  }

  /** 0..1 loudness of the worker's own mic. */
  micLevel(): number {
    return this.mic?.getVolumeLevel() ?? 0;
  }

  setAgentMuted(muted: boolean): void {
    this.agentMuted = muted;
    this.agentAudio?.setVolume(muted ? 0 : 100);
  }

  resumeAudio(): void {
    this.agentAudio?.play();
  }

  /** Muted while recording a machine so Agora's speech recognition does not hear it.
   * The raw recorder takes the device; the published track then stays silent unless it is replaced. */
  async setMuted(muted: boolean): Promise<void> {
    const run = this.micChain.then(() => this.applyMute(muted));
    this.micChain = run.catch(() => undefined);
    return run;
  }

  private async applyMute(muted: boolean): Promise<void> {
    if (!this.mic) return;
    if (muted) {
      this.silenced = true;
      await this.mic.setEnabled(false);
      return;
    }
    if (!this.silenced) {
      await this.mic.setEnabled(true);
      return;
    }
    const fresh = await this.openMic();
    this.silenced = false;
    const previous = this.mic;
    this.mic = fresh;
    if (previous) {
      await this.rtc.unpublish([previous]).catch(() => undefined);
      previous.close();
    }
    await this.rtc.publish([fresh]);
  }

  async leave(): Promise<void> {
    this.mic?.close();
    this.mic = null;
    await this.rtc.leave().catch(() => undefined);
  }
}
