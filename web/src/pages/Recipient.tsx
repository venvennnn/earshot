import { useCallback, useState } from 'react';
import { timeOf } from '../lib/format';
import { useSearchParams } from 'react-router-dom';
import { LogoMark } from '../components/Logo';
import { useLive, useLiveEvent } from '../lib/events';
import { api } from '../lib/api';
import { playAudio } from '../lib/audio';
import type { Contact, LiveEvent } from '../lib/types';
import './app.css';

function Message({ c }: { c: Contact }) {
  const [busy, setBusy] = useState(false);
  const replied = Boolean(c.reply);
  const reply = async (text: string) => {
    setBusy(true);
    try { await api.reply(c.id, text); } finally { setBusy(false); }
  };
  return (
    <article className={`card brief ${replied ? 'done' : ''}`}>
      <div className="brief-head">
        <span className="badge badge-voice">From EarShot · {timeOf(c.ts)}</span>
        <span className="muted small">{c.status}</span>
      </div>
      <p className="brief-text" lang={c.language}>{c.text || c.message}</p>
      {c.audio_url && <button className="btn btn-voice btn-lg" onClick={() => void playAudio(c.audio_url!)}>▶ Play message</button>}
      {replied ? (
        <p className="muted">You replied: <b>{c.reply}</b></p>
      ) : c.approval_for ? (
        <div className="sheet-actions">
          <button className="btn btn-dark btn-lg" disabled={busy} onClick={() => reply('approved')}>Approve</button>
          <button className="btn btn-lg" disabled={busy} onClick={() => reply('declined')}>Decline</button>
        </div>
      ) : (
        <div className="reply-row">
          <button className="btn" disabled={busy} onClick={() => reply('got it')}>Got it</button>
          <button className="btn" disabled={busy} onClick={() => reply('no stock')}>No stock</button>
          <button className="btn" disabled={busy} onClick={() => reply('please call me')}>Call me</button>
        </div>
      )}
    </article>
  );
}

/** Phone page for a supervisor or stores person: briefings in their language, play, and reply. */
export default function Recipient() {
  const [params] = useSearchParams();
  const name = params.get('name') ?? '';
  const { live } = useLive();
  const [armed, setArmed] = useState(false);
  const mine = (live?.contacts ?? []).filter((c) => c.kind === 'call' && c.name.toLowerCase() === name.toLowerCase()).reverse();
  const person = live?.pack?.people.find((p) => p.name.toLowerCase() === name.toLowerCase());

  const onEvent = useCallback((e: LiveEvent) => {
    if (!armed || e.kind !== 'briefing' || e.name.toLowerCase() !== name.toLowerCase()) return;
    const c = live?.contacts.find((x) => x.id === e.contact_id);
    if (c?.audio_url) void playAudio(c.audio_url);
  }, [armed, name, live]);
  useLiveEvent(onEvent);

  return (
    <div className="phone">
      <main className="phone-body">
        <header className="app-greeting">
          <LogoMark size={30} />
          <div>
            <h1>{name || 'Messages'}</h1>
            <p>{person ? `${person.role} · ${live?.pack?.plant}` : 'Messages from EarShot'}</p>
          </div>
        </header>
        {!armed && (
          <button className="btn btn-voice btn-lg" onClick={() => setArmed(true)}>Play new messages out loud</button>
        )}
        {mine.length === 0 && <p className="empty-note">No messages yet. New ones appear here as soon as EarShot sends them.</p>}
        {mine.map((c) => <Message key={c.id} c={c} />)}
      </main>
    </div>
  );
}
