export default defineNuxtPlugin((nuxtApp) => {
  const selector = 'input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]), textarea, select, button[role="combobox"], button[type="submit"]';
  function focusFirst(navigated = false) {
    // Only fill an empty focus position. Updates and polling must not interrupt typing.
    if (document.activeElement && document.activeElement !== document.body &&
        !(navigated && document.activeElement.closest('nav[aria-label="Administration"]'))) return;
    const field = Array.from(document.querySelectorAll<HTMLElement>(`form :is(${selector})`))
      .find((element) => !element.matches(':disabled, [readonly]') && element.getClientRects().length > 0);
    field?.focus({ preventScroll: true });
  }
  nuxtApp.hook('page:finish', () => { focusFirst(true); });
  nuxtApp.hook('app:mounted', () => {
    const observer = new MutationObserver((records) => {
      const hasNewForm = records.some(record => Array.from(record.addedNodes).some(node =>
        node instanceof Element && (node.matches('form, input, textarea, select') || node.querySelector('form, input, textarea, select'))));
      const becameEnabled = records.some(record => record.type === 'attributes' && record.target instanceof Element && !record.target.matches(':disabled'));
      if (hasNewForm || becameEnabled) focusFirst();
    });
    observer.observe(document.getElementById('__nuxt')!, { childList: true, subtree: true, attributes: true, attributeFilter: ['disabled'] });
    focusFirst();
  });
});
