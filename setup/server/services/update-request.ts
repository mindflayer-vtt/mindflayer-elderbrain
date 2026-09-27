export function updateRequest(value: unknown) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid update request');
  const input = value as Record<string, unknown>;
  if (Object.keys(input).sort().join(',') !== 'confirmDowntime,confirmUpdate,manifestSha256,version'
      || typeof input.version !== 'string' || input.version.length > 128
      || !/^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?![\s\S])/.test(input.version)
      || typeof input.manifestSha256 !== 'string' || !/^[a-f0-9]{64}(?![\s\S])/.test(input.manifestSha256)
      || input.confirmUpdate !== true || input.confirmDowntime !== true)
    throw new Error('Choose a release and explicitly confirm the update and service downtime');
  return { version: input.version, manifestSha256: input.manifestSha256, confirmUpdate: true, confirmDowntime: true };
}
