/** Only this authenticated file route may be used as a relative source citation. */
export function isPrivateSourceUrl(url: string): boolean {
  return /^\/api\/names\/[A-Z0-9^][A-Z0-9.^=_-]{0,63}\/documents\/[a-f0-9]{32}\/content$/.test(url)
}
