import { getLocale } from "../../i18n";
import en from "./live.messages.en.json";
import ko from "./live.messages.ko.json";

type Catalog = Record<string, unknown>;

const CATALOGS: Record<"en" | "ko", Catalog> = { en, ko };

function lookup(catalog: Catalog, key: string): string | undefined {
  let cursor: unknown = catalog;
  for (const part of key.replace(/^live\./, "").split(".")) {
    if (typeof cursor !== "object" || cursor === null) return undefined;
    cursor = (cursor as Record<string, unknown>)[part];
  }
  return typeof cursor === "string" ? cursor : undefined;
}

export function t(key: string, params?: Record<string, string | number>): string {
  const template = lookup(CATALOGS[getLocale()], key) ?? lookup(en, key) ?? key;
  if (params === undefined) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole,
  );
}
