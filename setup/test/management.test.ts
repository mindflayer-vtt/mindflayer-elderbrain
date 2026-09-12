import test from "node:test";
import assert from "node:assert/strict";
import net from "node:net";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { backupDownload, backupUpload } from "../server/utils/management";
import { Readable } from "node:stream";

async function fixture(t: test.TestContext, respond: (socket: net.Socket) => void) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "elderbrain-download-"));
  const socketPath = path.join(directory, "bridge.sock");
  const server = net.createServer({ allowHalfOpen: true }, socket => socket.once("data", () => respond(socket)));
  await new Promise<void>(resolve => server.listen(socketPath, resolve));
  t.after(() => { server.close(); fs.rmSync(directory, { recursive: true, force: true }); });
  return socketPath;
}
test("backup download handles split header and binary body", async t => {
  const socket = await fixture(t, peer => { peer.write('{"ok":true,'); setImmediate(() => peer.end(Buffer.concat([Buffer.from('"size":3}\n'), Buffer.from([0, 255, 10])]))); });
  const result = await backupDownload(socket, "a".repeat(32));
  const chunks: Buffer[] = [];
  for await (const chunk of result.stream) chunks.push(chunk);
  assert.equal(result.size, 3);
  assert.deepEqual(Buffer.concat(chunks), Buffer.from([0, 255, 10]));
});
test("backup download rejects unavailable artifacts and truncated bodies", async t => {
  const socket = await fixture(t, peer => peer.end('{"ok":false}\n'));
  await assert.rejects(backupDownload(socket, "a".repeat(32)), /unavailable/);
  const truncated = await fixture(t, peer => peer.end('{"ok":true,"size":10}\nx'));
  const result = await backupDownload(truncated, "a".repeat(32));
  await assert.rejects(async () => { for await (const _ of result.stream) {} }, /Truncated/);
});

test("backup upload streams request bytes and parses job response", async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "elderbrain-upload-"));
  const socketPath = path.join(directory, "bridge.sock");
  let received = Buffer.alloc(0);
  const server = net.createServer({ allowHalfOpen: true }, peer => {
    peer.on("data", chunk => { received = Buffer.concat([received, chunk]); });
    peer.on("end", () => peer.end('{"ok":true,"output":"queued"}\n'));
  });
  await new Promise<void>(resolve => server.listen(socketPath, resolve));
  t.after(() => { server.close(); fs.rmSync(directory, { recursive: true, force: true }); });
  const result = await backupUpload(socketPath, Readable.from([Buffer.from([0, 255, 10])]), 3);
  assert.equal(result.ok, true);
  assert.deepEqual(received, Buffer.concat([Buffer.from("backup-upload 3\n"), Buffer.from([0, 255, 10])]));
});
