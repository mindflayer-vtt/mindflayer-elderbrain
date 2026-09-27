export default defineEventHandler((event) => {
  setHeader(event, "cache-control", "no-store");
  setResponseStatus(event, 404);
  return { error: "not found" };
});
