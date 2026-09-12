const checks = new Set<() => boolean>();

export function confirmDiscardChanges() {
  return !Array.from(checks).some(check => check()) || window.confirm("Discard unsaved changes?");
}

export function useUnsavedChanges(value: () => unknown) {
  let baseline = JSON.stringify(value());
  const dirty = () => JSON.stringify(value()) !== baseline;
  onMounted(() => checks.add(dirty));
  onBeforeUnmount(() => checks.delete(dirty));
  return () => { baseline = JSON.stringify(value()); };
}

export function hasUnsavedChanges() { return Array.from(checks).some(check => check()); }
