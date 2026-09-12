import type { ApplianceConfig, Controller, ManagementResult } from "../../shared/types";

export function useAppliance(section: "overview" | "foundry" | "keypads" | "displays") {
const toast = useToast();
const { session, refresh: refreshSession } = useAdmin();
const config = ref<ApplianceConfig>();
const controllers = ref<Controller[]>([]);
const status = ref<Record<string, unknown>>({});
const error = ref("");
const busy = ref(false);
const credentials = reactive({ username: "", password: "", releaseUrl: "" });
const configSaved = useUnsavedChanges(() => config.value);
const credentialsSaved = useUnsavedChanges(() => credentials);
const { preview, update: updatePreview } = useDisplayPreview();
watch(() => preview.value.phase, (next, previous) => {
  if (section === 'displays' && ['pending', 'committing', 'rolling-back'].includes(previous) && ['confirmed', 'rolled-back'].includes(next)) void refresh(true);
});
let timer: ReturnType<typeof setInterval> | undefined;
let disposed = false;
let refreshing = false;

async function api<T>(route: string, options: Record<string, unknown> = {}): Promise<T> {
  const result = await $fetch<T & { error?: string }>("/elderbrain/api/" + route, {
    ...options,
    headers: { "x-elderbrain-request": "1", "x-csrf-token": session.value.csrf },
    onResponseError: async ({ response }) => { if (response.status === 401 || response.status === 403) await refreshSession(); },
  });
  if (result && typeof result === "object" && result.error) throw new Error(result.error);
  return result as T;
}
async function refresh(initial = false) {
  if (refreshing) return;
  refreshing = true;
  try {
    const [nextStatus, nextControllers] = await Promise.all([
      section === "overview" ? api<Record<string, unknown>>("status") : Promise.resolve({}), section === "keypads" ? api<Controller[]>("controllers") : Promise.resolve([]),
    ]);
    if (disposed) return;
    status.value = nextStatus;
    controllers.value = nextControllers;
    // Polling must never overwrite a user's unsaved form edits.
    if (initial || !config.value) { config.value = await api<ApplianceConfig>("config"); configSaved(); }
    error.value = "";
  } catch (e) { error.value = e instanceof Error ? e.message : "Unable to load appliance status"; }
  finally { refreshing = false; }
}
async function perform(task: () => Promise<void>, title: string) {
  busy.value = true;
  try { await task(); toast.add({ title, color: "success" }); }
  catch (e) { toast.add({ title: e instanceof Error ? e.message : "Action failed", color: "error" }); }
  finally { busy.value = false; }
}
function restart(action: string) {
  return perform(async () => {
    const result = await api<ManagementResult>("actions/" + action, { method: "POST" });
    if (!result.ok) throw new Error(result.error || result.output || "Restart failed");
    await refresh();
  }, "Restart requested");
}
function saveConfig() {
  return perform(async () => {
    await updatePreview('', config.value);
    configSaved();
  }, "Display preview started");
}
function saveFoundry() {
  return perform(async () => {
    const result = await api<{ stored: boolean; started: ManagementResult }>("foundry", { method: "PUT", body: { ...credentials } });
    credentials.username = ""; credentials.password = ""; credentials.releaseUrl = "";
    credentialsSaved();
    if (!result.started.ok) throw new Error("Credentials stored, but Foundry could not start: " + (result.started.error || result.started.output || "management unavailable"));
  }, "Credentials stored and Foundry started");
}
onMounted(() => { void refresh(true); if (section === "overview" || section === "keypads") timer = setInterval(() => void refresh(), 5000); });
onBeforeUnmount(() => { disposed = true; clearInterval(timer); });
return { config, controllers, status, error, busy, credentials, api, perform, restart, saveConfig, saveFoundry };
}
