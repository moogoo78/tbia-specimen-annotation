import { t } from "../design/tokens";

// A quoted citation, reproduced verbatim except that a bracketed URL — the
// digital object the source was scanned from — becomes a link. Shared by every
// page that shows provenance for curated text.
export function Citation({ text }: { text: string }) {
  const m = text.match(/\[(https?:\/\/[^\]\s]+)\]/);
  if (!m || m.index == null) return <>{text}</>;
  return (
    <>
      {text.slice(0, m.index)}
      <a href={m[1]} target="_blank" rel="noreferrer"
        style={{ color: t.accent, wordBreak: "break-all" }}>{m[1]}</a>
      {text.slice(m.index + m[0].length)}
    </>
  );
}
