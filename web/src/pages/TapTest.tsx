import { useCallback, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ListenPanel } from '../components/ListenPanel';
import { ConfirmSheet } from '../components/ConfirmSheet';
import { TopBar } from '../components/Bits';
import { useLive, useLiveEvent } from '../lib/events';
import { useAppSession } from '../lib/useAppSession';
import { useVoiceCall } from '../lib/useVoiceCall';
import { MicIcon } from '../components/Icons';
import { api, type ClipResponse, type TurnReply } from '../lib/api';
import { playAudio } from '../lib/audio';
import type { TapBatch, TapPart } from '../lib/types';
import './app.css';
import './talk.css';

function Ring({ envelope, tone }: { envelope: number[]; tone: 'good' | 'dull' }) {
  return (
    <span className={`ring-bars ${tone}`} aria-hidden="true">
      {envelope.map((v, i) => (
        <span key={i} style={{ height: `${Math.max(6, v * 100)}%` }} />
      ))}
    </span>
  );
}

function HearGoodVsThis({ batch, part, word }: { batch: TapBatch; part: TapPart; word: string }) {
  const [playing, setPlaying] = useState(false);
  if (!batch.good_url || !part.clip_url) return null;
  const play = async () => {
    setPlaying(true);
    await playAudio(batch.good_url!);
    await playAudio(part.clip_url!);
    setPlaying(false);
  };
  return (
    <button className="btn" disabled={playing} onClick={play}>
      {playing ? 'Playing…' : `▶ Hear good ${word} vs ${word} ${part.n}`}
    </button>
  );
}

