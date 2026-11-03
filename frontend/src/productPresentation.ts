export const COUNTRIES = [
  { code: 'DE', name: '德国' }, { code: 'FR', name: '法国' },
  { code: 'ES', name: '西班牙' }, { code: 'IT', name: '意大利' },
] as const;
export const COUNTRY_ORDER = COUNTRIES.map(country => country.code);
export const COUNTRY_NAMES = Object.fromEntries(COUNTRIES.map(country => [country.code, country.name])) as Record<typeof COUNTRY_ORDER[number], string>;

// These are display bands only. Business calculations stay on the server.
export function marginBand(value: number) {
  if (value < 0) return 'negative';
  if (value < 0.1) return 'low';
  if (value < 0.2) return 'warning';
  return 'good';
}

export function ratingBand(score: number) {
  return score >= 4.3 ? 'good' : score >= 3.5 ? 'warning' : 'danger';
}
