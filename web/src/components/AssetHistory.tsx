import { sentenceCase } from '../lib/format';
import type { Asset, AssetHistory, LiveState, PastIssue, TapPart } from '../lib/types';

function onPart(issue: { part?: number; title?: string; summary?: string; notes?: string }, n: number): boolean {
  if (issue.part === n) return true;
  const text = `${issue.title ?? ''} ${issue.summary ?? ''} ${issue.notes ?? ''}`;
  return new RegExp(`\\b(?:part|wheel|position)\\s*${n}\\b`, 'i').test(text);
}

function IssueLine({ issue, name }: { issue: PastIssue; name?: string }) {
  const when = [issue.when, issue.status].filter(Boolean).join(' · ');
  return (
    <li>
      <strong>{name ? `${name}: ` : ''}{issue.title}</strong>
      {when && <em>{when}</em>}
      <span>{[issue.cause ? sentenceCase(issue.cause) : '', issue.summary].filter(Boolean).join('. ')}</span>
    </li>
  );
}

export function AssetHistoryPanel({ live, asset, part, onPart: pickPart }: {
  live: LiveState;
  asset: Asset;
  part: number | null;
  onPart: (n: number | null) => void;
}) {
  const history: AssetHistory | undefined = live.histories?.[asset.id];
  const loaded = live.histories != null && Object.keys(live.histories).length > 0;
  const word = asset.type.includes('wheel') ? 'wheel' : 'part';
  const total = asset.parts || 0;
  const batch = live.tap_batches[asset.id];
  const issues = (history?.issues ?? []).filter((issue) => part == null || onPart(issue, part));
  const inspections = (history?.inspections ?? []).filter((entry) => part == null || onPart(entry, part));
  const known = new Set(issues.map((issue) => issue.id));
  const jobs = live.jobs.filter((job) => job.asset_id === asset.id && !known.has(job.id) && part == null);
  const tapped: TapPart | undefined = part == null ? undefined : batch?.parts.find((p) => p.n === part);
  const others = live.assets
    .filter((other) => other.id !== asset.id && other.type === asset.type)
    .flatMap((other) => (live.histories?.[other.id]?.issues ?? [])
      .filter((issue) => part == null || onPart(issue, part))
      .map((issue) => ({ issue, name: other.name })))
    .slice(0, 4);
  const marked = new Set((history?.issues ?? []).map((issue) => issue.part).filter((n): n is number => n != null));

  return (
    <div className="db-history">
      <div className="db-row">
        <h3>{asset.name}</h3>
        <span className={`small state-${asset.state}`}>{asset.label}</span>
      </div>
      {history?.last_serviced && <p className="small muted">Last serviced {history.last_serviced}.</p>}
      {history?.notes && <p className="small">{history.notes}</p>}

      {total > 1 && (
        <>
          <p className="small muted">Click a {word} to see its past issues.</p>
          <div className="db-parts">
            {Array.from({ length: total }, (_, i) => i + 1).map((n) => {
              const hit = batch?.parts.find((p) => p.n === n);
              const cls = [hit?.result, part === n ? 'sel' : '', !hit && marked.has(n) ? 'had' : ''].filter(Boolean).join(' ');
              return (
                <button key={n} type="button" className={`db-part ${cls}`} onClick={() => pickPart(part === n ? null : n)}>
                  <strong>{n}</strong>
                  <span>{hit ? (hit.result === 'dull' ? 'Dull' : 'Good') : marked.has(n) ? 'Past' : ''}</span>
                </button>
              );
            })}
          </div>
        </>
      )}

      <h3>{part == null ? 'Past issues' : `Past issues on ${word} ${part}`}</h3>
      {part != null && (
        <p className="small">
          {tapped
            ? `${word[0].toUpperCase() + word.slice(1)} ${part} ${tapped.result === 'dull' ? 'sounds dull' : 'rings well'} this test. ${tapped.reason}`
            : `${word[0].toUpperCase() + word.slice(1)} ${part} has not been tapped this shift.`}
        </p>
      )}
      {!loaded && <p className="muted small">Past issues could not be loaded.</p>}
      {loaded && issues.length === 0 && inspections.length === 0 && jobs.length === 0 && (
        <p className="muted small">
          {part == null ? `No past issues recorded on ${asset.name}.` : `No past issues on ${word} ${part}.`}
        </p>
      )}
      <ul className="db-issues">
        {issues.map((issue) => <IssueLine key={issue.id} issue={issue} />)}
        {inspections.map((entry) => (
          <li key={entry.id}>
            <strong>Inspection {entry.result}</strong>
            <em>{entry.at.replace('T', ' ')}</em>
            {entry.notes && <span>{entry.notes}</span>}
          </li>
        ))}
        {jobs.map((job) => (
          <li key={job.id}>
            <strong>{job.title}</strong>
            <em>{job.status}{job.priority ? ` · ${job.priority}` : ''}</em>
          </li>
        ))}
      </ul>
      {others.length > 0 && (
        <>
          <h3>On other {asset.type}s</h3>
          <ul className="db-issues">
            {others.map(({ issue, name }) => <IssueLine key={issue.id} issue={issue} name={name} />)}
          </ul>
        </>
      )}
    </div>
  );
}
