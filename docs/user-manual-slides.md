---
title: TBIA Specimen Annotation — User Manual
tags: manual, tbia, guide
type: slide
slideOptions:
  theme: white
  transition: slide
  center: false
---

<!-- .slide: style="text-align:center" -->

# 🔬 TBIA Specimen Annotation Platform

### User Manual — for general users

Closing gaps in natural-history specimen metadata

<small>Explore records · fill the gaps · help data get better</small>

Note:
Speaker notes are visible in presentation mode (press `s`). This deck is a walkthrough for everyday contributors, not admins.

---

## What is this platform?

A collaborative workspace for **Taiwan Biodiversity Information Alliance (TBIA)** specimen records.

- Millions of occurrence records are **read-only** here — we never edit the originals
- Many records have **gaps**: no identification, no coordinates, no date, no image
- You add the missing pieces as **annotations**
- Reviewed annotations are **exported back** to the data providers

> Your goal: find a record with a gap, and fill it. 🧩

----

### Why gaps matter

Each record gets a **completeness score (0–4)**, one point each for:

| Flag | Meaning |
|------|---------|
| 🧬 Identification | Has a scientific name / species-level ID |
| 📍 Coordinates | Has latitude & longitude |
| 📅 Date | Has a collection date |
| 🖼️ Media | Has at least one image |

Records are shown **gaps-first** by default, so the work that matters most is on top.

---

## 1 · Signing in

Sign-in is **ORCID-only** — no separate password to remember.

1. Click **Sign in** (top-right)
2. Click **Sign in with ORCID**
3. You're sent to **orcid.org** — approve access
4. You land back here, signed in ✅

<small>No ORCID iD yet? Register free at **orcid.org/register** — it's the standard researcher identifier.</small>

Note:
ORCID is an OAuth flow: the platform never sees your ORCID password. First sign-in automatically creates your account as a "contributor".

----

### What is ORCID?

**ORCID** = a free, unique ID for researchers (like `0000-0002-1825-0097`).

- Used across journals, grants, and data repositories
- Here it's both your **login** and your **contributor identity**
- Your annotations are credited to your ORCID iD

You can browse **without** signing in — but you must sign in to **annotate**.

---

## 2 · The Explore page

This is where you find records. Four zones:

- 🔎 **Search bar** — free-text across taxon, locality, collector, catalog #
- ⬅️ **Filters panel** — narrow by group, place, completeness, and more
- 🔀 **View switcher** — Table · Grid · Split · Map
- ↕️ **Sort** — defaults to *completeness ascending* (gaps first)

Note:
Everything updates live as you change filters. The active filters appear as removable chips under the search bar.

---

## 3 · Searching

Type in the search bar and results update.

Search matches on:

- **Scientific name** (e.g. *Pocillopora*)
- **Locality** (e.g. 野柳, Kenting)
- **Collector** name
- **Catalog number**

<small>💡 Data values stay in their original language (Chinese taxonomy & place names). Only the interface is bilingual.</small>

---

## 4 · Filtering

Open **FILTERS** to narrow the list. Key filters:

----

### Completeness filters (the important ones)

Show only records **missing** what you can help with:

- ☐ **Missing coordinates**
- ☐ **Missing date**
- ☐ **Missing identification**
- ☐ **Has images** — so you can transcribe from the label

> Tip: turn on *Has images* + *Missing identification* to find specimens you can identify from the photo.

----

### Other filters

- **Collection institution** — the source (institution / aggregator)
- **Biological group** & **Kingdom** — e.g. birds, plants, insects
- **County** — where it was collected
- **Taxon rank**, **Basis of record**, **Type status**
- **Holding institution**
- **Collector** — search a person, or "show all records by this collector"
- **Record number** & **year** ranges

<small>Selected filters show as chips — click ✕ on a chip (or **clear**) to remove.</small>

---

## 5 · View modes

Pick the layout that fits your task:

