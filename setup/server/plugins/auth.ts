import { AuthStore } from "../services/auth-store";
export default defineNitroPlugin((app) => {
  const auth = new AuthStore(process.env.STATE_DIR || "/state");
  app.hooks.hook("request", event => { event.context.auth = auth; });
});
