export interface ApplianceConfig {
  version: number;
  configured: boolean;
  domain: string;
  views: { output: string; url: string; mode?: "admin" | "player"; tabs?: string[] }[];
  controllers: Record<string, { name: string }>;
}
export interface Controller {
  id: string;
  connected: boolean;
  lastKey: string | null;
  lastState?: boolean;
  lastActivity: string | null;
  deviceAuthenticated?: boolean;
  hardware?: string | null;
  firmware?: string | null;
  configurationDigest?: string | null;
  appliedLeds?: { led1: string; led2: string } | null;
}
export interface ManagementResult {
  ok: boolean;
  action?: string;
  output?: string;
  error?: string;
}
