// Ported from the NatureDB mockup (naturedb-portal.zip / components.jsx).
export const t = {
  bg: "#f6f5f2",
  panel: "#ffffff",
  panelAlt: "#fbfaf7",
  border: "#d9d5cc",
  borderSoft: "#e5e2da",
  fg: "#1c1b18",
  fgMuted: "#5c5a54",
  fgSubtle: "#8a877f",
  accent: "oklch(0.48 0.09 240)",
  accentSoft: "oklch(0.94 0.02 240)",
  danger: "oklch(0.55 0.14 28)",
  ok: "oklch(0.55 0.10 150)",
  warn: "oklch(0.62 0.12 75)",
  mono: 'ui-monospace, "SF Mono", Menlo, Consolas, monospace',
  sans: '"Helvetica Neue", Helvetica, Arial, "PingFang TC", "Microsoft JhengHei", system-ui, sans-serif',
  row: 28,
};

// Bilingual tone per biological group (data values stay Chinese).
export const BIO_GROUP_TONE: Record<string, string> = {
  魚類: "oklch(0.58 0.10 230)",
  昆蟲: "oklch(0.56 0.10 60)",
  維管束植物: "oklch(0.60 0.09 140)",
  蕨類植物: "oklch(0.58 0.09 160)",
  苔蘚植物: "oklch(0.56 0.08 175)",
  鳥類: "oklch(0.58 0.10 30)",
  哺乳類: "oklch(0.54 0.07 40)",
  爬蟲類: "oklch(0.56 0.09 130)",
  兩棲類: "oklch(0.58 0.10 150)",
  藻類: "oklch(0.58 0.09 195)",
};

export function toneFor(group?: string | null): string {
  return (group && BIO_GROUP_TONE[group]) || "oklch(0.55 0.04 250)";
}
