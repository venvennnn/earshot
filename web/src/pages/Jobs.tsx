import { Link } from 'react-router-dom';
import { TopBar } from '../components/Bits';
import { BottomNav } from '../components/BottomNav';
import { useLive } from '../lib/events';
import './app.css';

export default function Jobs() {
  const { live } = useLive();
  const waiting = live?.confirmations.filter((c) => c.status === 'pending' || c.status === 'second_approval') ?? [];
  const jobs = live?.jobs ?? [];
  return (
    <div className="phone">
      <main className="phone-body">
        <TopBar title="My open jobs" />
        {waiting.map((c) => (
          <Link key={c.id} to={`/app/result?asset=${c.asset_id}&session=${c.session}`} className="attention problem">
            <span className="dot" />
            <span>
              <strong>{c.question}</strong>
              <span className="muted">{c.status === 'second_approval' ? `Waiting for ${c.approver}` : 'Waiting for your OK'}</span>
            </span>
          </Link>
        ))}
        {jobs.map((j) => (
          <div key={j.id} className="attention">
            <span className="dot muted-dot" />
            <span>
              <strong>{j.title}</strong>
              <span className="muted">
                {live?.assets.find((a) => a.id === j.asset_id)?.name ?? j.asset_id} · {j.priority} priority
                {j.scheduled_for ? ` · ${j.scheduled_for}` : ''}
              </span>
            </span>
          </div>
        ))}
        {waiting.length === 0 && jobs.length === 0 && <p className="empty-note">No open jobs this shift.</p>}
      </main>
      <BottomNav />
    </div>
  );
}
