/**
 * LlmNarrator - an OpenAI-compatible model as the console narrator.
 *
 * Understands free-form natural language (any language, including Korean) and
 * calls the read-only `console-tool`s to ground its answer. It is a translator,
 * not a judge: the system prompt forbids inventing numbers and forbids taking
 * actions (the console is read-only). One tool round is executed, then the model
 * answers from the tool results.
 *
 * Works with OpenAI (`Authorization: Bearer`) and Azure OpenAI (`api-key` header
 * + deployment-in-URL). Configured entirely from env - see `createNarrator`.
 */

import { CONSOLE_TOOLS, runTool } from "./tools.js";
import type { Narrator, NarratorContext } from "./types.js";

export interface LlmConfig {
  provider: "openai" | "azure";
  baseUrl: string;
  apiKey: string;
  model: string;
  apiVersion: string;
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

const SYSTEM_PROMPT =
  "You are the FDAI operator-console narrator. Your role is to translate the " +
  "operator's question (in any language, including Korean) into read-only tool " +
  "calls and to answer ONLY from the tool results. Never invent numbers or " +
  "facts; if the tools do not contain the answer, say so plainly. You never take " +
  "actions - the console is read-only and approvals happen through pull requests. " +
  "Reply in the operator's language, concisely.";

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

  private headers(): Record<string, string> {
    const common = { "content-type": "application/json" };
    return this.cfg.provider === "azure"
      ? { ...common, "api-key": this.cfg.apiKey }
      : { ...common, authorization: `Bearer ${this.cfg.apiKey}` };
  }

  private async post(
    messages: ChatMessage[],
    withTools: boolean,
  ): Promise<ChatMessage> {
    const body: Record<string, unknown> = { messages, temperature: 0 };
    if (this.cfg.provider === "openai") body.model = this.cfg.model;
    if (withTools) {
      body.tools = CONSOLE_TOOLS.map((t) => ({
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
      headers: this.headers(),
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
    const messages: ChatMessage[] = [
      { role: "system", content: SYSTEM_PROMPT },
      { role: "user", content: query },
    ];
    try {
      const first = await this.post(messages, true);
      if (!first.tool_calls || first.tool_calls.length === 0) {
        return first.content ?? "(no answer)";
      }
      // Execute the requested read-only tools and feed results back once.
      messages.push(first);
      for (const call of first.tool_calls) {
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
        messages.push({
          role: "tool",
          tool_call_id: call.id,
          content: result,
        });
      }
      const second = await this.post(messages, false);
      return second.content ?? "(no answer)";
    } catch (err) {
      return `(narrator error) ${(err as Error).message}`;
    }
  }
}
