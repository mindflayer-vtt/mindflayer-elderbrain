import { AuthError } from "./auth";
import type { H3Event } from "h3";
export async function smallBody(event: H3Event): Promise<Record<string, unknown>> {
  let size = 0;
  const chunks: Buffer[] = [];
  for await (const chunk of event.node.req) {
    const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += bytes.length;
    if (size <= 65536) chunks.push(bytes);
  }
  if (size > 65536) throw new AuthError("Request too large", 413);
  const body: unknown = JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
  if (!body || typeof body !== "object" || Array.isArray(body)) throw new AuthError("Expected an object");
  return body as Record<string, unknown>;
}
