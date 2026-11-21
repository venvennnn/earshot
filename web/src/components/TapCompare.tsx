import { useEffect, useRef, useState } from 'react';
import { mediaUrl } from '../lib/api';
import { stopAudio } from '../lib/audio';
import type { Asset, LiveState, TapBatch, TapPart } from '../lib/types';

type Hear = 'ab' | 'a' | 'b';

type Wave = { peaks: number[]; duration: number };

const cache = new Map<string, Wave>();

/** A ring picture from the 24-point decay envelope, used until the real clip is drawn. */
export function peaksFromEnvelope(envelope: number[], buckets = 480): number[] {
  if (envelope.length === 0) return [];
  const out: number[] = [];
  for (let i = 0; i < buckets; i++) {
    const t = i / (buckets - 1);
    const pos = t * (envelope.length - 1);
    const i0 = Math.floor(pos);
    const frac = pos - i0;
    const env = (envelope[i0] ?? 0) * (1 - frac) + (envelope[Math.min(envelope.length - 1, i0 + 1)] ?? 0) * frac;
    const ring = Math.abs(Math.sin(t * Math.PI * 38));
    out.push(Math.min(1, env * (0.22 + 0.78 * ring)));
  }
  return out;
}

async function waveFor(url: string): Promise<Wave | null> {
  const hit = cache.get(url);
  if (hit) return hit;
  try {
    const res = await fetch(mediaUrl(url));
    if (!res.ok) return null;
    const bytes = await res.arrayBuffer();
    const ctx = new AudioContext();
    const audio = await ctx.decodeAudioData(bytes.slice(0));
    await ctx.close();
    const channel = audio.getChannelData(0);
    const buckets = 480;
    const size = Math.max(1, Math.floor(channel.length / buckets));
    const peaks: number[] = [];
    for (let i = 0; i < buckets; i++) {
      let max = 0;
      const start = i * size;
      for (let j = 0; j < size; j += 2) max = Math.max(max, Math.abs(channel[start + j] || 0));
      peaks.push(max);
    }
    const top = Math.max(...peaks, 0.001);
    const wave = { peaks: peaks.map((p) => p / top), duration: audio.duration };
    cache.set(url, wave);
    return wave;
  } catch {
    return null;
  }
}

function wavePath(peaks: number[], width: number, height: number): string {
  if (peaks.length < 2) return '';
  const mid = height / 2;
  const amp = height * 0.44;
  const point = (i: number, sign: number) => {
    const x = (i / (peaks.length - 1)) * width;
    const y = mid - sign * peaks[i] * amp;
    return `${x.toFixed(1)} ${y.toFixed(1)}`;
  };
  let d = `M${point(0, 1)}`;
  for (let i = 1; i < peaks.length; i++) d += ` L${point(i, 1)}`;
  for (let i = peaks.length - 1; i >= 0; i--) d += ` L${point(i, -1)}`;
  return `${d} Z`;
}

function clock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) seconds = 0;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 1000);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
}

function decayLabel(ms: number): string {
  return `${(ms / 1000).toFixed(2)} s`;
}

function WaveChart({
  mark, title, sub, tone, peaks, duration, decay, active, progress,
}: {
  mark: string;
  title: string;
  sub: string;
  tone: 'good' | 'dull';
  peaks: number[];
  duration: number;
  decay?: number;
  active: boolean;
  progress: number;
}) {
  const width = 1000;
  const height = 150;
  const ticks = 5;
  return (
    <article className={`compare-chart ${tone} ${active ? 'on' : ''}`}>
      <header>
        <span className={`compare-mark ${tone}`}>{mark}</span>
        <div>
          <strong>{title}</strong>
          <span>{sub}</span>
        </div>
        {decay != null && <em>Decay (20 dB): {decayLabel(decay)}</em>}
      </header>
      <div className="compare-plot">
        <div className="compare-yaxis" aria-hidden="true">
          <span>1.0</span><span>0.5</span><span>0</span><span>-0.5</span><span>-1.0</span>
        </div>
        <div className="compare-canvas">
          <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label={title}>
            {[0.25, 0.5, 0.75].map((g) => (
              <line key={g} x1="0" x2={width} y1={height * g} y2={height * g} className="compare-grid" />
            ))}
            <line x1="0" x2={width} y1={height / 2} y2={height / 2} className="compare-zero" />
            <path d={wavePath(peaks, width, height)} className={`compare-wave ${tone}`} />
            {active && progress > 0 && <line className="compare-playhead" x1={progress * width} x2={progress * width} y1="0" y2={height} />}
          </svg>
          <div className="compare-xaxis">
            {Array.from({ length: ticks }, (_, i) => (
              <span key={i}>{(duration * i / (ticks - 1)).toFixed(3)}</span>
            ))}
          </div>
        </div>
      </div>
    </article>
  );
}

