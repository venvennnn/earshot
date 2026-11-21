import { useCallback, useEffect, useRef, useState } from 'react';
import { sentenceCase, midSentence, timeOf } from '../lib/format';
import { Logo } from '../components/Logo';
import { CheckIcon, SoundIcon } from '../components/Icons';
import { SpectrumChart, UnusualBar } from '../components/Bits';
import { useLive, useLiveEvent } from '../lib/events';
import { api, mediaUrl, type JiraConnection } from '../lib/api';
import { playAudio } from '../lib/audio';
import { AssetHistoryPanel } from '../components/AssetHistory';
import { TapCompare } from '../components/TapCompare';
import type { Asset, Contact, LiveEvent, LiveState } from '../lib/types';
import './dashboard.css';

const STATE_DOT: Record<string, string> = { normal: 'ok', watch: 'watch', problem: 'problem', out: 'problem', unset: 'unset' };

function JiraSettings({ project }: { project?: string | null }) {
  const [result, setResult] = useState<JiraConnection | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState('');

  const check = async () => {
    setChecking(true);
    setError('');
    setResult(null);
    try {
      setResult(await api.jiraConnection());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not check Jira.');
    } finally {
      setChecking(false);
    }
  };

  return (
    <details className="db-card db-jira">
      <summary>Jira {project ? `· ${project}` : 'setup'}</summary>
      <p>Approved repair jobs automatically create tickets in the configured Jira Cloud project.</p>
      <p className="muted small">
        Set <code>JIRA_SITE</code>, <code>JIRA_EMAIL</code>, <code>JIRA_API_TOKEN</code> and <code>JIRA_PROJECT</code> on the
        enterprise MCP service, then restart it. Use its secret settings for the token.
      </p>
      <button className="btn" disabled={checking} onClick={() => void check()}>
        {checking ? 'Checking Jira…' : 'Test connection'}
      </button>
      <div role="status">
        {error && <p className="error-text">{error}</p>}
        {result?.status === 'not_configured' && <p className="muted">Required settings: {result.missing.join(', ')}.</p>}
        {result?.status === 'connected' && <p className="text-ok">Connected to {result.project}. Create Issues permission confirmed.</p>}
        {result?.status === 'error' && <p className="error-text">{result.message}</p>}
      </div>
    </details>
  );
}

