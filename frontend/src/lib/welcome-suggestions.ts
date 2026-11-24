export function uniqueWelcomeSuggestions(...sources: ReadonlyArray<readonly string[]>): string[] {
  const questions = new Map<string, string>();
  for (const question of sources.flat()) {
    const key = question
      .normalize("NFC")
      .toLocaleLowerCase("az")
      .trim()
      .replace(/\s+/gu, " ")
      .replace(/\?+$/u, "")
      .trimEnd();
    if (key && !questions.has(key)) questions.set(key, question);
  }
  return [...questions.values()];
}
