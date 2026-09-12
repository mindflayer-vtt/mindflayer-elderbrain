export default defineNuxtConfig({
  compatibilityDate: "2026-09-10",
  // Appliance data is loaded in the browser; preserve the browser's URL when
  // Traefik forwards /elderbrain/ as /.
  ssr: false,
  devtools: { enabled: false },
  modules: ["@nuxt/ui"],
  ui: { fonts: false },
  css: ["~/assets/app.css"],
  app: {
    buildAssetsDir: "/elderbrain/_nuxt/",
    head: { title: "Elderbrain", htmlAttrs: { lang: "en" } },
  },
  nitro: { preset: "node-server" },
  typescript: { strict: true },
});
