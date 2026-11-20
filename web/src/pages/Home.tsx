import { Link } from 'react-router-dom';
import { Logo } from '../components/Logo';
import { CheckIcon, SoundIcon } from '../components/Icons';
import './home.css';

const STEPS = [
  { n: 1, tone: 'voice', title: 'Talk', body: 'Say what you are checking, the way you would tell a colleague. No forms, no typing.' },
  { n: 2, tone: 'sound', title: 'Let it listen', body: 'Hold your phone near the machine for 10 seconds. EarShot compares it with how that machine sounds when it is healthy.' },
  { n: 3, tone: 'ok', title: 'Say yes', body: 'EarShot tells you what it heard and what it recommends. Say yes, and it takes care of the jobs and the calls.' },
] as const;

const MODES = [
  { title: 'Running machines', body: 'Hold the phone near a motor, pump or fan. EarShot hears grinding, rattling or humming that was not there before.', eg: 'Pumps · motors · compressors · fans · engines' },
  { title: 'Tapped parts', body: 'Tap each part once. Healthy parts ring; cracked ones sound dull. EarShot calls out every tap.', eg: 'Castings · train wheels · tiles · glass' },
  { title: 'Alarm beeps', body: 'Hold the phone up to a beeping box. EarShot works out what the beeps mean and what to do about them.', eg: 'Backup power · fire panels · servers' },
];

const HANDLES = [
  { title: 'Raises the job', body: 'With the right priority and the sound attached.' },
  { title: 'Checks spare parts', body: 'And sets one aside if it is in stock.' },
  { title: 'Calls the right people', body: 'Each one in their own language.' },
  { title: 'Announces on the floor', body: 'So everyone knows a machine is stopping.' },
  { title: 'Writes the shift report', body: 'And reads it out to the next shift.' },
  { title: 'Learns from the fix', body: 'When the cause is confirmed, the next diagnosis gets better.' },
];

const INDUSTRIES = [
  { title: 'Factories', body: 'Pumps, conveyors, castings' },
  { title: 'Railways', body: 'Wheels, coach air conditioning' },
  { title: 'Data centers', body: 'Backup power alarms, fans' },
  { title: 'Fleets', body: 'Engine knocks, belt squeal' },
  { title: 'Buildings', body: 'Air conditioning, water pumps, leaks' },
  { title: 'Quality labs', body: 'Tap tests on tiles and glass' },
];

const SAFETY = [
  { title: 'Small things, it just does', body: 'Looking up history, checking stock, logging a result.' },
  { title: 'Big things need your yes', body: 'Stopping a machine or pulling a batch waits for a spoken OK.' },
  { title: 'The biggest need two people', body: 'Shutting down a line or large purchases need a second approver.' },
  { title: 'When unsure, it says so', body: 'It asks for another recording or calls a person instead of guessing.' },
];

function ExampleConversation() {
  return (
    <div className="convo" aria-label="Example conversation with EarShot">
      <p className="bubble bubble-worker">Check pump P-14. It sounds rough.</p>
      <span className="pill pill-sound convo-listening">
        <SoundIcon size={14} /> Listening to the pump…
      </span>
      <p className="bubble bubble-agent">
        That sounds like a worn bearing. It's the same sound pump P-7 made in March. I'd stop it at 10 PM tonight. Shall I raise the job?
      </p>
      <p className="bubble bubble-worker">Yes.</p>
      <div className="done-card">
        <p className="done-title">Done for you</p>
        <ul>
          {['Job raised, high priority', 'Spare bearing set aside', 'Supervisor called in Hindi'].map((t) => (
            <li key={t}>
              <span className="done-check"><CheckIcon /></span>
              {t}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export default function Home() {
  return (
    <div className="site">
      <header className="site-nav wrap">
        <Link to="/" aria-label="EarShot home"><Logo /></Link>
        <nav className="site-links" aria-label="Sections">
          <a href="#how">How it works</a>
          <a href="#listens">What it listens to</a>
          <a href="#where">Where it works</a>
          <a href="#safety">Safety</a>
        </nav>
        <div className="site-ctas">
          <Link className="btn" to="/dashboard">See the dashboard</Link>
          <Link className="btn btn-dark" to="/app">Open the app</Link>
        </div>
      </header>

      <section className="hero wrap">
        <div className="hero-copy">
          <span className="pill pill-sound">Voice assistant for maintenance and quality teams</span>
          <h1>Hear machine trouble before it becomes a breakdown.</h1>
          <p className="hero-sub">
            Talk to EarShot, hold your phone up to a machine, and it tells you what sounds wrong. Then it raises the job,
            checks spare parts and calls the right people. You just say yes.
          </p>
          <div className="hero-ctas">
            <Link className="btn btn-voice btn-lg" to="/app/talk">Try it on a machine</Link>
            <a className="btn btn-lg" href="#how">See how it works</a>
          </div>
          <p className="hero-note">No typing. No training. Works in English, Hindi, Tamil and more.</p>
        </div>
        <ExampleConversation />
      </section>

      <section id="how" className="band band-grey">
        <div className="wrap">
          <h2>How it works</h2>
          <p className="section-sub">Three steps. The person on the floor only ever talks and listens.</p>
          <div className="grid grid-3">
            {STEPS.map((s) => (
              <article className="card" key={s.n}>
                <span className={`step-num step-${s.tone}`}>{s.n}</span>
                <h3>{s.title}</h3>
                <p>{s.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="listens" className="band">
        <div className="wrap">
          <h2>Three ways it listens</h2>
          <p className="section-sub">Experienced workers diagnose by ear. EarShot does the same, for every machine, on every shift.</p>
          <div className="grid grid-3">
            {MODES.map((m) => (
              <article className="card card-outline" key={m.title}>
                <h3>{m.title}</h3>
                <p>{m.body}</p>
                <p className="card-eg">{m.eg}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="band band-night">
        <div className="wrap night-grid">
          <div>
            <h2>Once it hears a problem, it handles the rest</h2>
            <p className="section-sub">
              Everything that usually means forms, phone calls and chasing people happens while the worker is still standing at the machine.
            </p>
          </div>
          <div className="grid grid-2">
            {HANDLES.map((h) => (
              <article className="night-card" key={h.title}>
                <h3>{h.title}</h3>
                <p>{h.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="where" className="band">
        <div className="wrap">
          <h2>Works anywhere things make a sound</h2>
          <p className="section-sub">Each industry gets its own pack: its machines, its words, its systems. The assistant stays the same.</p>
          <div className="grid grid-5">
            {INDUSTRIES.map((i) => (
              <article className="card card-flat" key={i.title}>
                <h3>{i.title}</h3>
                <p>{i.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="safety" className="band band-grey">
        <div className="wrap">
          <h2>It asks before it acts</h2>
          <div className="grid grid-4">
            {SAFETY.map((s) => (
              <article className="card" key={s.title}>
                <h3>{s.title}</h3>
                <p>{s.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="band">
        <div className="wrap">
          <div className="final-cta">
            <div>
              <h2>Add a machine in 10 seconds</h2>
              <p className="section-sub">Record how it sounds when it's healthy. From then on, EarShot knows when something changes.</p>
            </div>
            <Link className="btn btn-voice btn-lg" to="/app">Open the app</Link>
          </div>
        </div>
      </section>

      <footer className="site-footer wrap">
        <span>EarShot · Built for Build with Agora</span>
        <span>Voice by Agora Conversational AI and Murf Falcon</span>
      </footer>
    </div>
  );
}
