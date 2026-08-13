import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon } from "../design/Icon";

// One specimen, start to finish: find it, read its label, run the AI, check
// what it proposed. The companion to /guide — that page explains what an
// annotation *is*, this one shows a real one being made, so anything
// conceptual here is a link back rather than a second telling of it.
//
// Screenshots live in public/guide/ (served at /guide/*.png, alongside but
// unrelated to the /guide route). Prose is in i18n `walk.*` like Guide.tsx,
// so both languages come from one file. docs/drafts/ contains the Markdown the
// Chinese was written in — a convenience for drafting, not a source of truth:
// the i18n keys are what ships, and the draft is the copy that goes stale.

/** A screenshot with its caption. Width-capped and lazy: nine full-page PNGs
 *  is ~2.9MB, and a reader on step 1 should not pay for step 5's. */
function Shot({ src, alt }: { src: string; alt: string }) {
  return (
    <figure style={{ margin: "14px 0 18px" }}>
      <img src={src} alt={alt} loading="lazy" style={{
        width: "100%", maxWidth: "100%", display: "block",
        border: `1px solid ${t.border}`, background: t.panelAlt,
      }} />
      <figcaption style={{ fontSize: 11, color: t.fgSubtle, marginTop: 5 }}>{alt}</figcaption>
    </figure>
  );
}

function P({ children, strong }: { children: React.ReactNode; strong?: boolean }) {
  return (
    <p style={{
      fontSize: 13, lineHeight: 1.85, margin: "0 0 12px",
      color: strong ? t.fg : t.fgMuted, fontWeight: strong ? 600 : 400,
    }}>{children}</p>
  );
}

function Step({ n, title, children }: { n: string; title: string; children: React.ReactNode }) {
  return (
    <section id={`step-${n}`} style={{ marginBottom: 34, scrollMarginTop: 16 }}>
      <h2 style={{
        fontSize: 15, fontWeight: 600, margin: "0 0 10px", paddingBottom: 6,
        borderBottom: `1px solid ${t.borderSoft}`,
      }}>{title}</h2>
      {children}
    </section>
  );
}

/** Set aside from the prose because it is the one thing on the page a reader
 *  may see a *different* screen for than the screenshots show. */
function Note({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      display: "flex", gap: 8, padding: "9px 11px", margin: "0 0 12px",
      background: t.panelAlt, borderLeft: `2px solid ${t.warn}`,
    }}>
      <Icon name="alert" size={12} />
      <div style={{ fontSize: 12, color: t.fgMuted, lineHeight: 1.75 }}>{children}</div>
    </div>
  );
}

