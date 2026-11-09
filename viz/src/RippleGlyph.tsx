export function RippleGlyph({ size = 18 }: { size?: number }) {
  return (
    <svg aria-hidden="true" width={size} height={size} viewBox="0 0 44 44" fill="none" focusable="false">
      <circle cx="22" cy="22" r="14" stroke="currentColor" strokeWidth="1.8" />
      <path d="M3 22h8M33 22h8M22 3v8M22 33v8" stroke="#B44D3C" strokeWidth="2.4" strokeLinecap="round" />
      <circle cx="22" cy="22" r="4.8" fill="#B44D3C" />
      <circle cx="22" cy="22" r="1.5" fill="#F4F1EA" />
    </svg>
  );
}
