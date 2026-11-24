import { describe, expect, it } from "vitest";
import { filterSources, simulatedAnswer, sources } from "./insurance-data";
describe("Insurance demonstration rules", () => {
  it("filters by insurance type", () => {
    expect(filterSources("", "Könüllü").map((s) => s.id)).toEqual([4]);
  });
  it("searches a law number and article", () => {
    expect(filterSources("165-IVQ Maddə 15").map((s) => s.id)).toEqual([1]);
  });
  it("filters versions and languages", () => {
    expect(filterSources("", "all", "all", "AZ", "2023").map((s) => s.id)).toEqual([3]);
    expect(filterSources("", "all", "all", "EN")).toEqual([]);
  });
  it("warns when supporting evidence is insufficient", () => {
    expect(simulatedAnswer("astronomiya")).toContain("kifayət qədər hüquqi sübut tapılmadı");
  });
  it("labels every synthetic legal passage", () => {
    expect(sources.every((s) => s.text.includes("Sintetik nümayiş"))).toBe(true);
  });
});
