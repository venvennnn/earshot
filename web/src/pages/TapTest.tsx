import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ListenPanel } from '../components/ListenPanel';
import { ConfirmSheet } from '../components/ConfirmSheet';
import { TopBar } from '../components/Bits';
import { useLive } from '../lib/events';
import { useAppSession } from '../lib/useAppSession';
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
  const [params] = useSearchParams();
  const { live } = useLive();
  const session = useAppSession();
  const asset = live?.assets.find((a) => a.id === params.get('asset')) ?? live?.assets.find((a) => a.modes.includes('tap'));
  const [recording, setRecording] = useState<{ purpose: 'check' | 'enroll'; part?: number } | null>(null);
  const [said, setSaid] = useState('');
  const batch = asset ? live?.tap_batches[asset.id] : undefined;
  const pending = live?.confirmations.find((c) => c.session === session && (c.status === 'pending' || c.status === 'second_approval'));

  const heard = (r: TurnReply) => {
    if (r.reply) setSaid(r.reply);
    if (r.audio_url) void playAudio(r.audio_url);
  };
  const done = (res: ClipResponse) => {
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
  const needsReference = asset.state === 'unset' && !batch;
  const word = asset.type.includes('wheel') ? 'wheel' : 'part';

  return (
    <div className="phone">
      <main className="phone-body">
        <TopBar title="Tap test" sub={asset.name} right={<span className="pill pill-sound"><span className="dot" /> Ready</span>} />
        <p className="muted">
          Tap each {word} once near the phone. Good {word}s ring. A {word} with a crack sounds dull.
        </p>

        {needsReference ? (
          <section className="card">
            <h2 className="card-h">First, tap a {word} you know is good</h2>
            <p className="muted">EarShot compares every tap with that ring.</p>
            <button className="btn btn-sound btn-lg" onClick={() => setRecording({ purpose: 'enroll' })}>Record a good {word}</button>
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

        {said && (
          <section className="said">
            <span className="said-who">EarShot</span>
            <p>{said}</p>
          </section>
        )}

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
            <button className="btn btn-lg" disabled={!session}
              onClick={async () => session && heard(await api.chat(session, `I've finished the tap test for ${asset.name}. What should we do?`))}>
              Finish batch
            </button>
          </div>
        )}
        {lastDull && next !== null && (
          <button className="btn" onClick={() => setRecording({ purpose: 'check' })}>Carry on with {word} {next}</button>
        )}
      </main>

      {pending && !recording && (
        <div className="overlay overlay-bottom">
          <ConfirmSheet confirmation={pending} voice={false} onAnswered={heard} />
        </div>
      )}
      {recording && session && (
        <ListenPanel asset={asset} mode="tap" purpose={recording.purpose} part={recording.part} session={session}
          onDone={done} onCancel={() => setRecording(null)} />
      )}
    </div>
  );
}
