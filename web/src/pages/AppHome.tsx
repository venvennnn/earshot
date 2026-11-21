import { Link } from 'react-router-dom';
import { LogoMark } from '../components/Logo';
import { BottomNav } from '../components/BottomNav';
import { CheckIcon, ChevronRightIcon, ClockIcon, EraserIcon, ListIcon, MicIcon, PlusCircleIcon, SoundIcon, WarningIcon } from '../components/Icons';
import { useLive } from '../lib/events';
import './app.css';

function greeting(now: Date): string {
  const h = now.getHours();
  if (h < 12) return 'Good morning';
  if (h < 17) return 'Good afternoon';
  return 'Good evening';
}

export default function AppHome() {
  const { live, connected } = useLive();
  const pack = live?.pack;
  const tapAsset = live?.assets.find((a) => a.modes.includes('tap'));
  const waiting = live?.confirmations.filter((c) => c.status === 'pending' || c.status === 'second_approval') ?? [];
  const attention = live?.assets.filter((a) => a.state === 'problem' || a.state === 'watch' || a.state === 'out') ?? [];
  const normalCount = live?.assets.filter((a) => a.state === 'normal').length ?? 0;
  const openJobs = (live?.jobs.filter((j) => j.status !== 'done' && j.status !== 'cancelled').length ?? 0) + waiting.length;
  const reminders = live?.followups.filter((f) => f.status === 'open') ?? [];

  return (
    <div className="phone">
      <main className="phone-body app-home">
        <header className="app-greeting">
          <div className="app-shift">
            <LogoMark size={24} />
            <p>{pack ? `${pack.shift} · ${pack.line}` : connected ? 'Loading…' : 'Connecting to EarShot…'}</p>
          </div>
          <h1>
            {greeting(new Date())}{pack ? `, ${pack.worker.name}.` : '.'}
            <br />What shall we check?
          </h1>
        </header>

        <Link to="/app/talk" className="talk-card">
          <span className="talk-card-halo">
            <span className="talk-card-icon"><MicIcon size={44} /></span>
          </span>
          <span>Tap and talk</span>
        </Link>

        <div className="shortcuts">
          <Link to="/app/listen" className="shortcut shortcut-sound">
            <SoundIcon size={26} />
            <span>Listen</span>
          </Link>
          <Link to={tapAsset ? `/app/tap?asset=${tapAsset.id}` : '/app/tap'} className="shortcut shortcut-tap">
            <EraserIcon size={26} />
            <span>Tap test</span>
          </Link>
          <Link to="/app/add" className="shortcut shortcut-add">
            <PlusCircleIcon size={26} />
            <span>New machine</span>
          </Link>
        </div>

        <section>
          <h2 className="app-section-title">Needs you</h2>
          {waiting.length === 0 && attention.length === 0 && reminders.length === 0 && normalCount === 0 ? (
            <p className="empty-note">Nothing needs your attention right now.</p>
          ) : (
            <div className="attention-list">
              {waiting.map((c) => (
                <Link key={c.id} to={`/app/result?asset=${c.asset_id}&session=${c.session}`} className="attention problem">
                  <span className="attention-icon"><WarningIcon /></span>
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
                    <span className="attention-icon"><WarningIcon /></span>
                    <span>
                      <strong>{a.name}</strong>
                      <span className="muted">{a.label}</span>
                    </span>
                    <ChevronRightIcon />
                  </Link>
                ))}
              {reminders.map((f) => (
                <Link key={f.id} to={`/app/listen?asset=${f.asset_id}`} className="attention watch">
                  <span className="attention-icon"><ClockIcon /></span>
                  <span>
                    <strong>{f.asset_name}</strong>
                    <span className="muted">{f.note} · {f.when}</span>
                  </span>
                  <ChevronRightIcon />
                </Link>
              ))}
              {normalCount > 0 && (
                <div className="attention normal">
                  <span className="attention-icon"><CheckIcon size={22} /></span>
                  <span>
                    <strong>{normalCount} {normalCount === 1 ? 'machine' : 'machines'}</strong>
                    <span className="muted">Sounding normal</span>
                  </span>
                </div>
              )}
            </div>
          )}
        </section>

        <Link to="/app/jobs" className="attention app-jobs">
          <span className="attention-icon"><ListIcon /></span>
          <span><strong>My open jobs{openJobs > 0 ? ` · ${openJobs}` : ''}</strong></span>
          <ChevronRightIcon />
        </Link>
      </main>
      <BottomNav />
    </div>
  );
}
