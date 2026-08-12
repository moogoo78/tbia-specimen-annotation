/** public/og/<slug>.png for a route: "/" is home, "/story/begonia" is story-begonia.
 *  Shared so og-image.mjs (which writes the file) and prerender.mjs (which points
 *  og:image at it) can never disagree about the name. */
export const slugFor = (path) =>
  path === "/" ? "home" : path.replace(/^\//, "").replace(/\//g, "-");