| View | Best for |
|------|----------|
| **Table** | Scanning many records + their gaps |
| **Grid** | Browsing specimen images |
| **Split** | List on one side, record open on the other |
| **Map** | Seeing where records are (and spotting gaps) |

Note:
The Gaps column in Table view shows at a glance which of the four pieces are missing. Map view loads more points at once.

---

## 6 · Opening a record

Click any record to see its detail, grouped into:

- **Taxonomy** — names & classification
- **Collection event** — collector, date, locality, coordinates, elevation
- **Record metadata** — catalog #, institution, basis of record…
- **Media** — specimen images (if any)
- **Annotations** — proposed additions & their status

Missing fields are clearly marked **missing** — those are your targets. 🎯

---

## 7 · Filling the gaps (annotating)

In the record's **"Fill the gaps"** panel:

1. Choose the **Field** you want to complete (e.g. Coordinates)
2. Enter a **Proposed value**
3. Add an optional **Note** (your reasoning / source)
4. Click **Submit annotation** — or **Save draft** to finish later

You must be **signed in** to do this.

Note:
A draft is private-ish and editable; submitting sends it into the review queue. Always cite your source in the note when you can.

----

### ✍️ Annotation = a suggestion, not an edit

- The original record is **never overwritten**
- Your annotation is a **proposed value** attached to it
- A reviewer decides whether it's accepted
- Accepted values are what gets **returned to the provider**

This keeps the source data safe while letting the community improve it.

---

## 8 · AI-assisted transcription

For records **with a label image**, you can get a head start:

1. Click **AI extract from image**
2. The system reads the label and proposes values, each with a **confidence** score
3. **Review carefully**, click **Use** to apply a suggestion into a field
4. Edit if needed, then **Submit**

> ⚠️ The AI is an assistant, not the author. **You** are responsible for what you submit.

Note:
AI output is a starting draft. Low-confidence fields especially need human checking before submitting.

---

## 9 · What happens to my annotation?

Every annotation moves through statuses:

| Status | Meaning |
|--------|---------|
| **Draft** | Saved, not yet submitted |
| **Submitted** | In the review queue |
| **Accepted** | A reviewer approved it |
| **Rejected** | Not approved (see the note) |
| **Merged** | Packaged to return to the provider |

<small>Contributors create Drafts/Submitted. Reviewers Accept / Reject / Mark merged.</small>

---

## 10 · The Dashboard

**Contributions & feedback loop** — see the impact:

- **By status** — how many draft / submitted / accepted…
- **By institution** — records, % identified / georeferenced / dated / with media, avg completeness
- **My annotations** vs **All annotations**
- **Pending review** count
- **Export deltas** — reviewed changes ready to return to providers

Note:
This closes the loop the project is named for — improvements flow back to the original data providers.

---

## 11 · Institutions & language

**Institutions page** — browse collection institutions, their datasets and record counts, and jump into their records.

**Language** — the interface is bilingual:

- 🇬🇧 English / 🇹🇼 中文 (zh-TW)
- Toggle in the header; data values stay in their original language

---

## Quick tips 💡

- Start from **Missing identification + Has images** for the highest-value work
- Use the **Note** field to record your **source** — reviewers rely on it
- **Save draft** if you're unsure; come back later
- The **Gaps** column tells you what's missing before you even open a record
- Sort stays **gaps-first** — the top of the list always needs you most

---

## Frequently asked

**Do I need an account to look around?**
No — browsing is open. Sign in only to annotate.

**Will I change the original data?**
Never. You add suggestions; providers get reviewed results.

**I don't have an ORCID iD.**
Register free at **orcid.org/register**, then sign in.

**Can I fix my own submission?**
Edit while it's a **draft**; after submitting, a reviewer handles it.

---

<!-- .slide: style="text-align:center" -->

## 🙏 Thank you for contributing

Every gap you close makes Taiwan's biodiversity data more usable
for research, conservation, and education.

### Find a gap → fill it → help it flow back

<small>TBIA Specimen Annotation Platform · *Closing Gaps in Specimen Metadata*</small>
