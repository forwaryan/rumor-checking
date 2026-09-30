export const MAX_ANALYSIS_INPUT_CHARACTERS = 100000;
export const MAX_REQUEST_BODY_BYTES = 1024 * 1024;

export function requestBodyHeaderStatus(contentLength: string | null): 400 | 413 | null {
  if (contentLength === null) return null;
  if (!/^\d+$/.test(contentLength)) return 400;
  return Number(contentLength) > MAX_REQUEST_BODY_BYTES ? 413 : null;
}

export function analysisInputError(value: string): string | null {
  return Array.from(value).length > MAX_ANALYSIS_INPUT_CHARACTERS
    ? `输入最多 ${MAX_ANALYSIS_INPUT_CHARACTERS.toLocaleString("zh-CN")} 个字符，请缩短后再核查。`
    : null;
}
