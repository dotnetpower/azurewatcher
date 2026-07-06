// strip-first-h1.mjs - remark plugin that removes a document's first H1
// when its text is identical to the front-matter `title`.
//
// Why: Starlight renders `frontmatter.title` as the page's H1 automatically.
// Our canonical docs at docs/roadmap/**/*.md still open with a Markdown
// `# Title` line so they read naturally in a plain-text viewer or on
// GitHub. Left as-is, the site shows both headings back-to-back. This
// plugin only strips the first H1 when it *matches* the front-matter
// title, so any content-bearing H1 (or a page that intentionally leads
// with a different heading) is left alone.
//
// This runs during Markdown rendering - after content sync - so it does
// not interfere with `docsSchema()` validation.

/**
 * @typedef {import('mdast').Root} MdastRoot
 * @typedef {import('mdast').Heading} MdastHeading
 * @typedef {import('mdast').PhrasingContent} PhrasingContent
 */

/** Flatten a heading's inline children into plain text. */
function headingText(heading) {
  /** @param {PhrasingContent[]} nodes */
  const collect = (nodes) =>
    nodes
      .map((n) => {
        if (n.type === "text" || n.type === "inlineCode") return n.value;
        if ("children" in n && Array.isArray(n.children)) return collect(n.children);
        return "";
      })
      .join("");
  return collect(heading.children).trim();
}

export function remarkStripFirstH1() {
  return (tree, file) => {
    const title = file.data.astro?.frontmatter?.title;
    if (typeof title !== "string" || title.trim().length === 0) return;

    const idx = tree.children.findIndex(
      (node) => node.type === "heading" && node.depth === 1,
    );
    if (idx === -1) return;

    const h1 = /** @type {MdastHeading} */ (tree.children[idx]);
    if (headingText(h1) !== title.trim()) return;

    tree.children.splice(idx, 1);
  };
}

export default remarkStripFirstH1;
