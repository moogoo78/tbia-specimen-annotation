import { useEffect } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon, type IconName } from "../design/Icon";
import { CompletenessDots, StatusPill } from "../components/ui";
import { exploreUrl } from "./exploreUrl";

// The user manual, in the product. Long-form version of the home page's
// Get-started strip: the four steps of the contribution loop, then tips and
// FAQ. Prose lives in i18n (`guide.*`) so it stays bilingual — the source is
// docs/user-manual-slides{,.zh-TW}.md; keep the decks and these keys in step.
export function Guide() {
  const { t: tr } = useTranslation();
  const nav = useNavigate();
  const { hash } = useLocation();

  // Router navigation doesn't honour a hash on its own, so scroll to the
  // linked step ourselves (the home cards deep-link to /guide#step-3).
  useEffect(() => {
    if (!hash) return;
    document.getElementById(hash.slice(1))?.scrollIntoView({ block: "start" });
  }, [hash]);

  const gaps = (only: "id" | "geo" | "date" | "media") => ({
    has_identification: only === "id", has_coordinates: only === "geo",
    has_date: only === "date", has_media: only === "media",
  });

  return (
    <div style={{ flex: 1, overflow: "auto" }}>
      <div style={{ maxWidth: 760, margin: "0 auto", padding: "24px 24px 48px" }}>
        <h2 style={{ fontSize: 18, fontWeight: 600, margin: "0 0 8px" }}>{tr("guide.title")}</h2>
        <p style={{ fontSize: 13, color: t.fgMuted, lineHeight: 1.7, margin: "0 0 24px" }}>{tr("guide.lead")}</p>

        {/* 這是什麼平台 */}
        <Heading icon="globe" text={tr("guide.whatTitle")} />
        <Bullets items={[tr("guide.what1"), tr("guide.what2"), tr("guide.what3"), tr("guide.what4")]} />
        <p style={{
          fontSize: 12, color: t.fg, lineHeight: 1.7, margin: "10px 0 24px",
          borderLeft: `2px solid ${t.accent}`, paddingLeft: 10,
        }}>{tr("guide.goal")}</p>

        {/* 為什麼缺漏很重要 */}
        <Heading icon="alert" text={tr("guide.scoreTitle")} />
        <p style={{ fontSize: 12, color: t.fgMuted, lineHeight: 1.7, margin: "0 0 10px" }}>{tr("guide.scoreIntro")}</p>
        <div style={{ background: t.panel, border: `1px solid ${t.border}`, marginBottom: 10 }}>
          {([["id", "scoreId"], ["geo", "scoreGeo"], ["date", "scoreDate"], ["media", "scoreMedia"]] as const).map(([k, label]) => (
            <div key={k} style={{
              display: "flex", alignItems: "center", gap: 10, padding: "7px 10px",
              borderBottom: `1px solid ${t.borderSoft}`, fontSize: 12,
            }}>
              <CompletenessDots row={gaps(k)} size={8} />
              <span style={{ color: t.fgMuted }}>{tr(`guide.${label}`)}</span>
            </div>
          ))}
        </div>
        <p style={{ fontSize: 12, color: t.fgMuted, lineHeight: 1.7, margin: "0 0 28px" }}>{tr("guide.scoreNote")}</p>

        {/* 1 · 登入 */}
        <StepBlock n={1} icon="user" title={tr("guide.step1Title")} body={tr("guide.step1Body")}>
          <Bullets items={[tr("guide.step1b1"), tr("guide.step1b2"), tr("guide.step1b3"), tr("guide.step1b4")]} />
        </StepBlock>

        {/* 2 · 找出缺漏 */}
        <StepBlock n={2} icon="search" title={tr("guide.step2Title")} body={tr("guide.step2Body")}>
          <Bullets items={[tr("guide.step2b1"), tr("guide.step2b2"), tr("guide.step2b3"), tr("guide.step2b4")]} />
          <button
            onClick={() => nav(exploreUrl({ flags: { missing_identification: true, has_media: true } }))}
            style={{
              marginTop: 10, display: "inline-flex", alignItems: "center", gap: 6, padding: "5px 10px",
              background: t.panelAlt, border: `1px solid ${t.border}`, cursor: "pointer",
              fontFamily: t.sans, fontSize: 12, color: t.fg,
            }}
          >
            <Icon name="search" size={12} />{tr("guide.step2Cta")}<Icon name="caretR" size={10} />
          </button>
        </StepBlock>

        {/* 3 · 補齊缺漏 */}
        <StepBlock n={3} icon="spark" title={tr("guide.step3Title")} body={tr("guide.step3Body")}>
          <Bullets items={[tr("guide.step3b1"), tr("guide.step3b2"), tr("guide.step3b3"), tr("guide.step3b4")]} />

          <SubHeading text={tr("guide.step3SuggestTitle")} />
          <Bullets items={[tr("guide.step3Suggest1"), tr("guide.step3Suggest2"), tr("guide.step3Suggest3"), tr("guide.step3Suggest4")]} />

          <SubHeading text={tr("guide.step3AiTitle")} />
          <p style={{ fontSize: 12, color: t.fgMuted, lineHeight: 1.7, margin: "0 0 8px" }}>{tr("guide.step3AiIntro")}</p>
          <Option n={1} text={tr("guide.step3AiPlatform")} />
          <Option n={2} text={tr("guide.step3AiOwn")} />
          <p style={{ fontSize: 12, color: t.fgMuted, lineHeight: 1.7, margin: "8px 0 0" }}>{tr("guide.step3AiUse")}</p>
          <p style={{
            fontSize: 12, color: t.fg, lineHeight: 1.7, margin: "10px 0 0",
            borderLeft: `2px solid ${t.warn}`, paddingLeft: 10,
          }}>{tr("guide.step3AiWarn")}</p>
          {/* The worked example. Kept as a link rather than folded in: this
              page is the reference, and a five-screenshot walkthrough of one
              specimen would bury the other three steps. */}
          <Link to="/guide/ai-transcribe" style={{
            display: "inline-flex", alignItems: "center", gap: 6, marginTop: 12,
            fontSize: 12, fontWeight: 600, color: t.accent, textDecoration: "none",
          }}>
            <Icon name="spark" size={12} />{tr("guide.step3AiWalk")}<Icon name="caretR" size={10} />
          </Link>
        </StepBlock>

        {/* 4 · 送出與回饋 */}
        <StepBlock n={4} icon="check" title={tr("guide.step4Title")} body={tr("guide.step4Body")}>
          <div style={{ border: `1px solid ${t.borderSoft}`, marginBottom: 10 }}>
            {(["draft", "submitted", "accepted", "rejected", "merged"] as const).map((s) => (
              <div key={s} style={{
                display: "flex", alignItems: "baseline", gap: 10, padding: "6px 10px",
                borderBottom: `1px solid ${t.borderSoft}`, fontSize: 12,
              }}>
                <span style={{ width: 92, flexShrink: 0 }}><StatusPill status={s} /></span>
                <span style={{ color: t.fgMuted, lineHeight: 1.6 }}>
                  {tr(`guide.step4${s.charAt(0).toUpperCase()}${s.slice(1)}`)}
                </span>
              </div>
            ))}
          </div>
          <Bullets items={[tr("guide.step4Source"), tr("guide.step4Dash")]} />
        </StepBlock>

        {/* 實用訣竅 */}
        <Heading icon="spark" text={tr("guide.tipsTitle")} />
        <Bullets items={[tr("guide.tip1"), tr("guide.tip2"), tr("guide.tip3"), tr("guide.tip4"), tr("guide.tip5")]} />

        {/* 常見問題 */}
        <div style={{ marginTop: 28 }}>
          <Heading icon="rows" text={tr("guide.faqTitle")} />
          {[1, 2, 3, 4].map((i) => (
            <div key={i} style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 3 }}>{tr(`guide.faqQ${i}`)}</div>
              <div style={{ fontSize: 12, color: t.fgMuted, lineHeight: 1.7 }}>{tr(`guide.faqA${i}`)}</div>
            </div>
          ))}
        </div>

        {/* 收尾 */}
        <div style={{
          marginTop: 32, paddingTop: 20, borderTop: `1px solid ${t.border}`,
        }}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 6 }}>{tr("guide.closing")}</div>
          <p style={{ fontSize: 12, color: t.fgMuted, lineHeight: 1.7, margin: "0 0 14px", maxWidth: 620 }}>
            {tr("guide.closingNote")}
          </p>
          <button onClick={() => nav("/explore")} style={{
            display: "inline-flex", alignItems: "center", gap: 6, padding: "8px 16px",
            background: t.fg, color: t.bg, border: "none", cursor: "pointer",
            fontFamily: t.sans, fontSize: 13, fontWeight: 600,
          }}>
            <Icon name="search" size={13} />{tr("home.startExploring")}<Icon name="caretR" size={11} />
          </button>
        </div>
      </div>
    </div>
  );
}