export default function TapTest() {
  const [params, setParams] = useSearchParams();
  const { live } = useLive();
  const appSession = useAppSession();
  const voice = useVoiceCall(); // optional live call: say "yes" or "finish the batch" while tapping
  const session = voice.session ?? appSession;
  const tapAssets = live?.assets.filter((a) => a.modes.includes('tap'));
  const asset = tapAssets?.find((a) => a.id === params.get('asset')) ?? tapAssets?.[0];
  const [recording, setRecording] = useState<{ purpose: 'check' | 'enroll'; part?: number } | null>(null);
  const [savedReference, setSavedReference] = useState<string | null>(null);
  const [said, setSaid] = useState('');
  const [finishing, setFinishing] = useState(false);
  const [error, setError] = useState('');
  const batch = asset ? live?.tap_batches[asset.id] : undefined;
  const pending = live?.confirmations.find((c) => c.session === session && (c.status === 'pending' || c.status === 'second_approval'));
  // During a call EarShot speaks through Agora; show its latest words here too.
  const lines = voice.session ? (live?.transcript ?? []).filter((l) => l.session === voice.session) : [];
  useLiveEvent(useCallback((e) => {
    if (e.kind === 'capture_start' && e.session === voice.session && e.mode === 'tap'
      && (e.purpose === 'enroll' || e.purpose === 'check') && live?.assets.some((a) => a.id === e.asset_id)) {
      setParams({ asset: e.asset_id });
      setRecording({ purpose: e.purpose });
    }
    if (e.kind === 'play_audio' && e.target === 'session' && e.session && e.session === voice.session) void playAudio(e.url);
  }, [live, setParams, voice.session]));

  const heard = (r: TurnReply) => {
    if (r.reply) setSaid(r.reply);
    if (r.audio_url) void playAudio(r.audio_url);
  };
  const finish = async () => {
    if (!session || !asset) return;
    setFinishing(true);
    setError('');
    try {
      heard(await api.finishTap(asset.id, session));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not finish the batch.');
    } finally {
      setFinishing(false);
    }
  };
  const done = (res: ClipResponse) => {
    setError('');
    if (recording?.purpose === 'enroll' && asset) {
      if (res.result.enrolled) setSavedReference(asset.id);
      else setError(res.result.tip ?? 'No reference saved. Tap a good part firmly near the phone and try again.');
    } else if (res.result.ok === false) {
      setError(res.result.tip ?? 'No usable taps were detected. Try again.');
    }
    setRecording(null);
    heard(res);
  };

  if (!asset) {
    return (
      <div className="phone">
        <main className="phone-body">
          <TopBar title="Tap test" />
          <p className="empty-note">No batch or wheel set is set up for tap testing in this pack.</p>
        </main>
      </div>
    );
  }

  const total = batch?.total ?? (asset.parts || 12);
  const parts = batch?.parts ?? [];
  const lastDull = [...parts].reverse().find((p) => p.result === 'dull');
  const shown = lastDull ?? parts[parts.length - 1]; // a dull part stays on top until it is re-tapped
  const good = parts.filter((p) => p.result === 'good').length;
  const dull = parts.filter((p) => p.result === 'dull').length;
  const next = parts.length < total ? Math.max(0, ...parts.map((p) => p.n)) + 1 : null;
  const needsReference = asset.state === 'unset' && !batch && savedReference !== asset.id;
  const word = asset.type.includes('wheel') ? 'wheel' : 'part';

  return (
    <div className="phone">
      <main className="phone-body">
        <TopBar title="Tap test" sub={asset.name} right={<span className="pill pill-sound"><span className="dot" /> Ready</span>} />
        {tapAssets && tapAssets.length > 1 && (
          <label className="field">
            <span>Wheelset or batch</span>
            <select value={asset.id} onChange={(e) => {
              setParams({ asset: e.target.value });
              setError('');
              setSaid('');
            }}>
              {tapAssets.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </label>
        )}
        <div className={`voice-strip ${voice.status}`}>
          {voice.status === 'live' ? (
            <>
              <span className="pill pill-ok"><span className="dot" /> Talking to EarShot</span>
              <span className="muted small">Say “Tap test {asset.name}” or “finish the batch”</span>
              {voice.needsTap && (
                <button className="btn btn-voice" onClick={voice.resume}>Tap to hear EarShot</button>
              )}
              <button className="btn" onClick={() => void voice.stop()}>End call</button>
            </>
          ) : (
            <>
              <button className="btn btn-voice" disabled={voice.status === 'connecting'} onClick={() => void voice.start()}>
                <MicIcon size={18} /> {voice.status === 'connecting' ? 'Connecting…' : 'Talk while testing'}
              </button>
              {voice.status === 'error' && <span className="error-text">{voice.error}</span>}
            </>
          )}
        </div>
        <p className="muted">
          Tap each {word} once near the phone. Good {word}s ring. A {word} with a crack sounds dull.
        </p>

        {needsReference ? (
          <section className="card">
            <h2 className="card-h">Record one good {word}</h2>
            <p className="muted">Place the phone near a good {word}. After the beep, tap it once and let it ring. EarShot uses that sound as the reference.</p>
            <button className="btn btn-sound btn-lg" disabled={!session} onClick={() => {
              setError('');
              setRecording({ purpose: 'enroll' });
            }}>Set up reference</button>
          </section>
        ) : (
          shown && batch && (
            <section className={`card tap-last ${shown.result}`}>
              <h2 className="card-h">
                {word[0].toUpperCase() + word.slice(1)} {shown.n} {shown.result === 'dull' ? 'sounds dull' : 'rings well'}
              </h2>
              {shown.result === 'dull' && <p>It may have a crack. Tap it once more to double-check.</p>}
              <div className="ring-compare">
                <span className="muted small">Good {word}</span>
                <Ring envelope={batch.good_envelope} tone="good" />
                <span className={`small ${shown.result === 'dull' ? 'text-problem' : ''}`}>{word[0].toUpperCase() + word.slice(1)} {shown.n}</span>
                <Ring envelope={shown.envelope} tone={shown.result} />
              </div>
              <HearGoodVsThis batch={batch} part={shown} word={word} />
            </section>
          )
        )}

        {savedReference === asset.id && !parts.length && (
          <p className="pill pill-ok" role="status">Reference saved. Ready to test.</p>
        )}

        <div className="tap-grid">
          {Array.from({ length: total }, (_, i) => i + 1).map((n) => {
            const p = parts.find((x) => x.n === n);
            const cls = p ? p.result : n === next ? 'next' : '';
            return (
              <div key={n} className={`tap-cell ${cls}`}>
                <strong>{n}</strong>
                <span>{p ? (p.result === 'good' ? 'Good' : 'Dull') : n === next ? 'Next' : ''}</span>
              </div>
            );
          })}
        </div>

        <div className="tap-counts">
          <span><b className="text-ok">{good}</b> good</span>
          <span><b className="text-problem">{dull}</b> needs a look</span>
          <span><b>{total - parts.length}</b> left</span>
        </div>

        {lines.length > 0 ? (
          <section className="tap-transcript" aria-live="polite">
            {lines.slice(-6).map((l) => (
              <p key={l.id} className={`bubble-line ${l.who}`}>{l.text}</p>
            ))}
          </section>
        ) : said ? (
          <section className="said">
            <span className="said-who">EarShot</span>
            <p>{said}</p>
          </section>
        ) : null}
        {error && <p className="error-text">{error}</p>}

        {!needsReference && (
          <div className="tap-actions">
            {lastDull ? (
              <button className="btn btn-sound btn-lg" onClick={() => setRecording({ purpose: 'check', part: lastDull.n })}>
                Tap {word} {lastDull.n} again
              </button>
            ) : (
              <button className="btn btn-sound btn-lg" disabled={next === null} onClick={() => setRecording({ purpose: 'check' })}>
                {parts.length ? 'Tap the next ones' : 'Start tapping'}
              </button>
            )}
            <button className="btn btn-lg" disabled={!session || finishing || parts.length === 0} onClick={() => void finish()}>
              {finishing ? 'Checking the batch…' : 'Finish batch'}
            </button>
          </div>
        )}
        {lastDull && next !== null && (
          <button className="btn" onClick={() => setRecording({ purpose: 'check' })}>Carry on with {word} {next}</button>
        )}
      </main>

      {pending && !recording && (
        <div className="overlay overlay-bottom">
          <ConfirmSheet confirmation={pending} voice={voice.status === 'live'} onAnswered={heard} />
        </div>
      )}
      {recording && session && (
        <ListenPanel asset={asset} mode="tap" requireStart purpose={recording.purpose} part={recording.part} session={session}
          onMute={voice.setMuted} onDone={done} onCancel={() => setRecording(null)} />
      )}
    </div>
  );
}
