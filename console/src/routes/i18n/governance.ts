import { getLocale, t as mainT } from "../../i18n";
import en from "./governance.en.json";
import ko from "./governance.ko.json";

type Catalog = Record<string, unknown>;

const CATALOGS: Record<"en" | "ko", Catalog> = { en, ko };

function lookup(catalog: Catalog, key: string): string | undefined {
  let cursor: unknown = catalog;
  for (const part of key.replace(/^governance\./, "").split(".")) {
    if (typeof cursor !== "object" || cursor === null) return undefined;
    cursor = (cursor as Record<string, unknown>)[part];
  }
  return typeof cursor === "string" && cursor.length > 0 ? cursor : undefined;
}

function routeTemplate(key: string): string | undefined {
  return lookup(CATALOGS[getLocale()], key) ?? lookup(en, key);
}

export function t(key: string, params?: Record<string, string | number>): string {
  const template = routeTemplate(key) ?? mainT(key, params);
  if (params === undefined) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole,
  );
}

export function displayValue(group: string, value: string): string {
  return routeTemplate(`governance.display.${group}.${value}`) ?? value;
}

export function formatNumber(value: number): string {
  return value.toLocaleString(getLocale() === "ko" ? "ko-KR" : "en-US");
}
