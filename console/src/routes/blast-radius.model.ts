import { routeHref } from "../router";

export const BLAST_RADIUS_LINKS = ["contains", "depends_on", "attached_to"] as const;
export const DEFAULT_BLAST_RADIUS_LINKS: readonly string[] = ["contains", "depends_on"];

export interface BlastRadiusQuery {
  readonly target: string | null;
  readonly depth: number;
  readonly links: readonly string[];
  readonly architectureView: string | null;
}

export function blastRadiusQueryFromSearch(search: string): BlastRadiusQuery {
  const params = new URLSearchParams(search.replace(/^\?/, ""));
  const target = params.get("target")?.trim() || null;
  const rawDepth = Number(params.get("depth"));
  const depth = Number.isInteger(rawDepth) && rawDepth >= 1 && rawDepth <= 5 ? rawDepth : 2;
  const requestedLinks = [
    ...params.getAll("link"),
    ...(params.get("links")?.split(",") ?? []),
  ];
  const links = [...new Set(requestedLinks.map((value) => value.trim()).filter(
    (value) => BLAST_RADIUS_LINKS.includes(value as (typeof BLAST_RADIUS_LINKS)[number]),
  ))];
  return {
    target,
    depth,
    links: links.length > 0 ? links : DEFAULT_BLAST_RADIUS_LINKS,
    architectureView: params.get("view")?.trim() || null,
  };
}

export function blastRadiusHref(query: BlastRadiusQuery): string {
  return routeHref("blast-radius", {
    params: {
      target: query.target,
      depth: query.depth,
      links: query.links.join(","),
      view: query.architectureView,
    },
  });
}
