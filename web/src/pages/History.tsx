import { TopBar } from '../components/Bits';
import { timeOf } from '../lib/format';
import { BottomNav } from '../components/BottomNav';
import { useLive } from '../lib/events';
import './app.css';

export default function History() {
  const { live } = useLive();
  const items = [...(live?.timeline ?? [])].filter((t) => t.status === 'done').reverse();
  return (
    <div className="phone">
      <main className="phone-body">
        <TopBar title="This shift" sub="Everything EarShot did" />
        {items.length === 0 && <p className="empty-note">Nothing yet this shift.</p>}
        <ol className="history">
          {items.map((t) => (
            <li key={t.id}>
              <span className="muted small">{timeOf(t.ts)}</span>
              <span>{t.text}</span>
            </li>
          ))}
        </ol>
      </main>
      <BottomNav />
    </div>
  );
}
