import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import net from "node:net";
import tls from "node:tls";
import { execFileSync, spawn } from "node:child_process";
import { once } from "node:events";

test("production recovery mail uses verified TLS and rejects unsafe transports", async (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "elderbrain-smtp-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const key = path.join(root, "key.pem");
  const cert = path.join(root, "cert.pem");
  execFileSync("openssl", ["req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
    "-keyout", key, "-out", cert, "-subj", "/CN=localhost", "-addext", "subjectAltName=IP:127.0.0.1,DNS:localhost"], { stdio: "ignore" });
  fs.chmodSync(key, 0o600);
  const delivered = path.join(root, "delivered.txt");
  let deliveries = 0;
  const sockets = new Set<net.Socket>();
  function smtp(socket: net.Socket) {
    sockets.add(socket);
    socket.on("close", () => sockets.delete(socket));
    socket.on("error", () => {});
    socket.write("220 localhost test SMTP\r\n");
    let buffer = "", message = "", receiving = false;
    socket.on("data", chunk => {
      buffer += chunk.toString();
      let end: number;
      while ((end = buffer.indexOf("\r\n")) >= 0) {
        const line = buffer.slice(0, end); buffer = buffer.slice(end + 2);
        if (receiving) {
          if (line === ".") {
            deliveries++; fs.writeFileSync(delivered, message, { mode: 0o600 });
            receiving = false; message = ""; socket.write("250 received\r\n");
          } else message += line + "\n";
        } else if (/^(EHLO|HELO) /.test(line)) socket.write("250 localhost\r\n");
        else if (/^(MAIL FROM:|RCPT TO:)/.test(line)) socket.write("250 accepted\r\n");
        else if (line === "DATA") { receiving = true; socket.write("354 send message\r\n"); }
        else if (line === "QUIT") socket.end("221 goodbye\r\n");
        else socket.write("502 unsupported\r\n");
      }
    });
  }
  const secure = tls.createServer({ key: fs.readFileSync(key), cert: fs.readFileSync(cert) }, smtp);
  secure.on("tlsClientError", () => {});
  const plain = net.createServer(smtp);
  secure.listen(0, "127.0.0.1"); plain.listen(0, "127.0.0.1");
  await Promise.all([once(secure, "listening"), once(plain, "listening")]);
  t.after(async () => {
    for (const socket of sockets) socket.destroy();
    await Promise.all([new Promise<void>(r => secure.close(() => r())), new Promise<void>(r => plain.close(() => r()))]);
  });
  for (const mode of ["trusted", "untrusted", "plaintext"] as const) {
    const port = ((mode === "plaintext" ? plain : secure).address() as net.AddressInfo).port;
    const child = spawn(process.execPath, ["--import", "tsx", "test/smtp-client.ts", mode], {
      env: { ...process.env, NODE_EXTRA_CA_CERTS: mode === "trusted" ? cert : "",
        SMTP_TEST_ROOT: root, SMTP_TEST_PORT: String(port) }, stdio: ["ignore", "pipe", "pipe"],
    });
    let errors = "";
    child.stderr.on("data", chunk => { errors += chunk; });
    const [code] = await once(child, "exit");
    assert.equal(code, 0, errors);
  }
  assert.equal(deliveries, 2, "Only verification and recovery messages should be delivered");
});
