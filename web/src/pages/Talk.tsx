import { useCallback, useEffect, useRef, useState } from 'react';
import { midSentence } from '../lib/format';
import { Link, useNavigate } from 'react-router-dom';
import { api, type AppSession, type ClipResponse, type VoiceSession } from '../lib/api';
import { VoiceCall } from '../lib/agora';
import { playAudio } from '../lib/audio';
import { useLive, useLiveEvent } from '../lib/events';
import type { Analysis, Asset, LiveEvent, Mode, Purpose } from '../lib/types';
import { ChevronLeftIcon, CloseIcon, MicIcon, MicOffIcon, SoundIcon, WaveIcon } from '../components/Icons';
import { ListenPanel } from '../components/ListenPanel';
import { ResultCard } from '../components/ResultCard';
import { ConfirmSheet } from '../components/ConfirmSheet';
import './app.css';
import './talk.css';

type Status = 'connecting' | 'live' | 'error';
type Capture = { asset: Asset; mode: Mode; purpose: Purpose };

const SUGGESTIONS = ['"Check pump P-14"', '"Listen to it"', '"Add a new machine"', '"What did you find?"'];

export default function Talk() {
  const navigate = useNavigate();
  const { live } = useLive();
  const [status, setStatus] = useState<Status>('connecting');
  const [error, setError] = useState('');
  const [session, setSession] = useState<VoiceSession | AppSession | null>(null);
  const [muted, setMuted] = useState(false);
  const [needsTap, setNeedsTap] = useState(false);
  const [capture, setCapture] = useState<Capture | null>(null);
  const [picking, setPicking] = useState(false);
  const [result, setResult] = useState<Analysis | null>(null);
  const [typed, setTyped] = useState('');
  const [sending, setSending] = useState(false);
  const callRef = useRef<VoiceCall | null>(null);
  const idRef = useRef<string | null>(null);
  const orbRef = useRef<HTMLDivElement>(null);
  const micRef = useRef<HTMLSpanElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const voice = session?.kind === 'voice';

  const hangUp = useCallback(async () => {
    const call = callRef.current;
    const id = idRef.current;
    callRef.current = null;
    idRef.current = null;
    await call?.leave();
    if (id) await api.endSession(id);
  }, []);

  useEffect(() => {
    let cancelled = false;
    // Deferred so React StrictMode's dev-only mount/unmount/mount doesn't start two agents.
    const timer = window.setTimeout(async () => {
      try {
        const s = await api.startSession('voice');
        idRef.current = s.session;
        if (s.kind === 'voice') {
          const call = new VoiceCall(s, () => setNeedsTap(true));
          callRef.current = call;
          await call.join();
        }
        if (cancelled) return;
        setSession(s);
        setStatus('live');
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : 'Could not connect.');
        setStatus('error');
        void hangUp();
      }
    }, 0);
    const onUnload = () => void hangUp();
    window.addEventListener('pagehide', onUnload);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      window.removeEventListener('pagehide', onUnload);
      void hangUp();
    };
  }, [hangUp]);

  // Orb follows EarShot's real voice level; the meter follows the worker's mic.
  useEffect(() => {
    let frame = 0;
    const tick = () => {
      const call = callRef.current;
      orbRef.current?.style.setProperty('--level', String(Math.min(1, (call?.agentLevel() ?? 0) * 1.6)));
      micRef.current?.style.setProperty('--mic', String(Math.min(1, (call?.micLevel() ?? 0) * 2)));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);

  const onEvent = useCallback(
    (e: LiveEvent) => {
      if (!session) return;
      if (e.kind === 'capture_start' && e.session === session.session) {
        const asset = live?.assets.find((a) => a.id === e.asset_id);
        if (asset) setCapture({ asset, mode: e.mode, purpose: e.purpose });
      }
      if (e.kind === 'play_audio' && e.target === 'session' && e.session === session.session) void playAudio(e.url);
    },
    [session, live],
  );
  useLiveEvent(onEvent);

  const lines = live?.transcript.filter((l) => l.session === session?.session) ?? [];
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [lines.length]);

  const pending = live?.confirmations.find(
    (c) => c.session === session?.session && (c.status === 'pending' || c.status === 'second_approval'),
  );
  const focusId = session ? live?.sessions[session.session]?.focus : undefined;
  const focusAsset = live?.assets.find((a) => a.id === focusId);

  const openListen = () => {
    if (focusAsset) setCapture({ asset: focusAsset, mode: focusAsset.modes[0] ?? 'continuous', purpose: focusAsset.state === 'unset' ? 'enroll' : 'check' });
    else setPicking(true);
  };

  const onClip = (res: ClipResponse) => {
    setCapture(null);
    if (res.result.band || res.result.ok === false) setResult(res.result);
  };

  const send = async () => {
    if (!session || !typed.trim()) return;
    setSending(true);
    const text = typed.trim();
    setTyped('');
    try {
      await api.chat(session.session, text); // the reply is voiced via a play_audio event
    } finally {
      setSending(false);
    }
  };

  const toggleMute = async () => {
    const next = !muted;
    await callRef.current?.setMuted(next);
    setMuted(next);
  };

  const hint =
    status === 'connecting'
      ? 'Connecting to EarShot…'
      : status === 'error'
        ? "EarShot can't connect right now."
        : !voice
          ? 'Type to EarShot (voice is off in demo mode)'
          : muted
            ? 'Your mic is muted'
            : 'Talk any time · you can interrupt';

  return (
    <div className="phone talk">
      <header className="talk-head">
        <Link to="/app" className="icon-btn" aria-label="Back" onClick={() => void hangUp()}>
          <ChevronLeftIcon />
        </Link>
        <div className="talk-title">
          <h1>Talking to EarShot</h1>
          {focusAsset && <p>Checking {midSentence(focusAsset.name)}</p>}
        </div>
        {status === 'live' && (
          <span className="pill pill-ok">
            <span className="dot" /> Live
          </span>
        )}
      </header>

      <div className="talk-orb-wrap">
        <div ref={orbRef} className={`talk-orb ${status}`} aria-hidden="true">
          <WaveIcon size={36} />
        </div>
        <p className={`talk-hint ${status === 'error' ? 'is-error' : ''}`} role="status">
          {hint}
        </p>
        {voice && status === 'live' && !muted && (
          <p className="mic-meter">
            Your mic <span ref={micRef} className="mic-bar" aria-hidden="true" />
          </p>
        )}
        {status === 'error' && error && <p className="talk-detail">{error}</p>}
        {needsTap && (
          <button className="btn btn-voice" onClick={() => { callRef.current?.resumeAudio(); setNeedsTap(false); }}>
            Tap to hear EarShot
          </button>
        )}
        {status === 'error' && (
          <button className="btn" onClick={() => window.location.reload()}>
            Try again
          </button>
        )}
      </div>

      <section className="talk-transcript" aria-live="polite">
        {lines.map((l) => (
          <p key={l.id} className={`bubble-line ${l.who}`}>
            {l.text}
          </p>
        ))}
        <div ref={bottomRef} />
      </section>

      <footer className="talk-foot">
        {voice ? (
          <>
            <p className="talk-cansay-label">You can say</p>
            <div className="talk-chips">
              {SUGGESTIONS.map((s) => (
                <span key={s} className="chip">{s}</span>
              ))}
            </div>
          </>
        ) : (
          status === 'live' && (
            <form className="talk-type" onSubmit={(e) => { e.preventDefault(); void send(); }}>
              <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="e.g. Check pump P-14" aria-label="Message to EarShot" />
              <button className="btn btn-voice" disabled={sending || !typed.trim()}>Send</button>
            </form>
          )
        )}
        <div className="talk-controls">
          <button className="round-btn" onClick={toggleMute} disabled={!voice || status !== 'live'} aria-pressed={muted}>
            <span className="round">{muted ? <MicOffIcon /> : <MicIcon />}</span>
            <span>{muted ? 'Unmute' : 'Mute'}</span>
          </button>
          <button className="listen-btn" onClick={openListen} disabled={status !== 'live'}>
            <SoundIcon size={28} />
            <span>Listen to machine</span>
          </button>
          <button className="round-btn" onClick={async () => { await hangUp(); navigate('/app'); }}>
            <span className="round round-end"><CloseIcon /></span>
            <span>End</span>
          </button>
        </div>
      </footer>

      {picking && live && (
        <div className="overlay" onClick={() => setPicking(false)}>
          <div className="sheet" onClick={(e) => e.stopPropagation()}>
            <div className="sheet-grip" />
            <h2>Which machine?</h2>
            <div className="pick-list">
              {live.assets.map((a) => (
                <button key={a.id} className="pick" onClick={() => { setPicking(false); setCapture({ asset: a, mode: a.modes[0] ?? 'continuous', purpose: a.state === 'unset' ? 'enroll' : 'check' }); }}>
                  <span>{a.name}</span>
                  <span className="muted small">{a.state === 'unset' ? 'Record its healthy sound' : a.label}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {result && !capture && (
        <div className="overlay overlay-top" onClick={() => setResult(null)}>
          <div className="overlay-card" onClick={(e) => e.stopPropagation()}>
            <ResultCard analysis={result} facts={live?.facts[result.asset_id]} />
            <button className="btn" onClick={() => setResult(null)}>Close</button>
          </div>
        </div>
      )}

      {pending && !capture && (
        <div className="overlay overlay-bottom">
          <ConfirmSheet confirmation={pending} voice={voice} />
        </div>
      )}

      {capture && session && (
        <ListenPanel
          key={`${capture.asset.id}:${capture.mode}:${capture.purpose}`}
          asset={capture.asset}
          mode={capture.mode}
          purpose={capture.purpose}
          session={session.session}
          requireStart
          onMute={(m) => callRef.current?.setMuted(m || muted)}
          onDone={onClip}
          onCancel={() => setCapture(null)}
        />
      )}
    </div>
  );
}
