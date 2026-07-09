/**
 * LlmNarrator - an OpenAI-compatible model as the console narrator.
 *
 * Understands free-form natural language (any language, including Korean) and
 * calls the read-only `console-tool`s to ground its answer. It is a translator,
 * not a judge: the system prompt forbids inventing numbers and forbids taking
 * actions (the console is read-only). One tool round is executed, then the model
 * answers from the tool results.
 *
 * Works with OpenAI (`Authorization: Bearer <key>`) and Azure OpenAI. For Azure
 * it authenticates either with an API key (`api-key` header) or, keyless, with
 * an Azure AD bearer token minted from the operator's existing `az login`
 * (`az account get-access-token`) - so natural language works with zero secrets
 * in the environment. Configured from env or `resolved-models.json` - see
 * `createNarrator`.
 */

import { execFile } from "node:child_process";
import { promisify } from "node:util";

import { CLI_CONSOLE_TOOLS, CONSOLE_TOOLS, runTool } from "./tools.js";
import { loadBaseNarratorPrompt, loadCliNarratorPrompt } from "./prompt-store.js";
import type { ConsoleTool, Narrator, NarratorContext } from "./types.js";
import type { Locale } from "../i18n/index.js";

/**
 * L3 render directive: instruct the model to answer in the operator locale
 * while keeping the English pipeline (ids, numbers, tool output) verbatim.
 * The directive itself is an English machine instruction (a prompt is L0
 * config), naming only the target language.
 */
export function localeDirective(locale: Exclude<Locale, "en">): string {
  const language: Record<Exclude<Locale, "en">, string> = { ko: "Korean" };
  return (
    `Respond to the operator in ${language[locale]}. ` +
    `Keep all numbers, identifiers, resource names, and quoted tool output ` +
    `exactly as provided - do not translate or reformat them.`
  );
}

export interface LlmConfig {
  provider: "openai" | "azure";
  baseUrl: string;
  apiKey: string;
  model: string;
  apiVersion: string;
  /** How to authenticate. `azure-ad` mints a token from `az login` per request. */
  auth: "api-key" | "azure-ad";
}

const execFileAsync = promisify(execFile);

// Azure AD (Entra) resource for the Azure OpenAI data plane. Public, identical
// for every tenant - not a customer-identifying value.
const AAD_AOAI_RESOURCE = "https://cognitiveservices.azure.com";

let tokenCache: { token: string; expiresAt: number } | null = null;

/** Mint an Azure AD bearer token from the operator's `az login`, cached until
 * shortly before expiry. Requires the Azure CLI to be installed and logged in. */
async function azureAdToken(): Promise<string> {
  const now = Date.now();
  if (tokenCache && tokenCache.expiresAt - 60_000 > now) return tokenCache.token;
  let stdout: string;
  try {
    ({ stdout } = await execFileAsync(
      "az",
      [
        "account",
        "get-access-token",
        "--resource",
        AAD_AOAI_RESOURCE,
        "--query",
        "accessToken",
        "-o",
        "tsv",
      ],
      { timeout: 20_000 },
    ));
  } catch (err) {
    throw new Error(
      `could not get an Azure AD token via 'az' (run 'az login'): ${(err as Error).message}`,
    );
  }
  const token = stdout.trim();
  if (!token) throw new Error("'az account get-access-token' returned no token (run 'az login')");
  // az tokens are typically valid ~60-90 min; cache conservatively for 50.
  tokenCache = { token, expiresAt: now + 50 * 60_000 };
  return token;
}

interface ToolCall {
  id: string;
  type: "function";
  function: { name: string; arguments: string };
}

interface ChatMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string | null;
  tool_calls?: ToolCall[];
  tool_call_id?: string;
}

interface ChatResponse {
  choices: Array<{ message: ChatMessage }>;
}

export class LlmNarrator implements Narrator {
  readonly kind = "llm";

  constructor(private readonly cfg: LlmConfig) {}

  private url(): string {
    if (this.cfg.provider === "azure") {
      const base = this.cfg.baseUrl.replace(/\/$/, "");
      return (
        `${base}/openai/deployments/${this.cfg.model}/chat/completions` +
        `?api-version=${this.cfg.apiVersion}`
      );
    }
    return `${this.cfg.baseUrl.replace(/\/$/, "")}/chat/completions`;
  }

  private async headers(): Promise<Record<string, string>> {
    const common = { "content-type": "application/json" };
    if (this.cfg.provider === "azure") {
      if (this.cfg.auth === "azure-ad") {
        return { ...common, authorization: `Bearer ${await azureAdToken()}` };
      }
      return { ...common, "api-key": this.cfg.apiKey };
    }
    return { ...common, authorization: `Bearer ${this.cfg.apiKey}` };
  }

  private async post(
    messages: ChatMessage[],
    tools: readonly ConsoleTool[] | null,
  ): Promise<ChatMessage> {
    const body: Record<string, unknown> = { messages, temperature: 0 };
    if (this.cfg.provider === "openai") body.model = this.cfg.model;
    if (tools) {
      body.tools = tools.map((t) => ({
        type: "function",
        function: {
          name: t.name,
          description: t.description,
          parameters: t.parameters,
        },
      }));
      body.tool_choice = "auto";
    }
    const res = await fetch(this.url(), {
      method: "POST",
      headers: await this.headers(),
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const detail = (await res.text()).slice(0, 200);
      throw new Error(`narrator model ${res.status} ${res.statusText}: ${detail}`);
    }
    const data = (await res.json()) as ChatResponse;
    const message = data.choices[0]?.message;
    if (!message) throw new Error("narrator model returned no choices");
    return message;
  }

  async answer(query: string, ctx: NarratorContext): Promise<string> {
    const cli = !!ctx.screen;
    const tools = cli ? CLI_CONSOLE_TOOLS : CONSOLE_TOOLS;
    const systemPrompt = cli ? loadCliNarratorPrompt() : loadBaseNarratorPrompt();
    const locale = ctx.locale ?? "en";
    const messages: ChatMessage[] = [
      { role: "system", content: systemPrompt },
      // L3: render the final answer in the operator locale while the pipeline
      // (tool calls, ids, numbers, grounding) stays English. English needs no
      // directive - the base prompt is already English.
      ...(locale === "en"
        ? []
        : [{ role: "system", content: localeDirective(locale) } as ChatMessage]),
      ...(ctx.history ?? []).slice(-6).map((h) => ({ role: h.role, content: h.content }) as ChatMessage),
      { role: "user", content: query },
    ];
    // Multi-round tool loop so the model can chain calls (e.g. query_inventory to
    // find a resource id, then get_metrics on it) before answering. Bounded.
    const MAX_ROUNDS = 4;
    try {
      for (let round = 0; round < MAX_ROUNDS; round++) {
        const offerTools = round < MAX_ROUNDS - 1 ? tools : null;
        const msg = await this.post(messages, offerTools);
        if (!msg.tool_calls || msg.tool_calls.length === 0) {
          return msg.content ?? "(no answer)";
        }
        messages.push(msg);
        for (const call of msg.tool_calls) {
          let args: Record<string, unknown> = {};
          try {
            args = JSON.parse(call.function.arguments || "{}");
          } catch {
            args = {};
          }
          let result: string;
          try {
            result = await runTool(call.function.name, args, ctx);
          } catch (err) {
            result = `error: ${(err as Error).message}`;
          }
          messages.push({ role: "tool", tool_call_id: call.id, content: result });
        }
      }
      const final = await this.post(messages, null);
      return final.content ?? "(no answer)";
    } catch (err) {
      return `(narrator error) ${(err as Error).message}`;
    }
  }
}
