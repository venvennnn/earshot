import { Link } from 'react-router-dom';
import { LogoMark } from '../components/Logo';
import { BottomNav } from '../components/BottomNav';
import { EraserIcon, ListIcon, MicIcon, PlusCircleIcon, SoundIcon } from '../components/Icons';
import './app.css';

// The worker's name and shift come from the active industry pack from Phase 5 on.
const WORKER = { name: 'Ravi', where: 'Line 3 · Night shift' };

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
  return (
    <div className="phone">
      <main className="phone-body">
        <header className="app-greeting">
          <LogoMark size={30} />
          <div>
            <h1>{greeting(new Date())}, {WORKER.name}</h1>
            <p>{WORKER.where}</p>
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
          <Link to="/app/tap" className="shortcut">
            <EraserIcon />
            <span>Tap test parts</span>
          </Link>
          <Link to="/app/add" className="shortcut">
            <PlusCircleIcon />
            <span>Add a machine</span>
          </Link>
          <Link to="/app/jobs" className="shortcut">
            <ListIcon />
            <span>My open jobs</span>
          </Link>
        </div>

        <section>
          <h2 className="app-section-title">Needs attention</h2>
          <p className="empty-note">Nothing needs your attention right now.</p>
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
