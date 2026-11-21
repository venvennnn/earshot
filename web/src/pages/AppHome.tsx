import { Link } from 'react-router-dom';
import { LogoMark } from '../components/Logo';
import { BottomNav } from '../components/BottomNav';
import { ChevronRightIcon, EraserIcon, ListIcon, MicIcon, PlusCircleIcon, SoundIcon } from '../components/Icons';
import { useLive } from '../lib/events';
import './app.css';

function greeting(now: Date): string {
  const h = now.getHours();
  if (h < 12) return 'Good morning';
  if (h < 17) return 'Good afternoon';
  return 'Good evening';
}

const STEPS = [
  { n: 1, tone: 'voice', text: "Tell it what you're checking" },
  { n: 2, tone: 'sound', text: 'Hold the phone near it' },
  { n: 3, tone: 'ok', text: 'Say yes to what it suggests' },
] as const;

export default function AppHome() {
  const { live, connected } = useLive();
  const pack = live?.pack;
  const tapAsset = live?.assets.find((a) => a.modes.includes('tap'));
  const waiting = live?.confirmations.filter((c) => c.status === 'pending' || c.status === 'second_approval') ?? [];
  const attention = live?.assets.filter((a) => a.state === 'problem' || a.state === 'watch' || a.state === 'out') ?? [];
  const openJobs = (live?.jobs.filter((j) => j.status !== 'done' && j.status !== 'cancelled').length ?? 0) + waiting.length;
  const reminders = live?.followups.filter((f) => f.status === 'open') ?? [];

  return (
    <div className="phone">
      <main className="phone-body">
        <header className="app-greeting">
          <LogoMark size={30} />
          <div>
            <h1>
              {greeting(new Date())}
              {pack ? `, ${pack.worker.name}` : ''}
            </h1>
            <p>{pack ? `${pack.line} · ${pack.shift}` : connected ? 'Loading…' : 'Connecting to EarShot…'}</p>
          </div>
        </header>

        <Link to="/app/talk" className="talk-card">
          <span className="talk-card-icon"><MicIcon size={28} /></span>
          <span>
            <span className="talk-card-title">Start talking</span>
            <span className="talk-card-sub">Tell EarShot what you're checking</span>
          </span>
        </Link>

        <div className="shortcuts">
          <Link to="/app/listen" className="shortcut shortcut-sound">
            <SoundIcon />
            <span>Check a machine</span>
          </Link>
          <Link to={tapAsset ? `/app/tap?asset=${tapAsset.id}` : '/app/tap'} className="shortcut">
            <EraserIcon />
            <span>Tap test parts</span>
          </Link>
          <Link to="/app/add" className="shortcut">
            <PlusCircleIcon />
            <span>Add a machine</span>
          </Link>
          <Link to="/app/jobs" className="shortcut">
            <ListIcon />
            <span>
              My open jobs{openJobs > 0 && <span className="count"> · {openJobs}</span>}
            </span>
          </Link>
        </div>

        <section>
          <h2 className="app-section-title">Needs attention</h2>
          {waiting.length === 0 && attention.length === 0 && reminders.length === 0 ? (
            <p className="empty-note">Nothing needs your attention right now.</p>
          ) : (
            <div className="attention-list">
              {waiting.map((c) => (
                <Link key={c.id} to={`/app/result?asset=${c.asset_id}&session=${c.session}`} className="attention problem">
                  <span className="dot" />
                  <span>
                    <strong>{c.asset_name}</strong>
                    <span className="muted">{c.question} · waiting for your OK</span>
                  </span>
                  <ChevronRightIcon />
                </Link>
              ))}
              {attention
                .filter((a) => !waiting.some((c) => c.asset_id === a.id))
                .map((a) => (
                  <Link key={a.id} to={`/app/result?asset=${a.id}`} className={`attention ${a.state === 'watch' ? 'watch' : 'problem'}`}>
                    <span className="dot" />
                    <span>
                      <strong>{a.name}</strong>
                      <span className="muted">{a.label}</span>
                    </span>
                    <ChevronRightIcon />
                  </Link>
                ))}
              {reminders.map((f) => (
                <Link key={f.id} to={`/app/listen?asset=${f.asset_id}`} className="attention watch">
                  <span className="dot" />
                  <span>
                    <strong>{f.asset_name}</strong>
                    <span className="muted">{f.note} · {f.when}</span>
                  </span>
                  <ChevronRightIcon />
                </Link>
              ))}
            </div>
          )}
        </section>

        <ol className="steps-strip">
          {STEPS.map((s) => (
            <li key={s.n}>
              <span className={`steps-num tone-${s.tone}`}>{s.n}</span>
              <span>{s.text}</span>
            </li>
          ))}
        </ol>
      </main>
      <BottomNav />
    </div>
  );
}
