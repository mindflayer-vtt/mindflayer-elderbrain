import { AuthStore } from "../utils/auth";
export default defineNitroPlugin((app) => {
  const auth = new AuthStore(process.env.STATE_DIR || "/state");
  app.hooks.hook("request", event => { event.context.auth = auth; });
});
