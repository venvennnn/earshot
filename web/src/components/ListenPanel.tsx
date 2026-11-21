import { useEffect, useRef, useState } from 'react';
import { stopAudio } from '../lib/audio';
import { api, type ClipResponse } from '../lib/api';
import { CLIP_SECONDS, QUIET_LEVEL, Recorder, WAVEFORM_BINS, fileToWav, primeRecordingAudio } from '../lib/capture';
import type { Asset, Mode, Purpose } from '../lib/types';

const MODES: { id: Mode; label: string }[] = [
  { id: 'continuous', label: 'Running machine' },
  { id: 'tap', label: 'Tapping parts' },
  { id: 'alarm', label: 'Alarm beeps' },
];

const TIPS: Record<Mode, string> = {
  continuous: "Hold the phone about a hand's width from the machine, near where it sounds loudest.",
  tap: 'Put the phone near the parts and tap each one once, firmly, a second or two apart.',
  alarm: 'Hold the phone close to the beeping box and wait for the whole pattern.',
};

interface Props {
  asset: Asset;
  mode?: Mode;
  purpose?: Purpose;
  session?: string;
  part?: number;
  playFile?: File | null; // "Enroll from this speaker": play this file aloud while recording
  onSpeakerMute?: (muted: boolean) => void;
  onMute?: (muted: boolean) => Promise<void> | void;
  onDone: (res: ClipResponse) => void;
  onCancel: () => void;
}

type Phase = 'starting' | 'preparing' | 'recording' | 'working' | 'error';

