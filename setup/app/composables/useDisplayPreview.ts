export interface PreviewState { phase: string; id?: string; deadline?: number }
export function useDisplayPreview() {
  const preview = useState<PreviewState>('display-preview', () => ({ phase: 'loading' }));
  const unavailable = useState('display-preview-unavailable', () => false);
  const mutating = useState('display-preview-mutating', () => false);
  const generation = useState('display-preview-generation', () => 0);
  const { session } = useAdmin();
  const locked = computed(() => mutating.value || unavailable.value || ['loading', 'pending', 'committing', 'rolling-back'].includes(preview.value.phase));
  async function update(action = '', body?: unknown) {
    const mutation = body !== undefined;
    if (!mutation && mutating.value) return preview.value;
    if (mutation) {
      if (mutating.value) throw new Error('A preview request is already in progress');
      mutating.value = true;
      generation.value++;
    }
    const requestGeneration = generation.value;
    try {
    const result = await $fetch<PreviewState & { error?: string }>('/elderbrain/api/display-preview' + action, {
      method: body === undefined ? 'GET' : 'POST', body: body as Record<string, unknown> | undefined,
      headers: { 'x-elderbrain-request': '1', 'x-csrf-token': session.value.csrf }, timeout: 15000, retry: 0,
    });
    if (result.error) throw new Error(result.error);
    if (requestGeneration === generation.value) {
      preview.value = result;
      unavailable.value = false;
    }
    return result;
    } finally { if (mutation) mutating.value = false; }
  }
  return { preview, unavailable, locked, update };
}
