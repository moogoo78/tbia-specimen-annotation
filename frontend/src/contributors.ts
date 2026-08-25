// How a contributor is named on screen.
//
// A name is published only if its owner opted in (`users.show_in_ranking`), and
// the server applies that rule before answering — `models.public_name`. So a
// null name here means "not for publication", never "no contributor": the id
// always comes back, and this is what turns it into the same "Unnamed
// contributor #<id>" the ranking has always shown.
//
// One function because five places name a contributor — the ranking, the home
// board, the dashboard's annotation list, a record's annotation history and its
// transcription queue line. Each used to build the string itself, which is how
// the opt-out came to cover only the first two.

/** `t` from `useTranslation()`; typed loosely so this module stays i18n-free. */
type Translate = (key: string) => string;

export function contributorLabel(
  tr: Translate,
  name: string | null | undefined,
  id?: number | null,
): string {
  if (name) return name;
  const anon = tr("vol.anonymous");
  return id == null ? anon : `${anon} #${id}`;
}

/** True when the label above is standing in for a withheld name — the callers
 *  that style it (muted, italic) and explain it (`vol.anonymousHint`). */
export function isAnonymous(name: string | null | undefined): boolean {
  return !name;
}
