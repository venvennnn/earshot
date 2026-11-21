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
  private agentAudio: IRemoteAudioTrack | null = null;
  private readonly session: VoiceSession;

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
      this.agentAudio?.play();
    });
    this.rtc.on('user-unpublished', (user) => {
      if (String(user.uid) === this.session.agent_uid) this.agentAudio = null;
    });
    await this.rtc.join(app_id, channel, token, uid);
    this.mic = await AgoraRTC.createMicrophoneAudioTrack({ AEC: true, ANS: true, AGC: true });
    await this.rtc.publish([this.mic]);
  }

  /** 0..1 loudness of the agent's voice. */
  agentLevel(): number {
    return this.agentAudio?.getVolumeLevel() ?? 0;
  }

  /** 0..1 loudness of the worker's own mic. */
  micLevel(): number {
    return this.mic?.getVolumeLevel() ?? 0;
  }

  resumeAudio(): void {
    this.agentAudio?.play();
  }

  /** Muted while recording a machine so Agora's speech recognition does not hear it. */
  async setMuted(muted: boolean): Promise<void> {
    await this.mic?.setMuted(muted);
  }

  async leave(): Promise<void> {
    this.mic?.close();
    this.mic = null;
    await this.rtc.leave().catch(() => undefined);
  }
}
