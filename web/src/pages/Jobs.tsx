import { useState } from 'react';
import { Link } from 'react-router-dom';
import { TopBar } from '../components/Bits';
import { BottomNav } from '../components/BottomNav';
import { ListenPanel } from '../components/ListenPanel';
import { ResultCard } from '../components/ResultCard';
import { useLive } from '../lib/events';
import { useAppSession } from '../lib/useAppSession';
import { api, type ClipResponse } from '../lib/api';
import { playAudio } from '../lib/audio';
import type { Analysis, Asset, Job } from '../lib/types';
import './app.css';
import './talk.css';

const STAGE: Record<Job['status'], string> = {
  open: 'Open',
  scheduled: 'Scheduled',
  in_progress: 'In progress',
  done: 'Done',
  cancelled: 'Cancelled',
};

export default function Jobs() {
  const { live } = useLive();
  const session = useAppSession();
  const [verifying, setVerifying] = useState<Asset | null>(null);
  const [busy, setBusy] = useState('');
  const [result, setResult] = useState<Analysis | null>(null);
  const [said, setSaid] = useState('');
  const [error, setError] = useState('');

  const waiting = live?.confirmations.filter((c) => c.status === 'pending' || c.status === 'second_approval') ?? [];
  const jobs = [...(live?.jobs ?? [])].reverse();
  const open = jobs.filter((j) => j.status !== 'done' && j.status !== 'cancelled');
  const finished = jobs.filter((j) => j.status === 'done' || j.status === 'cancelled');
  const reminders = live?.followups.filter((f) => f.status === 'open') ?? [];
  const assetOf = (id: string) => live?.assets.find((a) => a.id === id);

  const start = async (job: Job) => {
    setBusy(job.id);
    setError('');
    try {
      await api.setJobStatus(job.id, 'in_progress');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not update the job.');
    } finally {
      setBusy('');
    }
  };

  const verified = (res: ClipResponse) => {
    setVerifying(null);
    setResult(res.result);
    if (res.reply) setSaid(res.reply);
    if (res.audio_url) void playAudio(res.audio_url);
  };

  return (
    <div className="phone">
      <main className="phone-body">
        <TopBar title="My open jobs" sub={live?.integrations.jira ? `Synced to Jira · ${live.integrations.jira_project}` : undefined} />

        {waiting.map((c) => (
          <Link key={c.id} to={`/app/result?asset=${c.asset_id}&session=${c.session}`} className="attention problem">
            <span className="dot" />
            <span>
              <strong>{c.question}</strong>
              <span className="muted">{c.status === 'second_approval' ? `Waiting for ${c.approver}` : 'Waiting for your OK'}</span>
            </span>
          </Link>
        ))}

        {open.map((j) => {
          const asset = assetOf(j.asset_id);
          return (
            <article key={j.id} className="card job">
              <div className="job-head">
                <span className={`badge ${j.status === 'in_progress' ? 'badge-voice' : 'badge-sound'}`}>{STAGE[j.status]}</span>
                <span className="muted small">
                  {j.id}
                  {j.jira_key && j.jira_url && (
                    <>
                      {' · '}
                      <a href={j.jira_url} target="_blank" rel="noreferrer">{j.jira_key}</a>
                    </>
                  )}
                </span>
              </div>
              <h2 className="card-h">{j.title}</h2>
              <p className="muted">
                {asset?.name ?? j.asset_id} · {j.priority} priority{j.scheduled_for ? ` · ${j.scheduled_for}` : ''}
              </p>
              {j.jira_error && <p className="error-text">{j.jira_error}</p>}
              <div className="tap-actions">
                {j.status !== 'in_progress' ? (
                  <button className="btn btn-lg" disabled={busy === j.id} onClick={() => start(j)}>Start job</button>
                ) : (
                  <span />
                )}
                <button className="btn btn-sound btn-lg" disabled={!asset || !session} onClick={() => asset && setVerifying(asset)}>
                  Mark done
                </button>
              </div>
              <p className="muted small">Mark done listens to the machine again and closes the job only if it sounds normal.</p>
            </article>
          );
        })}

        {error && <p className="error-text">{error}</p>}
        {result && <ResultCard analysis={result} facts={live?.facts[result.asset_id]} />}
        {said && (
          <section className="said">
            <span className="said-who">EarShot</span>
            <p>{said}</p>
          </section>
        )}

        {reminders.length > 0 && (
          <section>
            <h2 className="app-section-title">Reminders</h2>
            <div className="attention-list">
              {reminders.map((f) => (
                <Link key={f.id} to={`/app/listen?asset=${f.asset_id}`} className="attention watch">
                  <span className="dot" />
                  <span>
                    <strong>{f.asset_name} · {f.when}</strong>
                    <span className="muted">{f.note}</span>
                  </span>
                </Link>
              ))}
            </div>
          </section>
        )}

        {finished.length > 0 && (
          <section>
            <h2 className="app-section-title">Done this shift</h2>
            {finished.map((j) => (
              <div key={j.id} className="attention">
                <span className="dot muted-dot" />
                <span>
                  <strong>{j.title}</strong>
                  <span className="muted">{assetOf(j.asset_id)?.name ?? j.asset_id} · {STAGE[j.status]}{j.jira_key ? ` · ${j.jira_key}` : ''}</span>
                </span>
              </div>
            ))}
          </section>
        )}

        {waiting.length === 0 && jobs.length === 0 && reminders.length === 0 && (
          <p className="empty-note">No open jobs this shift.</p>
        )}
      </main>
      <BottomNav />
      {verifying && session && (
        <ListenPanel asset={verifying} purpose="verify" session={session} onDone={verified} onCancel={() => setVerifying(null)} />
      )}
    </div>
  );
}