function shownPart(batch: TapBatch, part: number | null): TapPart | undefined {
  if (part != null) return batch.parts.find((p) => p.n === part);
  return [...batch.parts].reverse().find((p) => p.result === 'dull') ?? batch.parts[batch.parts.length - 1];
}

export function TapCompare({ live, asset, part, onPart }: {
  live: LiveState;
  asset: Asset;
  part: number | null;
  onPart: (n: number) => void;
}) {
  const batch = live.tap_batches[asset.id];
  const word = asset.type.includes('wheel') ? 'wheel' : 'part';
  const total = batch?.total || asset.parts || 0;
  const focus = batch ? shownPart(batch, part) : undefined;
  const highlighted = part ?? focus?.n ?? null;

  const [good, setGood] = useState<Wave | null>(null);
  const [tap, setTap] = useState<Wave | null>(null);
  const [hear, setHear] = useState<Hear>('ab');
  const [playing, setPlaying] = useState(false);
  const [stage, setStage] = useState<'a' | 'b'>('a');
  const [time, setTime] = useState(0);
  const [volume, setVolume] = useState(0.85);
  const [rate, setRate] = useState(1);
  const audio = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    let cancel = false;
    audio.current?.pause();
    audio.current = null;
    setPlaying(false);
    setTime(0);
    setGood(null);
    setTap(null);
    if (batch?.good_url) {
      void waveFor(batch.good_url).then((wave) => { if (!cancel) setGood(wave); });
    }
    if (focus?.clip_url) {
      void waveFor(focus.clip_url).then((wave) => { if (!cancel) setTap(wave); });
    }
    return () => { cancel = true; };
  }, [batch?.good_url, focus?.clip_url]);

  useEffect(() => () => { audio.current?.pause(); }, []);

  if (!batch || total < 2 || batch.parts.length === 0) return null;

  const goodPeaks = good?.peaks ?? peaksFromEnvelope(batch.good_envelope);
  const tapPeaks = tap?.peaks ?? (focus ? peaksFromEnvelope(focus.envelope) : []);
  const goodDuration = good?.duration || Math.max(0.5, (batch.good_decay_ms / 1000) * 3);
  const tapDuration = tap?.duration || (focus ? Math.max(0.4, (focus.decay_ms / 1000) * 3) : goodDuration);
  const playingB = playing && (hear === 'b' || (hear === 'ab' && stage === 'b'));
  const playingA = playing && !playingB;

  const stop = () => {
    audio.current?.pause();
    audio.current = null;
    setPlaying(false);
    setTime(0);
  };

  const start = (url: string | undefined, next?: () => void) => {
    if (!url) {
      next?.();
      return;
    }
    stopAudio();
    audio.current?.pause();
    const el = new Audio(mediaUrl(url));
    el.volume = volume;
    el.playbackRate = rate;
    audio.current = el;
    el.ontimeupdate = () => setTime(el.currentTime);
    el.onended = () => {
      if (next) next();
      else setPlaying(false);
    };
    el.onerror = () => setPlaying(false);
    void el.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
  };

  const play = (mode: Hear) => {
    setHear(mode);
    setTime(0);
    if (mode === 'b') {
      setStage('b');
      start(focus?.clip_url);
      return;
    }
    setStage('a');
    if (mode === 'ab') start(batch.good_url, () => { setStage('b'); setTime(0); start(focus?.clip_url); });
    else start(batch.good_url);
  };

  const toggle = () => {
    const el = audio.current;
    if (el && !el.paused) {
      el.pause();
      setPlaying(false);
      return;
    }
    if (el && el.currentTime > 0 && el.currentTime < (el.duration || Infinity) - 0.05) {
      el.volume = volume;
      el.playbackRate = rate;
      void el.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
      return;
    }
    play(hear);
  };

  const nudge = (delta: number) => {
    const el = audio.current;
    if (!el) return;
    el.currentTime = Math.max(0, Math.min((el.duration || 0) - 0.01, el.currentTime + delta));
    setTime(el.currentTime);
  };

  const activeDuration = playingB ? tapDuration : goodDuration;
  const shownTime = playing ? time : 0;

  return (
    <section className="db-card compare">
      <header className="compare-head">
        <div>
          <h2>Compare {word} taps</h2>
          <p>{asset.name} · {asset.line || live.pack?.line} · {live.pack?.shift}</p>
        </div>
      </header>

      <WaveChart
        mark="A" tone="good" title="Healthy reference" sub={`Known good ${word}`}
        peaks={goodPeaks} duration={goodDuration} decay={batch.good_decay_ms}
        active={playingA} progress={playingA ? shownTime / goodDuration : 0}
      />
      <WaveChart
        mark="B" tone="dull"
        title={focus ? `${word[0].toUpperCase()}${word.slice(1)} ${focus.n} tap` : `${word[0].toUpperCase()}${word.slice(1)} ${highlighted ?? ''} tap`}
        sub={focus ? `Current inspection (${asset.name})` : 'Not tapped yet'}
        peaks={tapPeaks} duration={tapDuration} decay={focus?.decay_ms}
        active={playingB} progress={playingB ? shownTime / tapDuration : 0}
      />

      <div className="compare-transport">
        <div className="compare-modes" role="group" aria-label="Which ring to play">
          {(['ab', 'a', 'b'] as Hear[]).map((mode) => (
            <button key={mode} type="button" className={hear === mode ? 'on' : ''} onClick={() => play(mode)}>
              {mode === 'ab' ? 'A / B' : mode === 'a' ? 'A only' : 'B only'}
            </button>
          ))}
        </div>
        <label className="compare-volume">
          <span aria-hidden="true">♪</span>
          <input type="range" min={0} max={1} step={0.05} value={volume} aria-label="Volume"
            onChange={(e) => {
              const next = Number(e.target.value);
              setVolume(next);
              if (audio.current) audio.current.volume = next;
            }} />
        </label>
        <div className="compare-play">
          <button type="button" aria-label="Back a little" onClick={() => nudge(-0.25)}>‹‹</button>
          <button type="button" className="compare-go" aria-label={playing ? 'Pause' : 'Play'} onClick={toggle}>{playing ? '❚❚' : '▶'}</button>
          <button type="button" aria-label="Forward a little" onClick={() => nudge(0.25)}>››</button>
        </div>
        <span className="compare-clock">{clock(shownTime)} / {clock(activeDuration)}</span>
        <label className="compare-rate">
          <span className="sr-only">Speed</span>
          <select value={rate} aria-label="Playback speed" onChange={(e) => {
            const next = Number(e.target.value);
            setRate(next);
            if (audio.current) audio.current.playbackRate = next;
          }}>
            <option value={0.5}>0.5×</option>
            <option value={1}>1.0×</option>
            <option value={1.5}>1.5×</option>
            <option value={2}>2.0×</option>
          </select>
        </label>
      </div>

      <div className="compare-inspect">
        <div>
          <strong>Current inspection</strong>
          <span>{total} {word} positions</span>
        </div>
        <ol className="compare-steps">
          {Array.from({ length: total }, (_, i) => i + 1).map((n) => {
            const hit = batch.parts.find((p) => p.n === n);
            const cls = [hit?.result, highlighted === n ? 'sel' : ''].filter(Boolean).join(' ');
            return (
              <li key={n}>
                <button type="button" className={cls} aria-label={`${word} ${n}${hit ? `, ${hit.result}` : ', not tapped'}`}
                  onClick={() => { stop(); onPart(n); }}>
                  {hit?.result === 'good' ? '✓' : n}
                </button>
              </li>
            );
          })}
        </ol>
        {focus?.result === 'dull' && (
          <p className="compare-flag">
            <strong>Repeat tap pending</strong>
            <span>{word[0].toUpperCase()}{word.slice(1)} {focus.n} · Dull ring · Recheck</span>
          </p>
        )}
      </div>
    </section>
  );
}
