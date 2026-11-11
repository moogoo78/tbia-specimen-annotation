import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import type { MediaSize } from "../api/types";
import { Button } from "./ui";

// A record's images, shared by the record page (a thumbnail grid) and the
// institution report (one large image to review a value against). Both read the
// same "open at" choice, so picking 2048px once holds everywhere.

// Remembered across records: someone reading labels wants the big one every
// time, and re-picking it on each record is the annoyance the setting removes.
const MEDIA_SIZE_KEY = "tbia.mediaSize";

function readSize(): string | null {
  try { return localStorage.getItem(MEDIA_SIZE_KEY); } catch { return null; }
}

/** The chosen rendition ladder entry, and the URLs a click should open. */
function useMediaSize(urls: string[], sizes?: MediaSize[]) {
  const ladder = sizes ?? [];
  const [pick, setPick] = useState<string | null>(readSize);
  const chosen = ladder.find((s) => s.size === pick) ?? ladder.find((s) => s.canonical) ?? null;
  const openUrls = chosen ? chosen.urls : urls;
  const choose = (size: string) => {
    setPick(size);
    try { localStorage.setItem(MEDIA_SIZE_KEY, size); } catch { /* per-viewer nicety only */ }
  };
  return { ladder, chosen, openUrls, choose };
}

function SizeLadder({ ladder, chosen, choose }: ReturnType<typeof useMediaSize>) {
  const { t: tr } = useTranslation();
  // Absent entirely for sources that publish one rendition — most of them.
  if (ladder.length <= 1) return null;
  return (
    <div style={{ marginTop: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 4, flexWrap: "wrap" }}>
        <span style={{ fontSize: 10, color: t.fgMuted }}>{tr("detail.openAt")}</span>
        {ladder.map((s) => (
          <Button key={s.size} small primary={chosen?.size === s.size} onClick={() => choose(s.size)}>
            {s.long_edge}px
          </Button>
        ))}
      </div>
      <div style={{ fontSize: 10, color: t.fgSubtle, marginTop: 3 }}>{tr("detail.openAtHint")}</div>
    </div>
  );
}

function NoMedia({ references }: { references?: string }) {
  const { t: tr } = useTranslation();
  return (
    <div style={{ fontSize: 11, color: t.fgSubtle }}>
      {tr("detail.noMedia")}
      {references && <div style={{ marginTop: 6 }}><a href={references} target="_blank" rel="noreferrer" style={{ color: t.accent, fontSize: 11 }}>references ↗</a></div>}
    </div>
  );
}

export function MediaGallery({ urls, sizes, references }: { urls: string[]; sizes?: MediaSize[]; references?: string }) {
  // What a click opens. The thumbnails always stay on the URL the export
  // shipped — the point of the picker is reading a label full-screen, and
  // rendering 4096px into a 120px tile would cost 750KB an image for nothing.
  const m = useMediaSize(urls, sizes);
  if (urls.length === 0) return <NoMedia references={references} />;
  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4 }}>
        {urls.slice(0, 6).map((u, i) => (
          <a key={i} href={m.openUrls[i] ?? u} target="_blank" rel="noreferrer" style={{ aspectRatio: "1", border: `1px solid ${t.border}`, overflow: "hidden", background: t.panelAlt }}>
            <img src={u} loading="lazy" style={{ width: "100%", height: "100%", objectFit: "cover" }}
              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
          </a>
        ))}
      </div>
      <SizeLadder {...m} />
    </>
  );
}

/** One image large enough to check a value against, with the record's other
 *  views as a strip beneath it. The large image is the export's own URL (what
 *  the page can afford to load for every record reviewed); a click opens the
 *  chosen rendition full size, exactly as the record page's thumbnails do. */
export function MediaViewer({ urls, sizes, references, height = 420 }: {
  urls: string[]; sizes?: MediaSize[]; references?: string; height?: number;
}) {
  const { t: tr } = useTranslation();
  const m = useMediaSize(urls, sizes);
  const [i, setI] = useState(0);
  const [broken, setBroken] = useState(false);
  // A new record starts on its first view.
  const sig = urls.join("|");
  useEffect(() => { setI(0); setBroken(false); }, [sig]);

  if (urls.length === 0) return <NoMedia references={references} />;
  const cur = Math.min(i, urls.length - 1);
  return (
    <div>
      <a href={m.openUrls[cur] ?? urls[cur]} target="_blank" rel="noreferrer" title={tr("report.openFull")}
        style={{
          display: "flex", alignItems: "center", justifyContent: "center", height,
          border: `1px solid ${t.border}`, background: t.panelAlt, overflow: "hidden",
        }}>
        {broken
          ? <span style={{ fontSize: 11, color: t.fgSubtle }}>{tr("report.imageFailed")}</span>
          : <img src={urls[cur]} alt="" style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }}
              onError={() => setBroken(true)} />}
      </a>
      {urls.length > 1 && (
        <div style={{ display: "flex", gap: 4, marginTop: 4, overflowX: "auto" }}>
          {urls.map((u, k) => (
            <button key={k} onClick={() => { setI(k); setBroken(false); }} style={{
              width: 56, height: 56, flexShrink: 0, padding: 0, cursor: "pointer", background: t.panelAlt,
              border: `2px solid ${k === cur ? t.accent : t.border}`, overflow: "hidden",
            }}>
              <img src={u} loading="lazy" alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }}
                onError={(e) => { (e.target as HTMLImageElement).style.visibility = "hidden"; }} />
            </button>
          ))}
        </div>
      )}
      <SizeLadder {...m} />
    </div>
  );
}
