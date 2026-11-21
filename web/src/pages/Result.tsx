import { useEffect, useState } from 'react';
import { timeOf } from '../lib/format';
import { useLocation, useSearchParams } from 'react-router-dom';
import { ResultCard } from '../components/ResultCard';
import { ConfirmSheet } from '../components/ConfirmSheet';
import { TopBar } from '../components/Bits';
import { useLive } from '../lib/events';
import { playAudio } from '../lib/audio';
import type { TurnReply } from '../lib/api';
import type { Analysis } from '../lib/types';
import './app.css';
import './talk.css';

interface NavState {
  reply?: string;
  audio?: string | null;
  result?: Analysis & Record<string, unknown>;
}

export default function Result() {
  const [params] = useSearchParams();
  const location = useLocation();
  const nav = (location.state ?? {}) as NavState;
  const { live } = useLive();
  const assetId = params.get('asset') ?? '';
  const session = params.get('session');
  const [reply, setReply] = useState(nav.reply ?? '');
  const asset = live?.assets.find((a) => a.id === assetId);
  // A failed recording (too quiet…) is shown as such; otherwise prefer the live analysis.
  const fresh = nav.result && (nav.result.band || nav.result.ok === false) ? nav.result : undefined;
  const analysis = fresh?.ok === false ? fresh : (live?.analyses[assetId] ?? fresh);
  const pending = live?.confirmations.find(
    (c) => c.asset_id === assetId && (!session || c.session === session) && (c.status === 'pending' || c.status === 'second_approval'),
  );

  useEffect(() => {
    if (nav.audio) void playAudio(nav.audio);
  }, [nav.audio]);

  const answered = (r: TurnReply) => {
    if (r.reply) setReply(r.reply);
    if (r.audio_url) void playAudio(r.audio_url);
  };

  return (
    <div className="phone">
      <main className="phone-body with-sheet">
        <TopBar title={asset?.name ?? assetId} sub={analysis ? `Listened at ${timeOf(analysis.at)}` : asset?.label} />
        {analysis ? (
          <ResultCard analysis={analysis} facts={live?.facts[assetId]} />
        ) : nav.result ? (
          <section className="card">
            <p>{(nav.result.meaning as string) ?? (nav.result.tip as string) ?? 'Done.'}</p>
          </section>
        ) : (
          <p className="empty-note">No recording of this machine yet this shift.</p>
        )}
        {reply && (
          <section className="said">
            <span className="said-who">EarShot</span>
            <p>{reply}</p>
          </section>
        )}
      </main>
      {pending && (
        <div className="overlay overlay-bottom static">
          <ConfirmSheet confirmation={pending} voice={false} onAnswered={answered} />
        </div>
      )}
    </div>
  );
}