// One numbered step, anchored so the home page can deep-link to it. The number
// badge matches the one in the record's annotation panel (RecordDetail's
// OptionCard), so a step reads the same wherever it appears.
function StepBlock({ n, icon, title, body, children }: {
  n: number; icon: IconName; title: string; body: string; children: React.ReactNode;
}) {
  return (
    <div id={`step-${n}`} style={{
      background: t.panel, border: `1px solid ${t.border}`, padding: "14px 16px", marginBottom: 14,
      scrollMarginTop: 12,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <span style={{
          flexShrink: 0, width: 20, height: 20, display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 11, fontFamily: t.mono, color: t.bg, background: t.fg,
        }}>{n}</span>
        <Icon name={icon} size={14} />
        <h3 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>{title}</h3>
      </div>
      <p style={{ fontSize: 12, color: t.fgMuted, lineHeight: 1.7, margin: "0 0 8px" }}>{body}</p>
      {children}
    </div>
  );
}

function Heading({ icon, text }: { icon: IconName; text: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 7, margin: "0 0 10px" }}>
      <Icon name={icon} size={14} />
      <h3 style={{ fontSize: 15, fontWeight: 600, margin: 0 }}>{text}</h3>
    </div>
  );
}

function SubHeading({ text }: { text: string }) {
  return <div style={{ fontSize: 12, fontWeight: 600, margin: "14px 0 6px" }}>{text}</div>;
}

function Bullets({ items }: { items: string[] }) {
  return (
    <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 5 }}>
      {items.map((it, i) => (
        <li key={i} style={{ fontSize: 12, color: t.fgMuted, lineHeight: 1.7 }}>{it}</li>
      ))}
    </ul>
  );
}

// The two AI routes — numbered, since the UI presents them as option 1 / 2.
function Option({ n, text }: { n: number; text: string }) {
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "baseline", marginTop: 6 }}>
      <span style={{ fontFamily: t.mono, fontSize: 11, color: t.accent, flexShrink: 0 }}>{n}.</span>
      <span style={{ fontSize: 12, color: t.fgMuted, lineHeight: 1.7 }}>{text}</span>
    </div>
  );
}
