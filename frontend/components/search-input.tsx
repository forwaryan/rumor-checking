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
        <header className="search-page__brand">
          <div className="brand-lockup">
            <span className="brand-mark" aria-hidden="true">
              <svg viewBox="0 0 24 24" role="img">
                <path d="M12 2.5 20 6v5.8c0 4.8-3.2 8.2-8 9.7-4.8-1.5-8-4.9-8-9.7V6l8-3.5Z" />
                <path d="m8.4 12 2.2 2.2 5-5" />
              </svg>
            </span>
            <span className="brand-name">较真</span>
          </div>
          <div className="search-page__eyebrow">谣言核查 · 帮你判断真假</div>
          <h1>别急着相信，<br /><span>先把证据找齐。</span></h1>
          <p>输入传闻、新闻标题或链接。我们会拆解事实、交叉检索，并说明结论来自哪里。</p>
        </header>

        <div className="search-panel">
          <label className="search-panel__label" htmlFor="claim-input">你想核查什么？</label>
          <div className="search-box">
            <textarea
              id="claim-input"
              className="search-box__input"
              rows={3}
              placeholder="例如：网传某地将实行新的公共交通政策，这是真的吗？"
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
              <span>{isStreaming ? "核查中" : "开始核查"}</span>
              <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m7 4 6 6-6 6" /></svg>
            </button>
          </div>

          {enabledSources.length > 0 && (
            <fieldset className="search-sources">
              <legend className="search-sources__label">检索范围</legend>
              <div className="search-sources__options">
                {enabledSources.map((source) => {
                  const checked = activeSources.includes(source.id);
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
            </fieldset>
          )}

          <div className="examples-block">
            <span className="examples-block__label">试试这些</span>
            <div className="examples">
              {demoCases.slice(0, 4).map((demo) => (
                <button key={demo.id} className="examples__chip" onClick={() => onSelectExample(demo)}>
                  {demo.title}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="trust-strip" aria-label="核查原则">
          <span><strong>01</strong> 多源交叉验证</span>
          <span><strong>02</strong> 证据逐条可追溯</span>
          <span><strong>03</strong> 不确定就明确说</span>
        </div>

        <div className="search-page__status" role="status">
          <span className={`status-dot status-dot--${backendState}`} />
          <span>{backendState === "online" ? "服务正常" : backendState === "offline" ? "服务离线" : backendState === "degraded" ? "服务降级" : "检测中..."}</span>
        </div>
      </div>
    </main>
  );
}
