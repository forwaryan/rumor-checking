"use client";

import type { DemoCaseSummary } from "@/types/report";
import type { SearchSource } from "@/lib/api-client";

export interface SearchInputProps {
  inputValue: string;
  onInputChange: (value: string) => void;
  onSubmit: () => void;
  isStreaming: boolean;
  demoCases: DemoCaseSummary[];
  onSelectExample: (demo: DemoCaseSummary) => void;
  backendState: "checking" | "online" | "offline" | "degraded";
  searchSources: SearchSource[];
  activeSources: string[];
  onToggleSource: (sourceId: string) => void;
}

export function SearchInput({
  inputValue,
  onInputChange,
  onSubmit,
  isStreaming,
  demoCases,
  onSelectExample,
  backendState,
  searchSources,
  activeSources,
  onToggleSource,
}: SearchInputProps) {
  const enabledSources = searchSources.filter((s) => s.enabled);

  return (
    <main className="app app--idle">
      <div className="search-page">
        <div className="search-page__brand">
          <h1>较真核查</h1>
          <p>输入你看到的消息，帮你判断真假</p>
        </div>

        {enabledSources.length > 0 && (
          <div className="search-sources">
            <span className="search-sources__label">搜索源：</span>
            <div className="search-sources__options">
              {enabledSources.map((source) => {
                const checked = activeSources.includes(source.id);
                // Block unchecking the last active source: an empty selection
                // would silently fall back to "all sources" on the backend.
                const isLastActive = checked && activeSources.length <= 1;
                return (
                  <label
                    key={source.id}
                    className="search-sources__item"
                    title={isLastActive ? "至少保留一个搜索源" : source.description}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => onToggleSource(source.id)}
                      disabled={isStreaming || isLastActive}
                    />
                    <span className="search-sources__name">{source.label}</span>
                  </label>
                );
              })}
            </div>
          </div>
        )}

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
