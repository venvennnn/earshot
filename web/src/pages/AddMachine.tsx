import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ListenPanel } from '../components/ListenPanel';
import { ResultCard } from '../components/ResultCard';
import { ConfirmSheet } from '../components/ConfirmSheet';
import { TopBar } from '../components/Bits';
import { useLive } from '../lib/events';
import { useAppSession } from '../lib/useAppSession';
import { api, type ClipResponse, type TurnReply } from '../lib/api';
import { playAudio } from '../lib/audio';
import type { Analysis, Asset, Mode } from '../lib/types';
import './app.css';
import './talk.css';

/** Add a machine in 10 seconds: record its healthy sound, then check it. */
export default function AddMachine() {
  const [params] = useSearchParams();
  const { live } = useLive();
  const session = useAppSession();
  const [assetId, setAssetId] = useState(params.get('asset') ?? '');
  const [name, setName] = useState('');
  const [type, setType] = useState('');
  const [selectedMode, setMode] = useState<Mode | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [recording, setRecording] = useState<'enroll' | 'check' | null>(null);
  const [enrolled, setEnrolled] = useState(false);
  const [result, setResult] = useState<Analysis | null>(null);
  const [said, setSaid] = useState('');
  const [error, setError] = useState('');

  const asset: Asset | undefined = live?.assets.find((a) => a.id === assetId);
  const mode = selectedMode ?? (asset?.modes.includes('tap') && !asset.modes.includes('continuous') ? 'tap' : 'continuous');
  const unset = live?.assets.filter((a) => a.state === 'unset') ?? [];
  const pending = live?.confirmations.find((c) => c.session === session && (c.status === 'pending' || c.status === 'second_approval'));

  const heard = (r: TurnReply) => {
    if (r.reply) setSaid(r.reply);
    if (r.audio_url) void playAudio(r.audio_url);
  };

  const start = async () => {
    setError('');
    try {
      if (!assetId) {
        const created = await api.addAsset(name.trim(), type.trim() || 'machine');
        setAssetId(created.asset_id);
      }
      setRecording('enroll');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not add the machine.');
    }
  };

  const done = (res: ClipResponse) => {
    const wasEnroll = recording === 'enroll';
    setRecording(null);
    heard(res);
    if (wasEnroll) {
      setEnrolled(Boolean(res.result.enrolled));
      if (!res.result.enrolled) setError(res.result.tip ?? 'No reference saved. Try again.');
    }
    else setResult(res.result);
  };

  return (
    <div className="phone">
      <main className="phone-body">
        <TopBar title="Add a machine" sub="Record how it sounds when it's healthy" />

        {!enrolled ? (
          <section className="card form-card">
            <label className="field">
              <span>Machine</span>
              <select value={assetId} onChange={(e) => {
                setAssetId(e.target.value);
                setMode(null);
              }}>
                <option value="">A new machine…</option>
                {unset.map((a) => (
                  <option key={a.id} value={a.id}>{a.name} (not set up yet)</option>
                ))}
                {live?.assets.filter((a) => a.state !== 'unset').map((a) => (
                  <option key={a.id} value={a.id}>{a.name} (record again)</option>
                ))}
              </select>
            </label>
            {!assetId && (
              <>
                <label className="field">
                  <span>Name</span>
                  <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Fan F-3, Desk fan" />
                </label>
                <label className="field">
                  <span>What kind of machine</span>
                  <input value={type} onChange={(e) => setType(e.target.value)} placeholder="e.g. fan, pump, motor" />
                </label>
              </>
            )}
            <div className="segmented light" role="radiogroup" aria-label="How it sounds">
              <button role="radio" aria-checked={mode === 'continuous'} className={mode === 'continuous' ? 'on' : ''} onClick={() => setMode('continuous')}>Running machine</button>
              <button role="radio" aria-checked={mode === 'tap'} className={mode === 'tap' ? 'on' : ''} onClick={() => setMode('tap')}>Tapped part</button>
            </div>

            <details className="helper">
              <summary>Enroll from this speaker</summary>
              <p className="muted small">
                Demoing with recordings? Pick the healthy recording here. EarShot plays it through this phone's speaker while
                it records, so the healthy sound and any faulty clip you play later go through the same speaker. That way
                the speaker itself is not mistaken for a fault.
              </p>
              <input type="file" accept="audio/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </details>

            <button className="btn btn-sound btn-lg" disabled={!session || (!assetId && !name.trim())} onClick={start}>
              {mode === 'tap' ? 'Record one good tap' : 'Record healthy sound'}
            </button>
            {error && <p className="error-text">{error}</p>}
          </section>
        ) : (
          <section className="card">
            <span className="badge badge-ok">Set up</span>
            <h2 className="result-title">{asset?.name} is set up</h2>
            <p className="muted">From now on EarShot will notice when it sounds different. Try it: make it sound wrong, then check it.</p>
            <button className="btn btn-sound btn-lg" onClick={() => { setResult(null); setRecording('check'); }}>Check it now</button>
          </section>
        )}

        {result && <ResultCard analysis={result} facts={live?.facts[result.asset_id]} />}
        {said && (
          <section className="said">
            <span className="said-who">EarShot</span>
            <p>{said}</p>
          </section>
        )}
      </main>

      {pending && !recording && (
        <div className="overlay overlay-bottom">
          <ConfirmSheet confirmation={pending} voice={false} onAnswered={heard} />
        </div>
      )}
      {recording && asset && session && (
        <ListenPanel asset={asset} mode={mode} requireStart purpose={recording} session={session}
          playFile={recording === 'enroll' ? file : null} onDone={done} onCancel={() => setRecording(null)} />
      )}
    </div>
  );
}
