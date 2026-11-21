import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { createVoiceSession, endVoiceSession } from '../lib/api';
import { VoiceCall, type Line } from '../lib/agora';
import { ChevronLeftIcon, CloseIcon, MicIcon, MicOffIcon, SoundIcon, WaveIcon } from '../components/Icons';
import './app.css';
import './talk.css';

type Status = 'connecting' | 'live' | 'error';

const SUGGESTIONS = ['"Check pump P-14"', '"Listen to it"', '"What did you find?"'];

export default function Talk() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<Status>('connecting');
  const [error, setError] = useState('');
  const [lines, setLines] = useState<Line[]>([]);
  const [speaking, setSpeaking] = useState(false);
  const [muted, setMuted] = useState(false);
  const [needsTap, setNeedsTap] = useState(false);
  const callRef = useRef<VoiceCall | null>(null);
  const channelRef = useRef<string | null>(null);
  const orbRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const hangUp = useCallback(async () => {
    const call = callRef.current;
    const channel = channelRef.current;
    callRef.current = null;
    channelRef.current = null;
    await call?.leave();
    if (channel) await endVoiceSession(channel);
  }, []);

  useEffect(() => {
    let cancelled = false;
    // Deferred so React StrictMode's dev-only mount/unmount/mount doesn't start two agents.
    const timer = window.setTimeout(async () => {
      try {
        const session = await createVoiceSession();
        channelRef.current = session.channel;
        const call = new VoiceCall(session, {
          onTranscript: setLines,
          onAgentSpeaking: setSpeaking,
          onMetric: () => undefined, // latency metrics are shown on the dashboard (Phase 6)
          onAutoplayBlocked: () => setNeedsTap(true),
        });
        callRef.current = call;
        await call.join();
        if (cancelled) return;
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

  // Orb pulses with the agent's actual voice level.
  useEffect(() => {
    let frame = 0;
    const tick = () => {
      const level = callRef.current?.agentLevel() ?? 0;
      orbRef.current?.style.setProperty('--level', String(Math.min(1, level * 1.6)));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [lines]);

  const toggleMute = async () => {
    const next = !muted;
    await callRef.current?.setMuted(next);
    setMuted(next);
  };

  const end = async () => {
    await hangUp();
    navigate('/app');
  };

  const hint =
    status === 'connecting'
      ? 'Connecting to EarShot…'
      : status === 'error'
        ? "EarShot can't connect right now."
        : speaking
          ? 'EarShot is speaking · you can interrupt'
          : muted
            ? 'Your mic is muted'
            : 'Listening to you…';

  return (
    <div className="phone talk">
      <header className="talk-head">
        <Link to="/app" className="icon-btn" aria-label="Back" onClick={() => void hangUp()}>
          <ChevronLeftIcon />
        </Link>
        <div className="talk-title">
          <h1>Talking to EarShot</h1>
        </div>
        {status === 'live' && (
          <span className="pill pill-ok">
            <span className="dot" /> Live
          </span>
        )}
      </header>

      <div className="talk-orb-wrap">
        <div ref={orbRef} className={`talk-orb ${speaking ? 'is-speaking' : ''} ${status}`} aria-hidden="true">
          <WaveIcon size={40} />
        </div>
        <p className={`talk-hint ${status === 'error' ? 'is-error' : ''}`} role="status">
          {hint}
        </p>
        {status === 'error' && error && <p className="talk-detail">{error}</p>}
        {needsTap && (
          <button
            className="btn btn-voice"
            onClick={() => {
              callRef.current?.resumeAudio();
              setNeedsTap(false);
            }}
          >
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
          <p key={l.id} className={`bubble-line ${l.who} ${l.final ? '' : 'partial'}`}>
            {l.text}
          </p>
        ))}
        <div ref={bottomRef} />
      </section>

      <footer className="talk-foot">
        <p className="talk-cansay-label">You can say</p>
        <div className="talk-chips">
          {SUGGESTIONS.map((s) => (
            <span key={s} className="chip">
              {s}
            </span>
          ))}
        </div>
        <div className="talk-controls">
          <button className="round-btn" onClick={toggleMute} disabled={status !== 'live'} aria-pressed={muted}>
            <span className="round">{muted ? <MicOffIcon /> : <MicIcon />}</span>
            <span>{muted ? 'Unmute' : 'Mute'}</span>
          </button>
          <button className="listen-btn" disabled title="Machine listening arrives in the sound phase">
            <SoundIcon size={28} />
            <span>Listen to machine</span>
          </button>
          <button className="round-btn" onClick={end}>
            <span className="round round-end">
              <CloseIcon />
            </span>
            <span>End</span>
          </button>
        </div>
      </footer>
    </div>
  );
}
