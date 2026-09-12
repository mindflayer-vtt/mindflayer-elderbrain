// Traefik removes /elderbrain before forwarding bundled asset requests.
export default defineEventHandler(async (event) => {
  const response = await useNitroApp().localFetch("/elderbrain" + event.path, {
    method: event.method === "HEAD" ? "HEAD" : "GET",
  });
  return sendWebResponse(event, response);
});
