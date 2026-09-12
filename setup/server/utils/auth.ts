import fs from "node:fs";
import path from "node:path";
import { randomBytes, randomInt, scryptSync, timingSafeEqual, createHash } from "node:crypto";
import nodemailer from "nodemailer";
import bootstrapWords from "../../shared/bootstrap-words.json";

export interface MailSettings { host: string; port: number; secure: boolean; user: string; password: string; from: string }
interface Account {
  schema: 1; password: string; mustChange: boolean; email: string;
  verified: boolean; smtp?: MailSettings; recoveryHash?: string;
  verification?: { hash: string; expires: number; attempts: number };
  reset?: { hash: string; expires: number };
}
interface Session { csrf: string; expires: number; lastSeen: number }
export class AuthError extends Error {
  constructor(message: string, public statusCode = 400) { super(message); }
}
const token = () => randomBytes(32).toString("base64url");
// Keep machine/session tokens unchanged; bootstrap passwords get 64 random bits.
export const bootstrapPassword = () => Array.from({ length: 8 }, () => bootstrapWords[randomInt(bootstrapWords.length)]).join("-");
// Long-lived, single-use offline recovery codes carry 128 independent random bits.
export const offlineRecoveryCode = () => Array.from({ length: 16 }, () => bootstrapWords[randomInt(bootstrapWords.length)]).join("-");
const digest = (value: string) => createHash("sha256").update(value).digest("hex");
export function passwordHash(value: string) {
  const salt = randomBytes(16).toString("hex");
  return salt + ":" + scryptSync(value, salt, 32, { N: 32768, maxmem: 64 * 1024 * 1024 }).toString("hex");
}
export function passwordMatches(value: string, hash: string) {
  const [salt, expected] = hash.split(":");
  if (!salt || !expected || !/^[a-f0-9]{64}$/.test(expected)) return false;
  return timingSafeEqual(Buffer.from(expected, "hex"), scryptSync(value, salt, 32, { N: 32768, maxmem: 64 * 1024 * 1024 }));
}
function strongPassword(value: unknown): string {
  if (typeof value !== "string" || value.length < 12 || value.length > 256)
    throw new AuthError("Use a password between 12 and 256 characters");
  return value;
}
function emailAddress(value: unknown): string {
  if (typeof value !== "string" || value.length > 254 || !/^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/.test(value))
    throw new AuthError("Enter a valid recovery email address");
  return value;
}
export class AuthStore {
  private sessions = new Map<string, Session>();
  private rates = new Map<string, { count: number; expires: number }>();
  private account: Account;
  readonly directory: string;
  constructor(state: string, private deliver = sendMail) {
    this.directory = path.join(state, "secrets");
    fs.mkdirSync(this.directory, { recursive: true, mode: 0o700 });
    try { this.account = JSON.parse(fs.readFileSync(this.file("admin.json"), "utf8")); }
    catch (e) {
      if ((e as NodeJS.ErrnoException).code !== "ENOENT") throw e;
      let initial: string;
      try { initial = fs.readFileSync(this.file("initial-password"), "utf8").trim(); }
      catch (e) {
        if ((e as NodeJS.ErrnoException).code !== "ENOENT") throw e;
        initial = "";
      }
      if (initial.length < 24 || initial.length > 256) {
        initial = bootstrapPassword();
        const temporary = this.file("initial-password." + token() + ".tmp");
        const descriptor = fs.openSync(temporary, "wx", 0o600);
        try { fs.writeFileSync(descriptor, initial + "\n"); fs.fsyncSync(descriptor); }
        finally { fs.closeSync(descriptor); }
        fs.renameSync(temporary, this.file("initial-password"));
      }
      this.account = { schema: 1, password: passwordHash(initial), mustChange: true, email: "", verified: false };
      this.save();
    }
  }
  private file(name: string) { return path.join(this.directory, name); }
  private defaultSmtp(): unknown {
    try { return JSON.parse(fs.readFileSync(this.file("default-smtp.json"), "utf8")); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined;
      throw new AuthError("Default SMTP configuration is unreadable or invalid", 503);
    }
  }
  private save() {
    const temporary = this.file("admin.json.tmp");
    fs.writeFileSync(temporary, JSON.stringify(this.account), { mode: 0o600 });
    fs.renameSync(temporary, this.file("admin.json"));
  }
  private checkRootReset() {
    if (!fs.existsSync(this.file("admin-reset.request"))) return;
    const initial = fs.readFileSync(this.file("initial-password"), "utf8").trim();
    if (initial.length < 24 || initial.length > 256) throw new AuthError("Root recovery credential is incomplete. Run the root reset command again.", 503);
    this.account.password = passwordHash(initial);
    this.account.mustChange = true;
    delete this.account.reset;
    this.sessions.clear();
    this.save();
    fs.unlinkSync(this.file("admin-reset.request"));
  }
  limit(key: string, count = 10, interval = 15 * 60 * 1000) {
    const now = Date.now();
    for (const [id, item] of this.rates) if (item.expires <= now) this.rates.delete(id);
    const item = this.rates.get(key) || { count: 0, expires: now + interval };
    if (++item.count > count) throw new AuthError("Too many attempts. Try again later.", 429);
    this.rates.set(key, item);
  }
  login(username: unknown, password: unknown, client: string) {
    this.checkRootReset();
    this.limit("login:" + client);
    this.limit("login-global", 60);
    const input = typeof password === "string" && password.length >= 12 && password.length <= 256 ? password : "";
    const valid = passwordMatches(input, this.account.password) && input.length >= 12;
    if (username !== "admin" || !valid) throw new AuthError("Invalid username or password", 401);
    const id = token();
    const now = Date.now();
    for (const [key, session] of this.sessions) if (session.expires < now || session.lastSeen < now - 30 * 60 * 1000) this.sessions.delete(key);
    if (this.sessions.size >= 32) this.sessions.delete(this.sessions.keys().next().value!);
    this.sessions.set(digest(id), { csrf: token(), expires: now + 8 * 60 * 60 * 1000, lastSeen: now });
    return { id, ...this.session(id) };
  }
  session(id?: string) {
    this.checkRootReset();
    const current = id ? this.sessions.get(digest(id)) : undefined;
    const now = Date.now();
    if (!current || current.expires < now || current.lastSeen < now - 30 * 60 * 1000) {
      if (id) this.sessions.delete(digest(id));
      return { authenticated: false as const, ready: false, csrf: "", mustChange: false, emailVerified: false, email: "" };
    }
    current.lastSeen = now;
    return { authenticated: true as const, ready: !this.account.mustChange && this.account.verified,
      csrf: current.csrf, mustChange: this.account.mustChange, emailVerified: this.account.verified, email: this.account.email,
      defaultSmtpAvailable: fs.existsSync(this.file("default-smtp.json")) };
  }
  authorize(id?: string, csrf?: string, mutate = false, onboarding = false) {
    const session = this.session(id);
    if (!session.authenticated) throw new AuthError("Sign in required", 401);
    if (mutate && (!csrf || csrf !== session.csrf)) throw new AuthError("Invalid CSRF token", 403);
    if (!onboarding && !session.ready) throw new AuthError("Complete first-login setup", 403);
    return session;
  }
  logout(id?: string) { if (id) this.sessions.delete(digest(id)); }
  changePassword(id: string, current: unknown, next: unknown) {
    this.authorize(id, undefined, false, true);
    const password = strongPassword(next);
    if (typeof current !== "string" || current.length > 256 || !passwordMatches(current, this.account.password)) throw new AuthError("Current password is incorrect");
    if (passwordMatches(password, this.account.password)) throw new AuthError("Choose a different password");
    this.account.password = passwordHash(password);
    this.account.mustChange = false;
    this.sessions.clear();
    this.save();
    fs.rmSync(this.file("initial-password"), { force: true });
  }
  async configureEmail(email: unknown, values: unknown) {
    this.limit("email-settings", 5);
    const address = emailAddress(email);
    if (values === undefined) values = this.defaultSmtp();
    if (!values || typeof values !== "object") throw new AuthError("SMTP settings required");
    const input = values as Record<string, unknown>;
    const host = typeof input.host === "string" ? input.host.trim() : "";
    const port = Number(input.port);
    if (!/^[a-zA-Z0-9.-]{1,253}$/.test(host) || !Number.isInteger(port) || port < 1 || port > 65535) throw new AuthError("Invalid SMTP host or port");
    const smtp: MailSettings = { host, port, secure: input.secure === true, from: emailAddress(input.from),
      user: String(input.user || "").slice(0, 320), password: String(input.password || "").slice(0, 2048) };
    const code = String(randomInt(100000, 1000000));
    await this.deliver(smtp, address, "Verify Elderbrain recovery email", "Verification code: " + code + "\nExpires in 10 minutes.");
    this.account.email = address;
    this.account.smtp = smtp;
    this.account.verified = false;
    this.account.verification = { hash: digest(code), expires: Date.now() + 600000, attempts: 0 };
    this.save();
  }
  verifyEmail(code: unknown) {
    const pending = this.account.verification;
    if (!pending || pending.expires < Date.now() || pending.attempts >= 5) throw new AuthError("Verification expired. Send a new code.");
    pending.attempts++;
    this.save();
    if (typeof code !== "string" || digest(code) !== pending.hash) throw new AuthError("Incorrect verification code");
    this.account.verified = true;
    delete this.account.verification;
    const recoveryCode = offlineRecoveryCode();
    this.account.recoveryHash = digest(recoveryCode);
    this.save();
    return recoveryCode;
  }
  async requestRecovery(email: unknown, client: string) {
    this.limit("recover:" + client, 3);
    this.limit("recover-global", 10);
    if (email !== this.account.email || !this.account.verified || !this.account.smtp) return;
    const code = token();
    await this.deliver(this.account.smtp, this.account.email, "Elderbrain password recovery", "Recovery token: " + code + "\nExpires in 15 minutes. Enter it on your appliance's login screen.");
    this.account.reset = { hash: digest(code), expires: Date.now() + 900000 };
    this.save();
  }
  resetPassword(code: unknown, next: unknown, client: string) {
    this.limit("reset:" + client, 5);
    this.limit("reset-global", 30);
    const password = strongPassword(next);
    const hashed = typeof code === "string" && code.length <= 128 ? digest(code) : "";
    const offline = !!this.account.recoveryHash && hashed === this.account.recoveryHash;
    const emailed = this.account.reset && this.account.reset.expires > Date.now() && hashed === this.account.reset.hash;
    if (!offline && !emailed) throw new AuthError("Invalid or expired recovery token");
    this.account.password = passwordHash(password);
    this.account.mustChange = false;
    delete this.account.reset;
    if (offline) delete this.account.recoveryHash;
    this.sessions.clear();
    this.save();
    fs.rmSync(this.file("initial-password"), { force: true });
  }
}
async function sendMail(settings: MailSettings, to: string, subject: string, text: string) {
  const transport = nodemailer.createTransport({
    host: settings.host, port: settings.port, secure: settings.secure,
    requireTLS: !settings.secure,
    auth: settings.user ? { user: settings.user, pass: settings.password } : undefined,
    connectionTimeout: 10000, greetingTimeout: 10000, socketTimeout: 15000,
    disableFileAccess: true, disableUrlAccess: true,
  });
  try { await transport.sendMail({ from: settings.from, to, subject, text }); }
  catch { throw new AuthError("Email delivery failed. Check SMTP settings and TLS certificates."); }
  finally { transport.close(); }
}
