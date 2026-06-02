// Tiny outline icon set, ported from the mockup.
export const Icons = {
  search: "M7 2a5 5 0 1 1 0 10 5 5 0 0 1 0-10Zm7 12l-3.2-3.2",
  caretD: "M3.5 6l4.5 4 4.5-4",
  caretR: "M6 3.5L10 8l-4 4.5",
  caretU: "M3.5 10l4.5-4 4.5 4",
  plus: "M8 3v10M3 8h10",
  x: "M3.5 3.5l9 9M12.5 3.5l-9 9",
  filter: "M2 3h12l-4.5 6v4l-3 1.5V9L2 3Z",
  pin: "M8 1.5v7M3 8.5h10l-5 6-5-6Z",
  grid: "M2.5 2.5h4v4h-4zM9.5 2.5h4v4h-4zM2.5 9.5h4v4h-4zM9.5 9.5h4v4h-4z",
  rows: "M2 3.5h12M2 8h12M2 12.5h12",
  map: "M2 3l4-1 4 2 4-1v11l-4 1-4-2-4 1V3zM6 2v11M10 4v11",
  img: "M2 3h12v10H2zM2 10l4-3 3 2 5-4",
  split: "M2 2.5h12v11H2zM7 2.5v11",
  down: "M8 2v9M4 7.5L8 11.5 12 7.5M2 14h12",
  check: "M2 8.5l3.5 3.5L14 4",
  alert: "M8 1.5l6.5 11.5H1.5L8 1.5ZM8 6v3.5M8 11.2v.2",
  spark: "M8 1.5l1.4 4.6 4.6 1.4-4.6 1.4L8 13.5 6.6 8.9 2 7.5l4.6-1.4L8 1.5Z",
  user: "M8 8.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5ZM3 14c.6-2.5 2.6-4 5-4s4.4 1.5 5 4",
  cog: "M8 5.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5Zm0-4v2M8 12.5v2M2 8h2M12 8h2M3.8 3.8l1.4 1.4M10.8 10.8l1.4 1.4M3.8 12.2l1.4-1.4M10.8 5.2l1.4-1.4",
  globe: "M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13ZM1.5 8h13M8 1.5c1.8 1.7 2.8 4 2.8 6.5S9.8 12.8 8 14.5C6.2 12.8 5.2 10.5 5.2 8S6.2 3.2 8 1.5Z",
  back: "M10 3.5L5.5 8 10 12.5",
};

type IconName = keyof typeof Icons;

export function Icon({ name, size = 14, stroke = 1.4 }: { name: IconName; size?: number; stroke?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor"
      strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
      <path d={Icons[name]} />
    </svg>
  );
}
