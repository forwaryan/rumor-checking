import type { DemoCaseSummary, InputType } from "@/types/report";

const inputTypeOptions: Array<{ value: InputType; label: string }> = [
  { value: "auto", label: "自动判断" },
  { value: "text", label: "正文" },
  { value: "url", label: "URL" },
  { value: "question", label: "问题" },
];

interface InputPanelProps {
  value: string;
  inputType: InputType;
  selectedDemoId: string | null;
  demoCases: DemoCaseSummary[];
  backendState: "checking" | "online" | "offline" | "degraded";
  isSubmitting: boolean;
  onValueChange: (value: string) => void;
  onInputTypeChange: (value: InputType) => void;
  onSelectDemo: (demoCase: DemoCaseSummary) => void;
  onSubmit: () => void;
  onReset: () => void;
}

function getBackendLabel(state: InputPanelProps["backendState"]) {
  switch (state) {
    case "online":
      return "后端在线";
    case "degraded":
      return "后端降级";
    case "offline":
      return "后端离线";
    default:
      return "检查连通性";
  }
}

export function InputPanel({
  value,
  inputType,
  selectedDemoId,
  demoCases,
  backendState,
  isSubmitting,
  onValueChange,
  onInputTypeChange,
  onSelectDemo,
  onSubmit,
  onReset,
}: InputPanelProps) {
  return (
    <section className="panel panel--hero">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Analyze Workspace</p>
          <h2>输入区</h2>
        </div>
        <div className={`health-pill health-pill--${backendState}`}>{getBackendLabel(backendState)}</div>
      </div>

      <p className="panel-copy">
        支持 URL、正文和问题输入。示例输入会优先走真实 <code>POST /api/v1/analyze</code>；只有后端离线或请求失败时，
        才回退到本地 demo payload。
      </p>

      <div className="type-switcher" role="tablist" aria-label="输入类型">
        {inputTypeOptions.map((option) => {
          const active = option.value === inputType;
          return (
            <button
              key={option.value}
              type="button"
              className={`type-chip${active ? " is-active" : ""}`}
              onClick={() => onInputTypeChange(option.value)}
            >
              {option.label}
            </button>
          );
        })}
      </div>

      <label className="field-shell">
        <span className="field-label">待核查内容</span>
        <textarea
          className="input-area"
          rows={6}
          placeholder="粘贴新闻 URL、正文，或直接输入你的问题。"
          value={value}
          onChange={(event) => onValueChange(event.target.value)}
        />
      </label>

      <div className="demo-strip">
        <div className="demo-strip__header">
          <span className="field-label">稳定 demo case</span>
          <span className="demo-strip__hint">示例输入已对齐当前后端 scenario；离线时会回退到同主题本地 payload</span>
        </div>
        <div className="demo-grid">
          {demoCases.map((demoCase) => {
            const active = demoCase.id === selectedDemoId;
            return (
              <button
                key={demoCase.id}
                type="button"
                className={`demo-card${active ? " is-active" : ""}`}
                onClick={() => onSelectDemo(demoCase)}
              >
                <strong>{demoCase.title}</strong>
                <span>{demoCase.description}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="action-row">
        <button type="button" className="button button--primary" onClick={onSubmit} disabled={isSubmitting}>
          {isSubmitting ? "分析中..." : selectedDemoId ? "运行 demo" : "开始分析"}
        </button>
        <button type="button" className="button button--ghost" onClick={onReset} disabled={isSubmitting}>
          清空输入
        </button>
      </div>
    </section>
  );
}
