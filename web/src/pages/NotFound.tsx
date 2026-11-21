import { Link, useLocation } from 'react-router-dom';
import { Logo } from '../components/Logo';

/** Shown for unknown URLs. */
export default function NotFound() {
  const { pathname } = useLocation();
  return (
    <main style={{ padding: 24, maxWidth: 480, margin: '0 auto', display: 'grid', gap: 16 }}>
      <Logo />
      <h1 style={{ fontSize: 22 }}>Page not found</h1>
      <p style={{ color: 'var(--muted)' }}>
        <span className="mono">{pathname}</span> doesn't exist.
      </p>
      <Link className="btn" to="/app">Back to the app</Link>
    </main>
  );
}
