import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { SectionHeader } from "@/components/section-header";

function renderHeader(isOpen: boolean, count: number) {
  return renderToStaticMarkup(createElement(SectionHeader, {
    title: "核查依据",
    count,
    id: "evidence-panel",
    isOpen,
    onToggle: () => {},
  }));
}

describe("section header SSR markup", () => {
  it("renders a closed button with its title, count, and disclosure attributes", () => {
    const markup = renderHeader(false, 3);

    expect(markup).toMatch(/^<button\b[^>]*>[\s\S]*<\/button>$/);
    expect(markup).toContain('type="button"');
    expect(markup).toContain('aria-expanded="false"');
    expect(markup).toContain('aria-controls="evidence-panel"');
    expect(markup).toContain('class="section-card__title">核查依据<span class="section-card__badge">3</span>');
    expect(markup).toContain('class="section-card__arrow" aria-hidden="true"');
    expect(markup).not.toContain("section-card__arrow--open");
  });

  it("marks an open button as expanded and updates the arrow and count", () => {
    const markup = renderHeader(true, 0);

    expect(markup).toContain('type="button"');
    expect(markup).toContain('aria-expanded="true"');
    expect(markup).toContain('aria-controls="evidence-panel"');
    expect(markup).toContain('class="section-card__title">核查依据<span class="section-card__badge">0</span>');
    expect(markup).toContain('class="section-card__arrow section-card__arrow--open" aria-hidden="true"');
  });

  it.each([false, true])("keeps interactive elements out of the %s button", (isOpen) => {
    const markup = renderHeader(isOpen, 3);
    const buttonContent = markup.replace(/^<button\b[^>]*>/, "").replace(/<\/button>$/, "");

    expect(buttonContent).not.toMatch(/<(?:button|a|input|select|textarea|summary)\b/i);
  });
});
