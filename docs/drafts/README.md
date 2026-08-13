# drafts/

Working copies of text that is **published somewhere else**. Nothing in this
directory is documentation, and nothing here is read by the app or the build.

| Draft | Where it actually ships |
|---|---|
| `ai-transcribe-walkthrough.zh-TW.md` | `/guide/ai-transcribe` — text in `frontend/src/i18n/index.ts` (`walk`) |

Why keep them at all: web copy is easier to write and review as Markdown than
as TypeScript string literals, and a screenshot-heavy page is easier to lay out
here first. Why they are quarantined: the moment a draft and its published
version disagree, **the published version wins** — and a draft sitting in
`docs/` looks authoritative when it is not. `docs/user-manual-slides*.md` is
what that looks like after a few releases.

Editing a draft changes nothing on the site. Someone has to carry it across.
