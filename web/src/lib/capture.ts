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

/** RMS amplitude -> 0..1 for display: -60 dBFS (silence) .. -10 dBFS (loud). */
export function dbLevel(rms: number): number {
  const db = 20 * Math.log10(rms + 1e-9);
  return Math.max(0, Math.min(1, (db + 60) / 50));
}

/** Below this the backend rejects a clip as too quiet (about -55 dBFS). */
export const QUIET_LEVEL = 0.1;

export const WAVEFORM_BINS = 96;

type WaveformBin = { min: number; max: number };

function addWaveformSamples(bins: WaveformBin[], samples: Float32Array, samplesPerBin: number, offset = 0): void {
  for (let i = 0; i < samples.length; i++) {
    const index = Math.min(WAVEFORM_BINS - 1, Math.floor((offset + i) / samplesPerBin));
    const sample = samples[i];
    const bin = bins[index] ?? (bins[index] = { min: 0, max: 0 });
    bin.min = Math.min(bin.min, sample);
    bin.max = Math.max(bin.max, sample);
  }
}

function waveformPath(bins: WaveformBin[]): string {
  // Compress the display scale so low-amplitude sounds are still visible.
  const ordinate = (amplitude: number) => Math.sign(amplitude) * Math.sqrt(Math.min(1, Math.abs(amplitude))) * 29;
  return bins.map(({ min, max }, i) =>
    `M${i + 0.5} ${32 - ordinate(max)}V${32 - ordinate(min)}`
  ).join(' ');
}

let captureContext: AudioContext | null = null;

function recordingContext(): AudioContext {
  if (!captureContext || captureContext.state === 'closed') captureContext = new AudioContext();
  return captureContext;
}

/** Unlock audio during a phone app gesture so later spoken commands can capture automatically. */
export function primeRecordingAudio(): void {
  try {
    const ctx = recordingContext();
    if (ctx.state !== 'running') void ctx.resume().catch(() => {});
  } catch {
    // Unsupported browsers report the error when recording is requested.
  }
}

async function resumeRecordingAudio(ctx: AudioContext): Promise<void> {
  if (ctx.state === 'running') return;
  let timer: number | undefined;
  try {
    await Promise.race([
      ctx.resume(),
      new Promise<never>((_, reject) => {
        timer = window.setTimeout(() => reject(new Error('The browser paused recording audio. Tap Retry microphone to enable it.')), 2000);
      }),
    ]);
  } finally {
    window.clearTimeout(timer);
  }
}

export class Recorder {
  private ctx: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private output: GainNode | null = null;
  private stream: MediaStream | null = null;
  private analyser: AnalyserNode | null = null;
  private processor: ScriptProcessorNode | null = null;
  private chunks: Float32Array[] = [];
  private capturing = false;
  private waveform: WaveformBin[] = [];
  private samplesPerBin = 1;
  private capturedSamples = 0;

  waveformPath(): string {
    return waveformPath(this.waveform);
  }
  private levelBuf = new Float32Array(2048);

