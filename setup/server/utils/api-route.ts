import type { H3Event } from "h3";

export function apiRoute(handler: (event: H3Event) => unknown | Promise<unknown>) {
  return defineEventHandler(async (event) => {
    setHeader(event, "cache-control", "no-store");
    try { return await handler(event); }
    catch (error) {
      setResponseStatus(event, 400);
      return { error: error instanceof Error ? error.message : "request failed" };
    }
  });
}

export async function apiBody(event: H3Event): Promise<unknown> {
  let size = 0;
  const chunks: Buffer[] = [];
  for await (const chunk of event.node.req) {
    const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += bytes.length;
    if (size <= 65536) chunks.push(bytes);
  }
  if (size > 65536) throw new Error("request too large");
  return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
}