function Header({ live, connected, soundOn, onSound }: { live: LiveState | null; connected: boolean; soundOn: boolean; onSound: () => void }) {
  const [packs, setPacks] = useState<{ id: string; name: string }[]>([]);
  const [switching, setSwitching] = useState(false);
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    void api.packs().then((p) => setPacks(p.packs)).catch(() => undefined);
    const t = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(t);
  }, []);
  const tts = live?.tts;
  return (
    <header className="db-card db-header">
      <Logo size={26} />
      <div className="db-where">
        <h1>{live?.pack ? `${live.pack.line} · ${live.pack.plant}` : 'Dashboard'}</h1>
        <span>
          {live?.pack && `${live.pack.shift} · `}
          {now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
        </span>
      </div>
      <div className="db-header-right">
        <span className={`pill ${connected ? 'pill-ok' : 'pill-sound'}`}>
          <span className="dot" /> {connected ? 'EarShot is on' : 'Reconnecting…'}
        </span>
        <span className="db-latency" title={tts ? `Measured: LLM reply ${tts.llm_reply_median_s ?? '–'} s + Murf first audio ${tts.murf_ttfa_median_s ?? '–'} s` : ''}>
          {tts?.voice_reply_s != null ? <>Voice reply in <b>{tts.voice_reply_s.toFixed(2)} s</b></> : 'Voice reply: measuring…'}
        </span>
        {!soundOn && <button className="btn" onClick={onSound}>Turn on sound</button>}
        <label className="db-select">
          <span>Industry</span>
          <select value={live?.pack?.id ?? ''} disabled={switching} onChange={async (e) => {
            setSwitching(true);
            try { await api.switchPack(e.target.value); } finally { setSwitching(false); }
          }}>
            {packs.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
      </div>
    </header>
  );
}

function AttentionBanner({ live }: { live: LiveState }) {
  const [busy, setBusy] = useState(false);
  const conf = [...live.confirmations].reverse().find((c) => c.status === 'pending' || c.status === 'second_approval');
  if (!conf) {
    return (
      <section className="db-banner db-banner-clear" aria-label="Open incidents">
        <p className="db-banner-label">Decisions this shift</p>
        <h2>No decisions waiting</h2>
      </section>
    );
  }
  const answer = async (d: 'yes' | 'no') => {
    setBusy(true);
    try { await api.answer(conf.id, d); } finally { setBusy(false); }
  };
  return (
    <section className="db-banner">
      <p className="db-banner-label"><SoundIcon size={18} /> Needs a decision</p>
      <h2>{conf.question}</h2>
      <div className="db-banner-detail">
        <p>
          {conf.steps.length ? `EarShot will: ${conf.steps.map((st) => midSentence(st.text)).join(', ')}. ` : ''}
          {conf.status === 'second_approval' ? `${conf.worker} said yes. Waiting for ${conf.approver} to approve.` : `Waiting for ${conf.worker} to say yes.`}
        </p>
      </div>
      {conf.status === 'pending' && (
        <div className="db-banner-actions">
          <button className="btn btn-dark" disabled={busy} onClick={() => answer('yes')}>Approve</button>
          <button className="btn" disabled={busy} onClick={() => answer('no')}>Not now</button>
        </div>
      )}
    </section>
  );
}

function Tiles({ live }: { live: LiveState }) {
  const t = live.tiles;
  const names = t.problem_assets.map((id) => midSentence(live.assets.find((a) => a.id === id)?.name ?? id));
  return (
    <section className="db-tiles">
      <div className="db-card db-tile db-tile-voice"><span>Machines checked</span><strong>{t.machines_checked}</strong><em>this shift</em></div>
      <div className="db-card db-tile db-tile-sound"><span>Problems caught early</span><strong>{t.problems_caught}</strong><em>{names.join(' and ') || 'none so far'}</em></div>
      <div className="db-card db-tile db-tile-ok"><span>Breakdown time saved</span><strong>{t.hours_saved_estimate} h</strong><em>estimated</em></div>
      <div className="db-card db-tile db-tile-violet"><span>Jobs done for the team</span><strong>{t.jobs_done}</strong><em>{t.waiting_for_yes} waiting for a yes</em></div>
    </section>
  );
}

function Wave({ active }: { active: boolean }) {
  return (
    <div className={`db-wave ${active ? 'on' : ''}`} aria-hidden="true">
      {Array.from({ length: 36 }, (_, i) => <span key={i} style={{ animationDelay: `${(i % 9) * 0.09}s` }} />)}
    </div>
  );
}

function ContactRow({ c }: { c: Contact }) {
  const tone = /approved|told/i.test(c.status) ? 'ok' : /declined|failed/i.test(c.status) ? 'problem' : 'sound';
  return (
    <div className="db-contact">
      <div>
        <strong>{c.name}</strong>
        <span>{c.role} · in {c.language_name}</span>
      </div>
      <div className="db-contact-right">
        {c.audio_url && <button className="icon-play" aria-label={`Play message to ${c.name}`} onClick={() => void playAudio(c.audio_url!)}>▶</button>}
        <span className={`text-${tone}`}>{c.status}</span>
      </div>
    </div>
  );
}

function Conversations({ live }: { live: LiveState }) {
  const sessionIds = Object.keys(live.sessions);
  const recent = live.transcript.filter((l) => sessionIds.includes(l.session));
  const last = recent[recent.length - 1];
  const talking = last ? Date.now() / 1000 - last.ts < 20 : false;
  const worker = live.pack?.worker;
  return (
    <section className="db-card db-col">
      <h2>Conversations</h2>
      {sessionIds.length > 0 && worker ? (
        <div className={`db-call ${talking ? 'live' : ''}`}>
          <div className="db-call-head">
            <span className="avatar">{worker.name[0]}</span>
            <div>
              <strong>{worker.name}, {worker.role}</strong>
              <span>On the floor, {live.pack?.line}</span>
            </div>
            <span className="text-voice small">{talking ? 'Talking now' : 'Connected'}</span>
          </div>
          <Wave active={talking} />
          {recent.slice(-4).map((l) => (
            <p key={l.id} className="db-line">
              <b className={l.who === 'agent' ? 'text-voice' : ''}>{l.who === 'agent' ? 'EarShot' : worker.name}:</b> {l.text}
            </p>
          ))}
        </div>
      ) : (
        <p className="muted">No one is talking to EarShot right now.</p>
      )}
      <h3>People EarShot is contacting</h3>
      {live.contacts.length === 0 && <p className="muted small">Nobody yet.</p>}
      {[...live.contacts].reverse().map((c) => <ContactRow key={c.id} c={c} />)}
    </section>
  );
}

function focusedAsset(live: LiveState, selected: string | null): Asset | undefined {
  const withAnalysis = live.assets.filter((a) => live.analyses[a.id]);
  const auto = withAnalysis.find((a) => a.state === 'problem') ?? withAnalysis[withAnalysis.length - 1];
  return live.assets.find((a) => a.id === selected) ?? auto;
}

function LineAtGlance({ live, selected, part, onSelect, onPart }: {
  live: LiveState;
  selected: string | null;
  part: number | null;
  onSelect: (id: string) => void;
  onPart: (n: number | null) => void;
}) {
  const asset = focusedAsset(live, selected);
  const analysis = asset ? live.analyses[asset.id] : undefined;
  const facts = asset ? live.facts[asset.id] ?? {} : {};
  return (
    <section className="db-card db-col db-mid">
      <div className="db-row">
        <h2>{live.pack?.line} at a glance</h2>
        <div className="db-legend">
          <span><i className="ok" />Sounds normal</span>
          <span><i className="watch" />Keep an eye on it</span>
          <span><i className="problem" />Problem found</span>
        </div>
      </div>
      <div className="db-assets">
        {live.assets.map((a) => (
          <button key={a.id} className={`db-asset ${a.state} ${asset?.id === a.id ? 'sel' : ''}`} onClick={() => onSelect(a.id)}>
            <span className="db-asset-top"><b className="mono">{a.id}</b><i className={STATE_DOT[a.state]} /></span>
            <span className="muted small">{sentenceCase(a.type)}</span>
            <span className={`small state-${a.state}`}>{a.label}</span>
          </button>
        ))}
      </div>
      {asset ? (
        <div className="db-heard">
          {analysis?.ok && analysis.spectrum && (
            <>
              <h3>What EarShot heard from {midSentence(asset.name)}</h3>
              <SpectrumChart baseline={analysis.spectrum.baseline} now={analysis.spectrum.now} height={140} />
              <p className="small"><span className="text-sound-ink">Sky blue</span> is how {asset.id} sounds when healthy. <span className="text-voice">Violet</span> is how it sounds now. {analysis.explanation}</p>
              <p className="small muted">How unusual it sounds</p>
              <UnusualBar analysis={analysis} />
              <dl className="facts">
                <div><dt>Most likely</dt><dd>{sentenceCase(analysis.label ?? '')}</dd></div>
                <div><dt>How sure</dt><dd>{sentenceCase(analysis.confidence ?? '')}</dd></div>
                {facts.seen_before && <div><dt>Happened before</dt><dd>{facts.seen_before}</dd></div>}
                {facts.last_serviced && <div><dt>Last serviced</dt><dd>{facts.last_serviced}</dd></div>}
                {facts.spare && <div><dt>Spare part</dt><dd>{facts.spare}</dd></div>}
              </dl>
            </>
          )}
          <AssetHistoryPanel live={live} asset={asset} part={part} onPart={onPart} />
        </div>
      ) : (
        <p className="muted db-heard">Select a machine to see its past issues.</p>
      )}
    </section>
  );
}

function Timeline({ live }: { live: LiveState }) {
  const [tech, setTech] = useState(false);
  return (
    <section className="db-card db-col db-activity">
      <h2>What EarShot did</h2>
      <ol className="db-timeline">
        {live.timeline.slice(-14).map((t) => (
          <li key={t.id} className={t.status}>
            <span className="tl-icon">{t.status === 'done' ? <CheckIcon size={12} /> : t.status === 'failed' ? '!' : null}</span>
            <div>
              <span>{t.text}</span>
              <em>
                {t.status === 'next' ? 'next' : t.status === 'skipped' ? 'not done' : timeOf(t.ts)}
                {typeof t.detail.result?.jira_error === 'string' && (
                  <em className="text-problem">{t.detail.result.jira_error}</em>
                )}
                {t.detail.result?.jira_url && (
                  <>
                    {' · '}
                    <a href={t.detail.result.jira_url} target="_blank" rel="noreferrer">Open in Jira</a>
                  </>
                )}
              </em>
              {tech && t.detail.tool && (
                <code className="tl-tech">
                  {t.detail.tool}({JSON.stringify(t.detail.args ?? {})}){t.detail.tier != null ? ` · tier ${t.detail.tier}` : ''}
                  {t.detail.error ? ` · error: ${t.detail.error}` : ''}
                </code>
              )}
            </div>
          </li>
        ))}
      </ol>
      {live.timeline.length === 0 && <p className="muted small">Nothing yet this shift.</p>}
      {live.followups.some((f) => f.status === 'open') && (
        <>
          <h3>Coming up next shift</h3>
          <ul className="db-followups">
            {live.followups.filter((f) => f.status === 'open').map((f) => (
              <li key={f.id}>
                <strong>{f.asset_name} · {f.when}</strong>
                <span>{f.note}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      <button className="btn" onClick={() => setTech((v) => !v)}>{tech ? 'Hide technical details' : 'Show technical details'}</button>
    </section>
  );
}

function Briefing({ live }: { live: LiveState }) {
  const [writing, setWriting] = useState(false);
  const [reading, setReading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [playing, setPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);
  const report = live.report;
  const toggle = () => {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) void a.play();
    else a.pause();
  };
  return (
    <section className="db-card db-brief">
      {report?.audio_url ? (
        <>
          <button className="play-btn" aria-label={playing ? 'Pause' : 'Play shift briefing'} onClick={toggle}>{playing ? '❚❚' : '▶'}</button>
          <audio ref={audioRef} src={mediaUrl(report.audio_url)} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
            onTimeUpdate={(e) => setProgress(e.currentTarget.currentTime / (e.currentTarget.duration || 1))} />
        </>
      ) : (
        <span className="play-btn off">▶</span>
      )}
      <div className="db-brief-text">
        <strong>{report ? "Tonight's shift briefing" : 'Shift briefing'}</strong>
        <span>{report ? `Written at ${timeOf(report.ts)} · read by Murf Falcon` : 'Not written yet'}</span>
      </div>
      <div className="db-progress"><span style={{ width: `${progress * 100}%` }} /></div>
      {report ? (
        <button className="link-btn" onClick={() => setReading((v) => !v)}>{reading ? 'Hide text' : 'Read it instead'}</button>
      ) : (
        <button className="btn" disabled={writing} onClick={async () => { setWriting(true); try { await api.writeReport(); } finally { setWriting(false); } }}>
          {writing ? 'Writing…' : 'Write the shift report'}
        </button>
      )}
      {reading && report && <p className="db-brief-full">{report.text}</p>}
    </section>
  );
}

export default function Dashboard() {
  const { live, connected } = useLive();
  const [soundOn, setSoundOn] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [part, setPart] = useState<number | null>(null);
  const packId = live?.pack?.id;
  useEffect(() => {
    setSelected(null);
    setPart(null);
  }, [packId]);
  const onEvent = useCallback((e: LiveEvent) => {
    if (soundOn && e.kind === 'play_audio' && e.target === 'dashboard') void playAudio(e.url);
  }, [soundOn]);
  useLiveEvent(onEvent);
  const asset = live ? focusedAsset(live, selected) : undefined;

  return (
    <div className="db">
      <Header live={live} connected={connected} soundOn={soundOn} onSound={() => setSoundOn(true)} />
      {live ? (
        <>
          <div className="db-overview">
            <AttentionBanner live={live} />
            <Tiles live={live} />
          </div>
          <div className="db-grid">
            <LineAtGlance live={live} selected={selected} part={part} onSelect={(id) => { setSelected(id); setPart(null); }} onPart={setPart} />
            <Timeline live={live} />
          </div>
          {asset && <TapCompare live={live} asset={asset} part={part} onPart={setPart} />}
          <div className="db-grid db-bottom">
            <Conversations live={live} />
            <Briefing live={live} />
          </div>
        </>
      ) : (
        <p className="db-card muted">Connecting to EarShot…</p>
      )}
      <JiraSettings project={live?.integrations.jira_project} />
    </div>
  );
}
