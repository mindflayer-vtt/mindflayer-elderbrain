import http from "node:http";
import net from "node:net";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { WebSocketServer } from "ws";
import { AuthStore } from "../server/utils/auth";
import { saveAtomic } from "../server/utils/config";

const state = fs.mkdtempSync(path.join(os.tmpdir(), "elderbrain-browser-"));
let verification = "";
const auth = new AuthStore(state, async (_settings, _to, _subject, text) => { verification = /Verification code: (\d+)/.exec(text)![1]!; });
const initial = fs.readFileSync(path.join(state, "secrets/initial-password"), "utf8").trim();
const bootstrap = auth.login("admin", initial, "fixture");
auth.changePassword(bootstrap.id, initial, "browser-test-password");
await auth.configureEmail("owner@example.com", { host: "smtp.example.com", port: 587, secure: false, from: "admin@example.com" });
auth.verifyEmail(verification);
fs.writeFileSync(path.join(state, "secrets/default-smtp.json"), JSON.stringify({
  host: "smtp.default.example.com", port: 587, secure: false, user: "", password: "default-private-canary", from: "admin@example.com",
}), { mode: 0o600 });
const socketPath = path.join(state, "management.sock");
const jobs: Record<string, unknown>[] = [];
let borgSettings: Record<string, unknown> = { configured: false };
let displayPreview = { phase: 'idle', id: '', deadline: 0 };
let displayCandidate: unknown;
let checkpointRetention = { enabled: false, keep: 10 };
let powerPending = false;
const management = net.createServer({ allowHalfOpen: true }, (socket) => {
  socket.once("data", (data) => {
    const action = data.toString().trim();
    if (action === 'release-check') {
      socket.end(JSON.stringify({ ok: true, output: JSON.stringify({ installedHostVersion: '1.0.0', installedReleaseSequence: 100, state: 'checked', release: {
        version: '1.2.3', releaseSequence: 123, recoveryApi: 1, hostVersion: '1.1.0', setupVersion: '2.0.0', notes: 'Improved offline updates. <script>unsafe()</script>',
        downtimeSeconds: 120, compatible: true, manifestSha256: 'a'.repeat(64),
      } }) }) + '\n');
      return;
    }
    if (action === 'power-status') {
      const output = JSON.stringify({ pending: powerPending });
      socket.end(JSON.stringify({ ok: true, output }) + '\n');
      // API tests observe acceptance once, then model the next boot so their
      // synthetic power request cannot block unrelated browser scenarios.
      if (powerPending) {
        powerPending = false;
        for (const job of jobs) if (job.kind === 'power' && job.state === 'queued') job.state = 'completed';
      }
      return;
    }
    if (action.startsWith('network-snapshot-restore-start ')) {
      const [, checkpoint, networkInterface, digest] = action.split(' ');
      if (!/^[a-f0-9]{64}$/.test(digest || '')) throw new Error('Expected confirmation hash only');
      const job = { id: 'a'.repeat(32), kind: 'network-snapshot-restore', state: 'queued',
        createdAt: Date.now() / 1000, request: { checkpoint, interface: networkInterface, confirmationDigest: digest } };
      jobs.unshift(job);
      socket.end(JSON.stringify({ ok: true, output: JSON.stringify(job) }) + '\n');
      return;
    }
    if (action === 'snapshots-retention' || action.startsWith('snapshots-retention-set ')) {
      if (action.startsWith('snapshots-retention-set ')) {
        const [, enabled, keep] = action.split(' ');
        checkpointRetention = { enabled: enabled === 'true', keep: Number(keep) };
      }
      socket.end(JSON.stringify({ ok: true, output: JSON.stringify(checkpointRetention) }) + '\n');
      return;
    }
    if (action === 'snapshots-list') {
      socket.end(JSON.stringify({ ok: true, output: JSON.stringify([{ version: 1, id: 'e'.repeat(32), createdAt: 1700000000, reason: 'manual' }]) }) + '\n');
      return;
    }
    if (action === 'snapshot-create-start' || action === 'snapshot-recover-start' || action.startsWith('snapshot-restore-start ')) {
      const job = { id: 'f'.repeat(32), kind: action.split(' ')[0]!.replace(/-start$/, ''), state: 'completed', createdAt: Date.now() / 1000 };
      jobs.unshift(job);
      socket.end(JSON.stringify({ ok: true, output: JSON.stringify(job) }) + '\n');
      return;
    }
    if (action === 'beamer-refresh' || action === 'beamer-status') {
      socket.end(JSON.stringify({ ok: true, output: JSON.stringify({ state: 'module-unavailable', views: [{ index: 1, state: 'module-unavailable' }] }) }) + '\n');
      return;
    }
    if (action.startsWith('display-preview-start ')) {
      const end = data.indexOf(10);
      const size = Number(data.subarray(0, end).toString().split(' ')[1]);
      let payload = data.subarray(end + 1);
      const finish = () => {
        if (displayPreview.phase === 'pending') { socket.end(JSON.stringify({ ok: false }) + '\n'); return; }
        displayCandidate = JSON.parse(payload.subarray(0, size).toString());
        displayPreview = { phase: 'pending', id: 'd'.repeat(32), deadline: Date.now() / 1000 + 90 };
        socket.end(JSON.stringify({ ok: true, output: JSON.stringify(displayPreview) }) + '\n');
      };
      if (payload.length >= size) finish();
      else socket.on('data', chunk => { payload = Buffer.concat([payload, chunk]); if (payload.length >= size) finish(); });
      return;
    }
    if (action.startsWith('display-preview-')) {
      const [operation, id] = action.split(' ');
      if (displayPreview.phase === 'pending' && displayPreview.deadline <= Date.now() / 1000) displayPreview.phase = 'rolled-back';
      if (operation !== 'display-preview-status') {
        if (displayPreview.phase !== 'pending' || id !== displayPreview.id) { socket.end(JSON.stringify({ ok: false }) + '\n'); return; }
        if (operation === 'display-preview-confirm') { saveAtomic(path.join(state, 'config.json'), displayCandidate); displayPreview.phase = 'confirmed'; }
        else displayPreview.phase = 'rolled-back';
      }
      socket.end(JSON.stringify({ ok: true, output: JSON.stringify(displayPreview) }) + '\n');
      return;
    }
    if (action === "host-displays") {
      socket.end(JSON.stringify({ ok: true, output: JSON.stringify({ at: Date.now() / 1000, outputs: [
        { name: "DP-1", make: "Fixture", model: "Monitor", active: true, width: 1920, height: 1080, refresh: 60000 },
      ] }) }) + "\n");
      return;
    }
    if (action === "host-network") {
      socket.end(JSON.stringify({ ok: true, output: JSON.stringify({ at: Date.now() / 1000, errors: [], interfaces: [
        { name: "eno1", index: 2, state: "UP", internal: false, defaultRoute: true, gateways: ["10.0.96.1"], dns: ["10.0.96.1"],
          addresses: [{ address: "10.0.96.125", prefix: 24, source: "DHCP", scope: "global" }] },
        { name: "docker0", index: 3, state: "UP", internal: true, defaultRoute: false, gateways: [], dns: [],
          addresses: [{ address: "172.17.0.1", prefix: 16, source: "Unknown", scope: "global" }] },
      ] }) }) + "\n");
      return;
    }
    if (action === "host-metrics") {
      const at = Date.now() / 1000;
      socket.end(JSON.stringify({ ok: true, output: JSON.stringify({ hostname: "elderbrain-host", uptime: 3600,
        services: [{ name: "elderbrain-stack", state: "active" }], errors: [],
        history: [at - 5, at].map(at => ({ at, cpu: 25, ram: { total: 8 * 1024 ** 3, used: 2 * 1024 ** 3, free: 6 * 1024 ** 3 },
          disks: [{ path: "/", total: 100 * 1024 ** 3, used: 20 * 1024 ** 3, free: 80 * 1024 ** 3 }] })) }) }) + "\n");
      return;
    }
    if (action.startsWith("kiosk-keyboard ")) {
      const [, token, layout] = action.split(" ");
      socket.end(JSON.stringify(token === "a".repeat(64) ? { ok: true, output: JSON.stringify({
        layouts: [{ value: "us:", label: "English (US)" }, { value: "de:", label: "German" }, { value: "de:nodeadkeys", label: "German (no dead keys)" }],
        active: [layout?.startsWith("de:") ? "German" : "English (US)"],
      }) } : { ok: false }) + "\n");
      return;
    }
    if (action === "keypad-release") {
      socket.end(JSON.stringify({ ok: true, output: JSON.stringify({ version: "1.2.3" }) }) + "\n");
      return;
    }
    if (action.startsWith("update-start ") || action.startsWith("power-start ")) {
      const end = data.indexOf(10);
      const size = Number(data.subarray(0, end).toString().split(' ')[1]);
      let payload = data.subarray(end + 1);
      const finish = () => {
        const kind = action.startsWith('power-start ') ? 'power' : 'update';
        const job = { id: (kind === 'power' ? '7' : '6').repeat(32), kind, state: 'queued', createdAt: Date.now() / 1000,
          request: JSON.parse(payload.subarray(0, size).toString()) };
        if (kind === 'power') powerPending = true;
        jobs.unshift(job);
        socket.end(JSON.stringify({ ok: true, output: JSON.stringify(job) }) + '\n');
      };
      if (payload.length >= size) finish();
      else socket.on('data', chunk => { payload = Buffer.concat([payload, chunk]); if (payload.length >= size) finish(); });
      return;
    }
    if (action.startsWith("keypad-install-start ")) {
      const end = data.indexOf(10);
      const size = Number(data.subarray(0, end).toString().split(" ")[1]);
      let payload = data.subarray(end + 1);
      const finish = () => {
        const input = JSON.parse(payload.subarray(0, size).toString());
        const job = { id: "5".repeat(32), kind: "keypad-install", state: "completed", stage: "completed", createdAt: Date.now() / 1000,
          request: input, result: { deviceId: "installed-fixture", firmware: input.version, revision: input.revision } };
        jobs.unshift(job);
        socket.end(JSON.stringify({ ok: true, output: JSON.stringify(job) }) + "\n");
      };
      if (payload.length >= size) finish();
      else socket.on("data", chunk => { payload = Buffer.concat([payload, chunk]); if (payload.length >= size) finish(); });
      return;
    }
    if (action === "keypad-usb-devices") {
      socket.end(JSON.stringify({ ok: true, output: JSON.stringify([{ id: "4".repeat(32), port: "/dev/ttyUSB0", vendorId: "1a86", productId: "7523", product: "Fixture USB adapter", manufacturer: "Fixture", serial: "test-only", chipVerified: false }]) }) + "\n");
      return;
    }
    if (action === "keypad-registrations") {
      socket.end(JSON.stringify({ ok: true, output: JSON.stringify(["test-keypad", "offline-keypad", ...(jobs.some(job => job.kind === "keypad-install") ? ["installed-fixture"] : [])]) }) + "\n");
      return;
    }
    if (action === "keypad-installations") {
      const installed = jobs.find(job => job.kind === "keypad-install");
      const result = installed?.result as { revision: number } | undefined;
      const current = fs.existsSync(path.join(state, "secrets/keypad-settings.json")) ? JSON.parse(fs.readFileSync(path.join(state, "secrets/keypad-settings.json"), "utf8")) : {};
      socket.end(JSON.stringify({ ok: true, output: JSON.stringify(result ? [{ deviceId: "installed-fixture", revision: result.revision,
        configurationVerifiedAt: Math.round(Number(installed!.createdAt) * 1000), configurationDigest: "a".repeat(64), hardware: "mindflayer-keypad-v1", firmware: "1.2.3",
        matchesCurrentSettings: result.revision === current.revision, currentSettingsRevision: current.revision }] : []) }) + "\n");
      return;
    }
    if (action.startsWith("backup-encrypted-start ") || action.startsWith("restore-preview-encrypted-start ")) {
      const end = data.indexOf(10);
      const size = Number(data.subarray(0, end).toString().split(" ")[1]);
      let received = data.length - end - 1;
      const finish = () => {
        const preview = action.startsWith("restore-preview-encrypted-start ");
        const job = { id: (preview ? "2" : "1").repeat(32), kind: preview ? "restore-preview-encrypted" : "backup-encrypted", state: "completed", createdAt: Date.now() / 1000,
          ...(preview ? { result: { preview: { files: 3, bytes: 100, applianceVersion: "test", applianceIdentity: "encrypted-fixture", roots: ["elderbrain"] } } } : {}) };
        jobs.unshift(job);
        socket.end(JSON.stringify({ ok: true, output: JSON.stringify(job) }) + "\n");
      };
      if (received >= size) finish();
      else socket.on("data", chunk => { received += chunk.length; if (received >= size) finish(); });
      return;
    }
    if (action === "borg-recovery-kit-start") {
      const job = { id: "f".repeat(32), kind: "borg-recovery-kit", state: "completed", createdAt: Date.now() / 1000 };
      jobs.unshift(job);
      socket.end(JSON.stringify({ ok: true, output: JSON.stringify(job) }) + "\n");
      return;
    }
    if (action.startsWith("recovery-download ")) {
      const kit = JSON.stringify({ type: "elderbrain-borg-recovery-kit", containsSecrets: true, settings: { passphrase: "fixture-kit-secret" } });
      socket.end(JSON.stringify({ ok: true, size: Buffer.byteLength(kit) }) + "\n" + kit);
      return;
    }
    if (action === "borg-settings") {
      socket.end(JSON.stringify({ ok: true, output: JSON.stringify(borgSettings) }) + "\n");
      return;
    }
    if (action.startsWith("borg-configure ")) {
      const end = data.indexOf(10);
      const size = Number(data.subarray(0, end).toString().split(" ")[1]);
      let payload = data.subarray(end + 1);
      const finish = () => {
        const parsed = JSON.parse(payload.subarray(0, size).toString());
        delete parsed.passphrase;
        borgSettings = { ...parsed, configured: true, passphraseStored: true };
        socket.end(JSON.stringify({ ok: true, output: JSON.stringify(borgSettings) }) + "\n");
      };
      if (payload.length >= size) finish();
      else socket.on("data", chunk => { payload = Buffer.concat([payload, chunk]); if (payload.length >= size) finish(); });
      return;
    }
    if (action === "borg-list-start" || action === "borg-test-start") {
      const job = { id: "d".repeat(32), kind: "borg-list", state: "completed", createdAt: Date.now() / 1000,
        result: { archives: [{ name: "elderbrain-fixture-2026", time: "2026-09-10" }] } };
      jobs.unshift(job);
      socket.end(JSON.stringify({ ok: true, output: JSON.stringify(job) }) + "\n");
      return;
    }
    if (action.startsWith("borg-fetch-start ")) {
      const job = { id: "e".repeat(32), kind: "borg-fetch", state: "completed", createdAt: Date.now() / 1000,
        result: { preview: { files: 3, bytes: 100, applianceVersion: "test", applianceIdentity: "remote-fixture", roots: ["foundry", "elderbrain"] } } };
      jobs.unshift(job);
      socket.end(JSON.stringify({ ok: true, output: JSON.stringify(job) }) + "\n");
      return;
    }
    if (action.startsWith("backup-upload ") || action.startsWith("backup-upload-encrypted ")) {
      const headerEnd = data.indexOf(10);
      const size = Number(data.subarray(0, headerEnd).toString().split(" ")[1]);
      let received = data.length - headerEnd - 1;
      const finish = () => {
        if (action.startsWith("backup-upload-encrypted ")) {
          socket.end(JSON.stringify({ ok: true, output: JSON.stringify({ uploadId: "3".repeat(32) }) }) + "\n");
          return;
        }
        const job = { id: "b".repeat(32), kind: "restore-preview", state: "completed", createdAt: Date.now() / 1000,
          result: { preview: { files: 3, bytes: size, applianceVersion: "test", applianceIdentity: "fixture-appliance", roots: ["foundry", "elderbrain"], createdAt: "2026-09-10T00:00:00Z" } } };
        jobs.unshift(job);
        socket.end(JSON.stringify({ ok: true, output: JSON.stringify(job) }) + "\n");
      };
      if (received >= size) finish();
      else socket.on("data", chunk => { received += chunk.length; if (received >= size) finish(); });
      return;
    }
    if (action.startsWith("restore-start ")) {
      const job = { id: "c".repeat(32), kind: "restore", state: "completed", createdAt: Date.now() / 1000 };
      jobs.unshift(job);
      socket.end(JSON.stringify({ ok: true, output: JSON.stringify(job) }) + "\n");
      return;
    }
    if (action.startsWith("backup-download ")) {
      socket.end(JSON.stringify({ ok: true, size: 12, encrypted: action.endsWith("1".repeat(32)) }) + "\n" + "test-archive");
      return;
    }
    if (action === "backup-start") {
      const job = { id: "a".repeat(32), kind: "backup", state: "completed", createdAt: Date.now() / 1000,
        result: { preview: { files: 2, bytes: 12, applianceVersion: "test" } } };
      jobs.unshift(job);
      socket.end(JSON.stringify({ ok: true, output: JSON.stringify(job) }) + "\n");
      return;
    }
    if (action === "jobs-list") {
      const output = JSON.stringify(jobs);
      socket.end(JSON.stringify({ ok: true, output }) + "\n");
      // Request-context API tests have no workers to advance their synthetic
      // jobs. Complete them after the first durable-list observation so one
      // test cannot leave the fixture's global admission gate occupied.
      for (const job of jobs) if (job.state === 'queued') job.state = 'completed';
      return;
    }
    socket.end(JSON.stringify({ ok: true, action, output: action === "foundry-logs" ? "Foundry container state: running\n2026-09-10T12:00:00Z Foundry test log" : "active" }) + "\n");
  });
}).listen(socketPath);
const ws = new WebSocketServer({ port: 18082 });
ws.on("connection", (socket) => {
  socket.on("message", (data) => {
    const message = JSON.parse(data.toString());
    if (message.type === "registration") socket.send(JSON.stringify({
      type: "registration", "controller-id": "test-keypad", status: "connected",
    }));
  });
});
const app = spawn(process.execPath, [".output/server/index.mjs"], {
  env: { ...process.env, HOST: "127.0.0.1", PORT: "18080", STATE_DIR: state,
    MANAGEMENT_SOCKET: socketPath, MINDFLAYER_WS_URL: "ws://127.0.0.1:18082",
    MINDFLAYER_SERVER_IMAGE: "test-registry-image", ELDERBRAIN_DEV_HTTP: "1" },
  stdio: "inherit",
});
// Match Traefik's PathPrefix + StripPrefix route; reject accidental root APIs/assets.
const proxy = http.createServer((req, res) => {
  if (!req.url?.startsWith("/elderbrain/")) { res.writeHead(404).end(); return; }
  const upstream = http.request({
    hostname: "127.0.0.1", port: 18080, path: req.url.slice("/elderbrain".length),
    method: req.method, headers: req.headers,
  }, (response) => {
    res.writeHead(response.statusCode || 502, response.headers);
    response.pipe(res);
  });
  upstream.on("error", () => res.writeHead(502).end());
  req.pipe(upstream);
}).listen(18081, "127.0.0.1");
function stop() {
  app.kill("SIGTERM");
  proxy.close(); management.close(); ws.close();
  fs.rmSync(state, { recursive: true, force: true });
}
process.on("SIGTERM", stop);
process.on("SIGINT", stop);
