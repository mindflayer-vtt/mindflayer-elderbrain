export default defineNuxtPlugin(() => {
  const router = useRouter();
  router.beforeEach((to, from) => to.path === from.path || confirmDiscardChanges());
  window.addEventListener("beforeunload", event => {
    if (hasUnsavedChanges()) { event.preventDefault(); event.returnValue = ""; }
  });
});
