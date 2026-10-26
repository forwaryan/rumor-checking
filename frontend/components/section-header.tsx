"use client";

import React from "react";

interface SectionHeaderProps {
  title: string;
  count: number;
  id: string;
  isOpen: boolean;
  onToggle: () => void;
}

export function SectionHeader({ title, count, id, isOpen, onToggle }: SectionHeaderProps) {
  return (
    <button type="button" className="section-card__header" onClick={onToggle} aria-expanded={isOpen} aria-controls={id}>
      <span className="section-card__title">{title}<span className="section-card__badge">{count}</span></span>
      <span className={`section-card__arrow${isOpen ? " section-card__arrow--open" : ""}`} aria-hidden="true">&#9660;</span>
    </button>
  );
}