  async open(signal?: AbortSignal): Promise<void> {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      throw new Error('Open EarShot over HTTPS to use the phone microphone.');
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { noiseSuppression: false, echoCancellation: false, autoGainControl: false, channelCount: 1 },
    });
    if (signal?.aborted) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    this.stream = stream;
    this.ctx = recordingContext();
    await resumeRecordingAudio(this.ctx);
    if (!this.ctx || signal?.aborted) return;
    const source = this.ctx.createMediaStreamSource(this.stream);
    this.source = source;
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 2048;
    source.connect(this.analyser);
    // ScriptProcessor works on every mobile browser; muted output keeps it running without feedback.
    this.processor = this.ctx.createScriptProcessor(4096, 1, 1);
    const mute = this.ctx.createGain();
    this.output = mute;
    mute.gain.value = 0;
    source.connect(this.processor);
    this.processor.connect(mute);
    mute.connect(this.ctx.destination);
    this.processor.onaudioprocess = (e) => {
      if (!this.capturing) return;
      const samples = new Float32Array(e.inputBuffer.getChannelData(0));
      this.chunks.push(samples);
      addWaveformSamples(this.waveform, samples, this.samplesPerBin, this.capturedSamples);
      this.capturedSamples += samples.length;
    };
  }

  /** Current loudness 0..1 on a decibel scale, so quiet machine sound still moves the meter. */
  level(): number {
    if (!this.analyser) return 0;
    this.analyser.getFloatTimeDomainData(this.levelBuf);
    let sum = 0;
    for (const v of this.levelBuf) sum += v * v;
    return dbLevel(Math.sqrt(sum / this.levelBuf.length));
  }

  async beep(frequency = 880, ms = 180): Promise<void> {
    if (!this.ctx) return;
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    osc.frequency.value = frequency;
    gain.gain.value = 0.25;
    osc.connect(gain).connect(this.ctx.destination);
    osc.onended = () => {
      osc.disconnect();
      gain.disconnect();
    };
    osc.start();
    osc.stop(this.ctx.currentTime + ms / 1000);
    await new Promise((r) => window.setTimeout(r, ms + 250)); // let the beep die away before/after capture
  }

  /** Beep, record `seconds`, beep. `onTick` gets seconds left. Resolves with a WAV blob. */
  async record(seconds: number, onTick: (left: number) => void, signal?: AbortSignal): Promise<Blob | null> {
    if (!this.ctx) throw new Error('Microphone is not open');
    await this.beep(880);
    if (signal?.aborted) return null;
    this.chunks = [];
    this.waveform = [];
    this.capturedSamples = 0;
    this.samplesPerBin = Math.ceil(this.ctx.sampleRate * seconds / WAVEFORM_BINS);
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
    if (!this.ctx || signal?.aborted) return null;
    const total = this.chunks.reduce((n, c) => n + c.length, 0);
    if (!total) throw new Error('No microphone audio was captured. Check your microphone permission and try again.');
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
    this.source?.disconnect();
    this.source = null;
    this.output?.disconnect();
    this.output = null;
    this.processor?.disconnect();
    this.processor = null;
    this.analyser = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx = null;
    this.stream = null;
  }
}

/** Any audio file the browser can play (WAV, MP3, M4A, …) -> mono WAV of the first `maxSeconds` seconds,
 * plus `bars` loudness values across it (to draw the file's real waveform). */
export async function fileToWav(file: File, bars = 48, maxSeconds = CLIP_SECONDS): Promise<{ wav: Blob; levels: number[]; waveform: string }> {
  const ctx = new AudioContext();
  try {
    const audio = await ctx.decodeAudioData(await file.arrayBuffer());
    const length = Math.min(audio.length, Math.round(maxSeconds * audio.sampleRate));
    const mono = new Float32Array(length);
    for (let ch = 0; ch < audio.numberOfChannels; ch++) {
      const data = audio.getChannelData(ch);
      for (let i = 0; i < length; i++) mono[i] += data[i] / audio.numberOfChannels;
    }
    const chunk = Math.max(1, Math.floor(length / bars));
    const levels = Array.from({ length: bars }, (_, b) => {
      let sum = 0;
      for (let i = b * chunk; i < Math.min(length, (b + 1) * chunk); i++) sum += mono[i] * mono[i];
      return dbLevel(Math.sqrt(sum / chunk));
    });
    const waveform: WaveformBin[] = [];
    addWaveformSamples(waveform, mono, Math.max(1, length / WAVEFORM_BINS));
    return { wav: encodeWav(mono, audio.sampleRate), levels, waveform: waveformPath(waveform) };
  } catch {
    throw new Error("Couldn't read that file. Try a WAV or MP3 recording.");
  } finally {
    void ctx.close();
  }
}
