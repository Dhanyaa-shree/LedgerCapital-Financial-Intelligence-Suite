/** Display actual retrieved counts; never fabricate minimum values. */
export function displayNeo4jDocs(raw: number | undefined): number {
  return typeof raw === 'number' && Number.isFinite(raw) ? Math.max(0, Math.round(raw)) : 0;
}
export function displayChromaChunks(raw: number | undefined): number {
  return typeof raw === 'number' && Number.isFinite(raw) ? Math.max(0, Math.round(raw)) : 0;
}
