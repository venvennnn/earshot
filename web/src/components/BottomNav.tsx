import { NavLink } from 'react-router-dom';
import { ClockIcon, HomeIcon, MicIcon } from './Icons';

const ITEMS = [
  { to: '/app', label: 'Home', icon: <HomeIcon />, end: true },
  { to: '/app/talk', label: 'Talk', icon: <MicIcon />, end: false },
  { to: '/app/history', label: 'History', icon: <ClockIcon />, end: false },
];

export function BottomNav() {
  return (
    <nav className="bottom-nav" aria-label="App">
      {ITEMS.map((i) => (
        <NavLink key={i.to} to={i.to} end={i.end} className={({ isActive }) => (isActive ? 'active' : '')}>
          {i.icon}
          <span>{i.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
