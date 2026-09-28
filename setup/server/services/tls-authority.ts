import { Readable } from "node:stream";
import { backupUpload } from "./management-client";

export async function installAuthority(input: unknown) {
  if (!input || typeof input !== "object") throw new Error("Certificate upload is required");
  const value = input as Record<string, unknown>;
  if (Object.keys(value).sort().join(",") !== "certificate,privateKey,trustRoot" ||
      [value.certificate, value.privateKey, value.trustRoot].some(item => typeof item !== "string" ||
        !item.startsWith("-----BEGIN ") || Buffer.byteLength(item) > 16384))
    throw new Error("Expected a PEM CA certificate, private key and trust root (16 KiB each)");
  const bytes = Buffer.from(JSON.stringify(value));
  const result = await backupUpload(process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock",
    Readable.from([bytes]), bytes.length, "tls-authority-install");
  if (!result.ok) throw new Error("Could not install the certificate authority; existing TLS settings were preserved where possible");
  return JSON.parse(result.output || "{}");
}