export function AiWalkthrough() {
  const { t: tr } = useTranslation();

  // Field names are code identifiers and stay verbatim in both languages; the
  // values are label text (also verbatim) except the one that describes rather
  // than quotes. Only the verdict column is prose.
  const checks: [string, React.ReactNode, string][] = [
    ["full_text", tr("walk.s4Full"), tr("walk.s4FullOk")],
    ["locality", "Chichibu, Chichibu City, Saitama Pref.", tr("walk.s4LocOk")],
    ["eventDate", "1920", tr("walk.s4DateOk")],
    ["taxonRank", "genus → species", tr("walk.s4RankOk")],
    ["annotationScientificName", <em>Rubus phoenicolasius</em>, tr("walk.s4NameOk")],
  ];

  return (
    <div style={{ flex: 1, overflow: "auto" }}>
      <div style={{ maxWidth: 760, margin: "0 auto", padding: "24px 24px 48px" }}>
        {/* The way back to the concepts. This page deliberately explains none of
            them, and the crumb is what says so — it puts the walkthrough
            underneath the guide rather than beside it. */}
        <nav style={{
          display: "flex", alignItems: "center", gap: 5,
          fontSize: 11, color: t.fgSubtle, margin: "0 0 10px",
        }}>
          <Link to="/guide" style={{ color: t.fgMuted, textDecoration: "none" }}>{tr("nav.guide")}</Link>
          <Icon name="caretR" size={9} />
          <span>{tr("walk.crumb")}</span>
        </nav>

        <h1 style={{ fontSize: 19, fontWeight: 600, margin: "0 0 8px" }}>{tr("walk.title")}</h1>
        <p style={{ fontSize: 13, color: t.fgMuted, lineHeight: 1.8, margin: "0 0 28px" }}>
          {tr("walk.lead")}
        </p>

        <Step n="1" title={tr("walk.s1Title")}>
          <P>{tr("walk.s1Body")}</P>
          <Shot src="/guide/island-step1-1-find.png" alt={tr("walk.capFind")} />
          <P>{tr("walk.s1Pick")}</P>
          <P>{tr("walk.s1Layout")}</P>
          <Shot src="/guide/island-step1-2-adjust-layout.png" alt={tr("walk.capLayout")} />
          <P>{tr("walk.s1After")}</P>
          <P>{tr("walk.s1Record")}</P>
        </Step>

        <Step n="2" title={tr("walk.s2Title")}>
          <P strong>{tr("walk.s2Body")}</P>
          <P>{tr("walk.s2Sizes")}</P>
          <Shot src="/guide/island-step1-3-ready.png" alt={tr("walk.capReady")} />
          <ul style={{ margin: "0 0 12px", paddingLeft: 18, fontSize: 13, color: t.fgMuted, lineHeight: 1.85 }}>
            <li>{tr("walk.s2Size1")}</li>
            <li>{tr("walk.s2Size2")}</li>
            <li>{tr("walk.s2Size3")}</li>
          </ul>
          <P>{tr("walk.s2Open")}</P>
          <Shot src="/guide/island-step1-4-label.png" alt={tr("walk.capLabel")} />
          <pre style={{
            fontFamily: t.mono, fontSize: 12, lineHeight: 1.7, margin: "0 0 12px",
            padding: "10px 12px", background: t.panelAlt, border: `1px solid ${t.borderSoft}`,
            overflowX: "auto",
          }}>{`Makino Herbarium  168800
Rubus phoenicolasius Maxim.
Chichibu, Chichibu City, Saitama Pref.
Date: 1920            (1971)
Coll.: Tomitaro MAKINO    Det.: Y. Momiyama`}</pre>
          <P>{tr("walk.s2Date")}</P>
        </Step>

        <Step n="3" title={tr("walk.s3Title")}>
          <P>{tr("walk.s3Modes")}</P>
          <P>{tr("walk.s3Demo")}</P>
          <P>{tr("walk.s3Go")}</P>
          <Shot src="/guide/island-step2-1-AI-select.png" alt={tr("walk.capSelect")} />
          <P>⚠️ {tr("walk.s3Cost")}</P>
          <Note>{tr("walk.s3Note")}</Note>
          <P>{tr("walk.s3Keep")}</P>
          <Shot src="/guide/island-step2-2-AI-start.png" alt={tr("walk.capStart")} />
          <P>{tr("walk.s3Done")}</P>
          <Shot src="/guide/island-step2-3-AI-done.png" alt={tr("walk.capDone")} />
        </Step>

        <Step n="4" title={tr("walk.s4Title")}>
          <P>{tr("walk.s4Body")}</P>
          <Shot src="/guide/island-step2-4-AI-values.png" alt={tr("walk.capValues")} />
          <P>{tr("walk.s4Legend")}</P>
          <div style={{ overflowX: "auto", margin: "0 0 14px" }}>
            <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 12 }}>
              <thead>
                <tr>
                  {[tr("walk.s4ColField"), tr("walk.s4ColValue"), tr("walk.s4ColOk")].map((h) => (
                    <th key={h} style={{
                      textAlign: "left", padding: "5px 8px", fontSize: 10, fontWeight: 600,
                      textTransform: "uppercase", letterSpacing: 0.4, color: t.fgMuted,
                      borderBottom: `1px solid ${t.border}`, whiteSpace: "nowrap",
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {checks.map(([field, value, ok]) => (
                  <tr key={field}>
                    <td style={{ padding: "6px 8px", borderBottom: `1px solid ${t.borderSoft}`, fontFamily: t.mono, fontSize: 11, whiteSpace: "nowrap" }}>{field}</td>
                    <td style={{ padding: "6px 8px", borderBottom: `1px solid ${t.borderSoft}` }}>{value}</td>
                    <td style={{ padding: "6px 8px", borderBottom: `1px solid ${t.borderSoft}`, color: t.fgMuted, whiteSpace: "nowrap" }}>{ok}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <P strong>{tr("walk.s4Trap")}</P>
          <P>{tr("walk.s4Fix")}</P>
        </Step>

        <Step n="5" title={tr("walk.s5Title")}>
          <P>{tr("walk.s5Body")}</P>
          <P>{tr("walk.s5Dash")}</P>
          <Shot src="/guide/island-step4-check.png" alt={tr("walk.capDash")} />
        </Step>

        <div style={{ marginTop: 30, paddingTop: 20, borderTop: `1px solid ${t.border}` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 12 }}>
            <Icon name="rows" size={13} />
            <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>{tr("walk.faqTitle")}</h2>
          </div>
          {[1, 2, 3].map((i) => (
            <div key={i} style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 3 }}>{tr(`walk.faqQ${i}`)}</div>
              <div style={{ fontSize: 12, color: t.fgMuted, lineHeight: 1.75 }}>{tr(`walk.faqA${i}`)}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
