import { isIP } from "node:net";
import { AuthError } from "./auth";

function address(value: unknown, label: string): string {
  if (typeof value !== "string" || !value || value !== value.trim() || !isIP(value))
    throw new AuthError(`Invalid ${label} address metadata`, 400);
  return value.startsWith("::ffff:") && isIP(value.slice(7)) === 4 ? value.slice(7) : value;
}

/**
 * Traefik appends the actual socket peer to X-Forwarded-For, so the rightmost
 * element is authoritative. Earlier elements are validated but never trusted.
 */
export function clientAddress(remote: unknown, forwarded: unknown, development = false,
                              trustedProxy = ""): string {
  const peer = address(remote, "peer");
  if (development) return `direct:${peer}`;
  const proxy = address(trustedProxy, "trusted proxy");
  if (peer !== proxy) throw new AuthError("Authentication request did not use the trusted proxy", 403);
  if (typeof forwarded !== "string" || !forwarded || forwarded.length > 1024)
    throw new AuthError("Trusted proxy did not provide client address metadata", 400);
  const chain = forwarded.split(",").map(value => value.trim());
  if (!chain.length || chain.length > 16 || chain.some(value => !value || !isIP(value)))
    throw new AuthError("Invalid forwarded client address metadata", 400);
  return `proxy:${chain.at(-1)}`;
}
