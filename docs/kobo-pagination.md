# Kobo (RMSDK) pagination bugs

Symptom: on a Kobo reading a plain `.epub` (Adobe RMSDK, not kepub), some pages repeat lines from
the previous page, lose lines, or a page turn shows the same page again. It starts at a certain
point of a chapter file and carries on from there until the next file.

## Cause found: `<br>` with `display: block`

Calibre conversions give `<br>` a class that only sets `display: block` (`.calibre5 { display:
block }`, sometimes with `line-height`). RMSDK measures a block `<br>` differently when laying out
the pages than when drawing them, so every page after one is off by a line.

Where it shows up:

| Book | Where | Count |
|---|---|---|
| The Nature of Code (Calibre) | `line<br/>` inside `<pre>` code blocks | (fixed in the first version) |
| The Nature of Code (Calibre) | inline code and formulas in `<p>`, outside `<pre>` | 258 |
| No tengo boca y debo gritar (Calibre 9.16, from an epubgratis book) | blank-line paragraphs `<p class="calibre1"><br class="calibre5"/></p>`, the whole story is one 41 KB file | 3 |

The first version only fixed `<br>` inside `<pre>`, so the second book kept repeating pages.

**Not verified on a device from here**: the diagnosis comes from the markup the two books share
and from the `<pre>` fix having worked. Confirm on the Kobo after each new fix.

## Fix adopted (`clean` step, `fix_block_breaks`)

Every `<br>` that some rule gives a display other than `inline`/`none` gets
`style="display: inline"`. The inline style wins over the class and keeps the class's other
properties.

Which rules count: the subject of each selector (the last compound, after the last combinator) is
`br` or has a class the `<br>` has. Rules inside `@media`/`@supports` count. A `<style>` element
only counts for its own document. Selectors for pseudo-elements (`::after`, `:before`) are
ignored, since they don't style the `<br>` itself.

## Discarded

- **Deleting `display` from the CSS rule.** In The Nature of Code, `.calibre5` is also used by two
  `<div>`s. Harmless there (a `<div>` is a block anyway), but the same class on a `<span>` or
  `<img>` would change the layout.
- **Removing the class from the `<br>`.** Also drops its other properties, like
  `.calibre22 { display: block; line-height: 1.2 }` in The Nature of Code.
- **Adding `br { display: inline }` to the stylesheet.** It loses to `.calibre5` on specificity.
  `br[class]` would win, but attribute selectors in RMSDK aren't reliable enough to bet on.
- **Turning `<br>` with `display: none` inline.** Could be the book hiding the line break on
  purpose: these are left alone, even if another class sets `display: block`.

## Other suspects, if pages still repeat

Not changed, because no book has shown them to be a problem yet:

- Calibre's `page_styles.css` with `@page { margin-top: 5pt; margin-bottom: 5pt }`, on top of
  Kobo's own margins.
- Kobo's built-in `body { padding-bottom: <one line> !important }` can push the last line of a
  chapter onto a new page. It can't be overridden from the book (the reader's `!important` wins).
- `line-height` in paragraph rules combined with inline elements with a bigger `font-size`.
