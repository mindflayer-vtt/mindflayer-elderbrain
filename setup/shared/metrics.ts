export interface Usage { total: number; free: number; used: number }
export interface MetricSample {
  at: number; cpu: number | null; ram: Usage | null;
  disks: (Usage & { path: string })[];
}
export interface HostMetrics {
  hostname: string; uptime: number | null; version: string; mindflayerServerImage: string;
  services: { name: string; state: string }[]; errors: string[]; history: MetricSample[];
}
