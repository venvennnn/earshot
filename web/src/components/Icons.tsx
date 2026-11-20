/* Small stroke icons used across the app. 24px grid, currentColor. */
type IconProps = { size?: number };

const base = (size: number) => ({
  width: size,
  height: size,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
});

export const MicIcon = ({ size = 24 }: IconProps) => (
  <svg {...base(size)}>
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
  </svg>
);

export const EraserIcon = ({ size = 24 }: IconProps) => (
  <svg {...base(size)}>
    <path d="M4 15l9-9 6 6-7 7H8l-4-4zM9 19h11M9 10l6 6" />
  </svg>
);

export const PlusCircleIcon = ({ size = 24 }: IconProps) => (
  <svg {...base(size)}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 8v8M8 12h8" />
  </svg>
);

export const ListIcon = ({ size = 24 }: IconProps) => (
  <svg {...base(size)}>
    <rect x="5" y="3" width="14" height="18" rx="2" />
    <path d="M9 8h6M9 12h6M9 16h4" />
  </svg>
);

export const HomeIcon = ({ size = 24 }: IconProps) => (
  <svg {...base(size)}>
    <path d="M4 11l8-7 8 7v9a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1z" />
  </svg>
);

export const ClockIcon = ({ size = 24 }: IconProps) => (
  <svg {...base(size)}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3 2" />
  </svg>
);

export const ChevronRightIcon = ({ size = 20 }: IconProps) => (
  <svg {...base(size)}>
    <path d="M9 6l6 6-6 6" />
  </svg>
);

export const CheckIcon = ({ size = 16 }: IconProps) => (
  <svg {...base(size)}>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </svg>
);

export const SoundIcon = ({ size = 24 }: IconProps) => (
  <svg {...base(size)}>
    <circle cx="6" cy="12" r="2.2" fill="currentColor" stroke="none" />
    <path d="M11 8a6 6 0 0 1 0 8M15 5a10 10 0 0 1 0 14" />
  </svg>
);
