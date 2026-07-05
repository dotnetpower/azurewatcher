// @ts-check
import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";
import { remarkStripFirstH1 } from "./src/plugins/strip-first-h1.mjs";

// GitHub Pages project page: https://dotnetpower.github.io/aiopspilot/
// Overridable at build time via SITE_URL / BASE_PATH env vars so a fork can
// deploy under a different owner or path without editing this file.
//
// Base path defaults by environment:
//   - astro dev  (NODE_ENV=development) -> "/"          so localhost:4321/roadmap/ works
//   - astro build (NODE_ENV=production) -> "/aiopspilot" (GitHub Pages project page)
// An explicit BASE_PATH env always wins, so CI can override either way.
const SITE_URL = process.env.SITE_URL ?? "https://dotnetpower.github.io";
const IS_PROD = process.env.NODE_ENV === "production";
const BASE_PATH = process.env.BASE_PATH ?? (IS_PROD ? "/aiopspilot" : "/");

export default defineConfig({
  site: SITE_URL,
  base: BASE_PATH,
  trailingSlash: "ignore",
  // Starlight auto-renders `frontmatter.title` as the page H1. The source
  // Markdown under docs/roadmap/**/*.md keeps its own `# Title` line so it
  // reads naturally on GitHub, so left alone the site would show two H1s
  // back-to-back. remarkStripFirstH1 drops the first H1 iff it duplicates
  // the front-matter title; anything else is preserved.
  markdown: {
    remarkPlugins: [remarkStripFirstH1],
  },
  integrations: [
    starlight({
      title: "AIOpsPilot",
      description:
        "Autonomous cloud operations control plane — deterministic-first, event-driven, risk-gated.",
      // Browser language detection is Starlight's default behaviour when
      // multiple locales are configured. Users land on the closest match to
      // their Accept-Language header and can flip via the language switcher.
      defaultLocale: "root",
      locales: {
        root: { label: "English", lang: "en" },
        ko: { label: "\ud55c\uad6d\uc5b4", lang: "ko" },
      },
      social: [
        {
          icon: "github",
          label: "GitHub",
          href: "https://github.com/dotnetpower/aiopspilot",
        },
      ],
      sidebar: [
        {
          label: "Roadmap",
          autogenerate: { directory: "roadmap" },
        },
      ],
      editLink: {
        // "Edit this page" points at the canonical Markdown under
        // docs/roadmap/, not at the mounted symlink. Contributors land on
        // the source of truth.
        baseUrl: "https://github.com/dotnetpower/aiopspilot/edit/main/",
      },
    }),
  ],
});