export function ListenPanel({ asset, mode: initialMode = 'continuous', purpose = 'check', session, part, playFile, onSpeakerMute, onMute, onDone, onCancel }: Props) {
  const [mode, setMode] = useState<Mode>(initialMode);
  const tapReference = mode === 'tap' && purpose === 'enroll';
  const clipSeconds = tapReference ? 4 : CLIP_SECONDS;
  const partWord = asset.type.includes('wheel') ? 'wheel' : 'part';
  const [phase, setPhase] = useState<Phase>('starting');
  const [left, setLeft] = useState(clipSeconds);
  const [error, setError] = useState('');
  const [quiet, setQuiet] = useState(false);
  const waveformRef = useRef<SVGPathElement>(null);
  const [attempt, setAttempt] = useState(0);
  const [file, setFile] = useState<File | null>(null); // "Use a recording instead": skips the microphone
  const [fileShown, setFileShown] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  useEffect(() => {
    const abort = new AbortController();
    const recorder = new Recorder();
    let player: HTMLAudioElement | null = null;
    let mutedMic = false;
    let frame = 0;
    let recentLoud = 0;
    const wave = waveformRef.current;
    wave?.removeAttribute('d');

    const draw = () => {
      const level = recorder.level();
      recentLoud = recentLoud * 0.97 + level * 0.03;
      wave?.setAttribute('d', recorder.waveformPath());
      frame = requestAnimationFrame(draw);
    };
    const qualityTimer = window.setInterval(() => !file && setQuiet(mode === 'continuous' && recentLoud < QUIET_LEVEL), 800);

    const timer = window.setTimeout(async () => {
      if (file) {
        try {
          setPhase('working');
          const { wav, levels: fileLevels, waveform } = await fileToWav(file);
          if (abort.signal.aborted) return;
          wave?.setAttribute('d', waveform);
          setQuiet(Math.max(...fileLevels) < QUIET_LEVEL);
          setFileShown(true);
          const result = await api.uploadClip(wav, { asset_id: asset.id, mode, purpose, session, part });
          if (!abort.signal.aborted) doneRef.current(result);
        } catch (e) {
          if (abort.signal.aborted) return;
          setError(e instanceof Error ? e.message : 'Could not use that file.');
          setPhase('error');
        }
        return;
      }
      try {
        setPhase('starting');
        await onMute?.(true);
        if (abort.signal.aborted) return;
        mutedMic = true;
        await recorder.open(abort.signal);
        if (abort.signal.aborted) return;
        setPhase('preparing');
        await new Promise((resolve) => window.setTimeout(resolve, 1600));
        if (abort.signal.aborted) return;
        stopAudio();
        onSpeakerMute?.(true);
        frame = requestAnimationFrame(draw);
        if (playFile) {
          player = new Audio(URL.createObjectURL(playFile));
          player.loop = true;
          void player.play();
        }
        const wav = await recorder.record(clipSeconds, (secondsLeft) => {
          setPhase('recording');
          setLeft(secondsLeft);
        }, abort.signal);
        player?.pause();
        cancelAnimationFrame(frame);
        recorder.close();
        onSpeakerMute?.(false);
        if (!wav || abort.signal.aborted) return;
        wave?.setAttribute('d', recorder.waveformPath());
        setPhase('working');
        const result = await api.uploadClip(wav, { asset_id: asset.id, mode, purpose, session, part });
        if (!abort.signal.aborted) doneRef.current(result);
      } catch (e) {
        if (abort.signal.aborted) return;
        player?.pause();
        cancelAnimationFrame(frame);
        recorder.close();
        setError(e instanceof DOMException && e.name === 'NotAllowedError'
          ? 'Microphone access was denied. Allow it in your browser settings and try again.'
          : e instanceof Error ? e.message : 'Could not use the microphone.');
        setPhase('error');
      } finally {
        if (!abort.signal.aborted) {
          onSpeakerMute?.(false);
          if (mutedMic) await onMute?.(false);
        }
      }
    }, 0); // deferred so React StrictMode's double mount doesn't open the mic twice
    return () => {
      abort.abort();
      window.clearTimeout(timer);
      window.clearInterval(qualityTimer);
      cancelAnimationFrame(frame);
      player?.pause();
      recorder.close();
      onSpeakerMute?.(false);
      void onMute?.(false);
    };
    // Restart when the mode or the chosen file changes; other props are fixed for one recording.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, file, clipSeconds, attempt]);

  const retry = () => {
    primeRecordingAudio();
    setError('');
    setFile(null);
    setFileShown(false);
    setAttempt((n) => n + 1);
    setPhase('starting');
  };

  const ring = 2 * Math.PI * 88;
  const progress = phase === 'recording' ? left / clipSeconds : phase === 'working' ? 0 : 1;

  return (
    <div className="listen" role="dialog" aria-label="Listening to the machine">
      <span className="listen-pill">
        <span className="dot" />{' '}
        {purpose === 'enroll' ? 'Recording the healthy sound' : purpose === 'verify' ? 'Checking the repair' : 'Listening to the machine'}
      </span>
      <h1 className="listen-asset">{asset.name}</h1>
      <p className="listen-sub">
        {phase === 'working'
          ? file ? `Listening to ${file.name}…` : 'Working out what it heard…'
          : phase === 'starting' ? 'Opening the microphone…'
            : phase === 'preparing' ? (tapReference ? `Get close to a good ${partWord}. Wait for the beep.` : 'Get close. Recording starts after the beep.')
              : phase === 'error' ? 'Recording did not complete.'
                : tapReference ? `Tap the good ${partWord} once after the first beep.`
                  : mode === 'tap' ? `After the beep, tap each ${partWord} once.`
                    : 'Hold still and stay quiet until the beep'}
      </p>

      <div className="listen-ring">
        <svg viewBox="0 0 200 200" aria-hidden="true">
          <circle cx="100" cy="100" r="88" className="ring-bg" />
          <circle cx="100" cy="100" r="88" className="ring-fg" strokeDasharray={ring} strokeDashoffset={ring * (1 - progress)} />
        </svg>
        <div className="listen-count">
          {phase === 'working' ? <span className="spinner" aria-label="Working" /> : <strong>{phase === 'recording' ? left : clipSeconds}</strong>}
          <span>{phase === 'working' ? '' : 'seconds left'}</span>
        </div>
      </div>

      <figure className="listen-waveform">
        <figcaption>{file ? 'Recording waveform' : 'Microphone waveform'}</figcaption>
        <svg viewBox={`0 0 ${WAVEFORM_BINS} 64`} preserveAspectRatio="none" aria-hidden="true">
          <line x1="0" x2={WAVEFORM_BINS} y1="32" y2="32" />
          <path ref={waveformRef} />
        </svg>
      </figure>
      {fileShown && phase === 'working' && (
        <p className={`listen-check ${quiet ? 'warn' : 'good'}`}>
          {quiet ? 'This recording is very quiet' : `Using ${file?.name}: this is the sound EarShot is analysing`}
        </p>
      )}
      {phase === 'recording' && (
        <p className={`listen-check ${quiet ? 'warn' : 'good'}`}>
          {mode === 'tap' ? 'Recording taps' : quiet ? 'Too quiet, move closer' : 'Good, the sound is coming through clearly'}
        </p>
      )}
      {phase === 'error' && <p className="listen-check warn">{error}</p>}

      <div className="listen-tip">
        <span className="tip-icon" aria-hidden="true">◉▯</span>
        <p>{playFile ? 'Playing your file through this speaker while recording.' : tapReference ? 'Let the ring fade before moving the phone.' : TIPS[mode]}</p>
      </div>

      {purpose === 'check' && (
        <>
          <p className="listen-q">What are you listening to?</p>
          <div className="segmented" role="radiogroup">
            {MODES.map((m) => (
              <button key={m.id} role="radio" aria-checked={mode === m.id} className={mode === m.id ? 'on' : ''}
                disabled={phase === 'working'} onClick={() => setMode(m.id)}>
                {m.label}
              </button>
            ))}
          </div>
        </>
      )}

      {phase === 'error' && (
        <button className="btn btn-sound" onClick={retry}>Retry microphone</button>
      )}

      {phase !== 'working' && (
        <>
          <button className="link-file" onClick={() => fileInput.current?.click()}>
            Use a recording instead
          </button>
          <input ref={fileInput} type="file" accept="audio/*" hidden
            onChange={(e) => { const f = e.target.files?.[0]; if (f) { setError(''); setFile(f); } }} />
        </>
      )}

      <button className="btn listen-stop" onClick={onCancel} disabled={phase === 'working'}>
        {phase === 'error' ? 'Close' : 'Stop listening'}
      </button>
    </div>
  );
}
