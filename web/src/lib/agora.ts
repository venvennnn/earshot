/**
 * Browser side of the voice path: join the Agora RTC channel, publish the mic, play the agent,
 * and receive live transcripts / agent state / metrics over RTM via Agora's agent client toolkit.
 */
import AgoraRTC, { type IAgoraRTCClient, type IMicrophoneAudioTrack, type IRemoteAudioTrack } from 'agora-rtc-sdk-ng';
import AgoraRTM from 'agora-rtm';
import {
  AgoraVoiceAI,
  AgoraVoiceAIEvents,
  TranscriptHelperMode,
  TurnStatus,
  type AgentMetric,
  type TranscriptHelperItem,
} from 'agora-agent-client-toolkit';
import type { VoiceSession } from './api';

export interface Line {
  id: string;
  who: 'worker' | 'agent';
  text: string;
  final: boolean;
}

export interface VoiceCallHandlers {
  onTranscript: (lines: Line[]) => void;
  onAgentSpeaking: (speaking: boolean) => void;
  onMetric: (metric: AgentMetric) => void;
  onAutoplayBlocked: () => void;
}

type RTMClient = InstanceType<typeof AgoraRTM.RTM>;

AgoraRTC.setLogLevel(3); // warnings and errors only

export class VoiceCall {
  private rtc: IAgoraRTCClient;
  private rtm: RTMClient;
  private ai: AgoraVoiceAI | null = null;
  private mic: IMicrophoneAudioTrack | null = null;
  private agentAudio: IRemoteAudioTrack | null = null;
  private readonly session: VoiceSession;
  private readonly handlers: VoiceCallHandlers;

  constructor(session: VoiceSession, handlers: VoiceCallHandlers) {
    this.session = session;
    this.handlers = handlers;
    this.rtc = AgoraRTC.createClient({ mode: 'rtc', codec: 'vp8' });
    this.rtm = new AgoraRTM.RTM(session.app_id, String(session.uid));
  }

  async join(): Promise<void> {
    const { app_id, channel, token, uid } = this.session;
    AgoraRTC.onAutoplayFailed = () => this.handlers.onAutoplayBlocked();

    this.rtc.on('user-published', async (user, mediaType) => {
      if (mediaType !== 'audio' || String(user.uid) !== this.session.agent_uid) return;
      await this.rtc.subscribe(user, 'audio');
      this.agentAudio = user.audioTrack ?? null;
      this.agentAudio?.play();
    });
    this.rtc.on('user-unpublished', (user) => {
      if (String(user.uid) === this.session.agent_uid) this.agentAudio = null;
    });

    await this.rtm.login({ token });
    this.ai = await AgoraVoiceAI.init({
      rtcEngine: this.rtc,
      rtmEngine: this.rtm,
      renderMode: TranscriptHelperMode.TEXT,
    });
    this.ai.on(AgoraVoiceAIEvents.TRANSCRIPT_UPDATED, (items) => this.handlers.onTranscript(this.toLines(items)));
    this.ai.on(AgoraVoiceAIEvents.AGENT_SPEAKING_CHANGED, (_agent, speaking) => this.handlers.onAgentSpeaking(speaking));
    this.ai.on(AgoraVoiceAIEvents.AGENT_METRICS, (_agent, metric) => this.handlers.onMetric(metric));
    // Agent pipeline errors (ASR / LLM / TTS) reported by Agora; visible in the browser console for debugging.
    this.ai.on(AgoraVoiceAIEvents.AGENT_ERROR, (agent, error) => console.warn('[EarShot] agent error', agent, error));

    await this.rtc.join(app_id, channel, token, uid);
    this.mic = await AgoraRTC.createMicrophoneAudioTrack({ AEC: true, ANS: true, AGC: true });
    await this.rtc.publish([this.mic]);
    this.ai.subscribeMessage(channel);
  }

  /** 0..1 loudness of the agent's voice, for the orb animation. */
  agentLevel(): number {
    return this.agentAudio?.getVolumeLevel() ?? 0;
  }

  /** 0..1 loudness of the worker's own mic, so they can see they are being picked up. */
  micLevel(): number {
    return this.mic?.getVolumeLevel() ?? 0;
  }

  resumeAudio(): void {
    this.agentAudio?.play();
  }

  async setMuted(muted: boolean): Promise<void> {
    await this.mic?.setMuted(muted);
  }

  async leave(): Promise<void> {
    this.ai?.unsubscribe();
    this.ai?.destroy();
    this.ai = null;
    this.mic?.close();
    this.mic = null;
    await this.rtc.leave().catch(() => undefined);
    await this.rtm.logout().catch(() => undefined);
  }

  private toLines(items: TranscriptHelperItem<unknown>[]): Line[] {
    return items
      .filter((i) => i.text.trim())
      .map((i) => ({
        id: `${i.uid}-${i.turn_id}`,
        // The toolkit tags the local user's own speech with uid "0"; everything else is the agent.
        who: String(i.uid) === '0' ? 'worker' : 'agent',
        text: i.text,
        final: i.status !== TurnStatus.IN_PROGRESS,
      }));
  }
}
