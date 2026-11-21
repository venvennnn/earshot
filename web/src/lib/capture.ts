/**
 * Raw machine-sound capture with Web Audio. Noise suppression, echo cancellation and auto gain are OFF:
 * those would remove exactly the machine sound EarShot needs. (Agora's speech path is muted meanwhile.)
 */

export const CLIP_SECONDS = 10;

export function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const write = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
  };
  write(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  write(8, 'WAVE');
  write(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  write(36, 'data');
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buffer], { type: 'audio/wav' });
}

export class Recorder {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private analyser: AnalyserNode | null = null;
  private processor: ScriptProcessorNode | null = null;
  private chunks: Float32Array[] = [];
  private capturing = false;
  private levelBuf = new Float32Array(2048);

  async open(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { noiseSuppression: false, echoCancellation: false, autoGainControl: false, channelCount: 1 },
    });
    this.ctx = new AudioContext();
    await this.ctx.resume();
    const source = this.ctx.createMediaStreamSource(this.stream);
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 2048;
    source.connect(this.analyser);
    // ScriptProcessor works on every mobile browser; muted output keeps it running without feedback.
    this.processor = this.ctx.createScriptProcessor(4096, 1, 1);
    const mute = this.ctx.createGain();
    mute.gain.value = 0;
    source.connect(this.processor);
    this.processor.connect(mute);
    mute.connect(this.ctx.destination);
    this.processor.onaudioprocess = (e) => {
      if (this.capturing) this.chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    };
  }

  /** Current loudness 0..1 (RMS, scaled for display). */
  level(): number {
    if (!this.analyser) return 0;
    this.analyser.getFloatTimeDomainData(this.levelBuf);
    let sum = 0;
    for (const v of this.levelBuf) sum += v * v;
    return Math.min(1, Math.sqrt(sum / this.levelBuf.length) * 6);
  }

  async beep(frequency = 880, ms = 180): Promise<void> {
    if (!this.ctx) return;
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    osc.frequency.value = frequency;
    gain.gain.value = 0.25;
    osc.connect(gain).connect(this.ctx.destination);
    osc.start();
    osc.stop(this.ctx.currentTime + ms / 1000);
    await new Promise((r) => window.setTimeout(r, ms + 250)); // let the beep die away before/after capture
  }

  /** Beep, record `seconds`, beep. `onTick` gets seconds left. Resolves with a WAV blob. */
  async record(seconds: number, onTick: (left: number) => void, signal?: AbortSignal): Promise<Blob | null> {
    if (!this.ctx) throw new Error('Microphone is not open');
    await this.beep(880);
    this.chunks = [];
    this.capturing = true;
    const started = performance.now();
    while (performance.now() - started < seconds * 1000) {
      if (signal?.aborted) {
        this.capturing = false;
        return null;
      }
      onTick(Math.ceil(seconds - (performance.now() - started) / 1000));
      await new Promise((r) => window.setTimeout(r, 100));
    }
    this.capturing = false;
    onTick(0);
    await this.beep(660);
    const total = this.chunks.reduce((n, c) => n + c.length, 0);
    const all = new Float32Array(total);
    let offset = 0;
    for (const c of this.chunks) {
      all.set(c, offset);
      offset += c.length;
    }
    return encodeWav(all, this.ctx.sampleRate);
  }

  close(): void {
    this.capturing = false;
    this.processor?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    void this.ctx?.close();
    this.ctx = null;
    this.stream = null;
  }
}

/** Any audio file the browser can play (WAV, MP3, M4A, …) -> mono WAV, first `maxSeconds` seconds. */
export async function fileToWav(file: File, maxSeconds = CLIP_SECONDS): Promise<Blob> {
  const ctx = new AudioContext();
  try {
    const audio = await ctx.decodeAudioData(await file.arrayBuffer());
    const length = Math.min(audio.length, Math.round(maxSeconds * audio.sampleRate));
    const mono = new Float32Array(length);
    for (let ch = 0; ch < audio.numberOfChannels; ch++) {
      const data = audio.getChannelData(ch);
      for (let i = 0; i < length; i++) mono[i] += data[i] / audio.numberOfChannels;
    }
    return encodeWav(mono, audio.sampleRate);
  } catch {
    throw new Error("Couldn't read that file. Try a WAV or MP3 recording.");
  } finally {
    void ctx.close();
  }
}
