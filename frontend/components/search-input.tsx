"use client";

import type { DemoCaseSummary } from "@/types/report";

export interface SearchInputProps {
  inputValue: string;
  onInputChange: (value: string) => void;
  onSubmit: () => void;
  isStreaming: boolean;
  demoCases: DemoCaseSummary[];
  onSelectExample: (demo: DemoCaseSummary) => void;
  backendState: "checking" | "online" | "offline" | "degraded";
}

export function SearchInput({
  inputValue,
  onInputChange,
  onSubmit,
  isStreaming,
  demoCases,
  onSelectExample,
  backendState,
}: SearchInputProps) {
  return (
    <main className="app app--idle">
      <div className="search-page">
        <div className="search-page__brand">
          <h1>较真核查</h1>
          <p>输入你看到的消息，帮你判断真假</p>
        </div>

        <div className="search-box">
          <textarea
            className="search-box__input"
            rows={1}
            placeholder="粘贴一条消息、新闻标题或链接..."
            value={inputValue}
            onChange={(e) => onInputChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSubmit();
              }
            }}
          />
          <button
            className="search-box__submit"
            onClick={onSubmit}
            disabled={isStreaming || !inputValue.trim()}
          >
            核查
          </button>
        </div>

        <div className="examples">
          {demoCases.slice(0, 4).map((demo) => (
            <button key={demo.id} className="examples__chip" onClick={() => onSelectExample(demo)}>
              {demo.title}
            </button>
          ))}
        </div>

        <div className="search-page__status">
          <span className={`status-dot status-dot--${backendState}`} />
          <span>{backendState === "online" ? "服务正常" : backendState === "offline" ? "服务离线" : backendState === "degraded" ? "服务降级" : "检测中..."}</span>
        </div>
      </div>
    </main>
  );
}
