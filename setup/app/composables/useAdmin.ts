interface AdminSession {
  authenticated: boolean; ready: boolean; csrf: string;
  mustChange: boolean; emailVerified: boolean; email: string;
  defaultSmtpAvailable?: boolean;
}
export function useAdmin() {
  const session = useState<AdminSession>("admin-session", () => ({
    authenticated: false, ready: false, csrf: "", mustChange: false, emailVerified: false, email: "",
  }));
  async function request<T>(route: string, body?: unknown) {
    try {
      return await $fetch<T>("/elderbrain/api/auth/" + route, {
        method: body === undefined ? "GET" : "POST",
        body: body as Record<string, unknown> | undefined,
        headers: { "x-elderbrain-request": "1", "x-csrf-token": session.value.csrf },
      });
    } catch (e) {
      const error = e as { data?: { error?: string }; message?: string };
      throw new Error(error.data?.error || error.message || "Request failed");
    }
  }
  async function refresh() { session.value = await request<AdminSession>("session"); }
  async function login(password: string) { session.value = await request<AdminSession>("login", { username: "admin", password }); }
  async function logout() { await request("logout", {}); await refresh(); }
  return { session, request, refresh, login, logout };
}
