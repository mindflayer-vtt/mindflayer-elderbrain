import { Readable } from "node:stream";
import type { H3Event } from "h3";
import { command, backupUpload } from "../management";
import { updateRequest } from "../update-request";
import { apiBody } from "../api-route";

export async function systemApi(event: H3Event, route: string) {
  const method = event.method;
  const socket = process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock";
  const body = () => apiBody(event);
  if (route === 'system/release' && method === 'GET') {
    const result = await command(socket, 'release-status');
    if (!result.ok) throw new Error('Installed release status unavailable');
    return JSON.parse(result.output || 'null');
  }
  if (route === 'system/power' && method === 'GET') {
    const result = await command(socket, 'power-status');
    if (!result.ok) throw new Error('Power status unavailable');
    return JSON.parse(result.output || 'null');
  }
  if (route === 'system/power' && method === 'POST') {
    const input = await body() as Record<string, unknown>;
    if (!input || Array.isArray(input) || Object.keys(input).sort().join(',') !== 'action,confirmPower'
        || !['reboot', 'shutdown'].includes(input.action as string) || input.confirmPower !== true)
      throw new Error('Choose reboot or shutdown and explicitly confirm service interruption');
    const payload = Buffer.from(JSON.stringify(input));
    const result = await backupUpload(socket, Readable.from([payload]), payload.length, 'power-start');
    if (!result.ok) throw new Error('Power request was not accepted. Check active jobs and maintenance status.');
    setResponseStatus(event, 202);
    return JSON.parse(result.output || 'null');
  }
  if (route === 'system/check' && method === 'POST') {
    const input = await body();
    if (!input || typeof input !== 'object' || Array.isArray(input) || Object.keys(input).length)
      throw new Error('Release checks do not accept a custom source or key');
    const result = await command(socket, 'release-check', 35000);
    if (!result.ok) throw new Error('Release check failed. Check the configured source, signing key and network connection.');
    return JSON.parse(result.output || 'null');
  }
  if (route === 'system/update' && method === 'POST') {
    const payload = Buffer.from(JSON.stringify(updateRequest(await body())));
    const result = await backupUpload(socket, Readable.from([payload]), payload.length, 'update-start');
    if (!result.ok) throw new Error('Update was not accepted. Check active jobs and maintenance status before retrying.');
    setResponseStatus(event, 202);
    return JSON.parse(result.output || 'null');
  }

  setResponseStatus(event, 404);
  return { error: "not found" };
}
