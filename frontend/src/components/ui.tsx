import { ArrowLeftOutlined } from "@ant-design/icons";
import type { CSSProperties, ReactNode } from "react";
import { Link } from "react-router-dom";

/** 产品名和副标题，登录页和顶栏共用。 */
export const BRAND = { name: "试镜评分", sub: "腾宝 · 主播工作台" };

/** 品牌标记：录制指示灯。 */
export function BrandMark() {
  return <span className="brand-mark" aria-hidden><i /></span>;
}

/** 页头：返回链接、标题（h1）、标题旁的状态、说明、右侧操作。每个页面只用一个。 */
export function PageHeader({ title, tags, description, actions, back }: {
  title: ReactNode;
  tags?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  back?: { to: string; label: string };
}) {
  return (
    <header className="page-head">
      {back && (
        <Link to={back.to} className="page-back">
          <ArrowLeftOutlined />
          {back.label}
        </Link>
      )}
      <div className="page-head-row">
        <div className="page-head-main">
          <div className="page-title-row">
            <h1 className="page-title">{title}</h1>
            {tags}
          </div>
          {description && <p className="page-desc">{description}</p>}
        </div>
        {actions && <div className="page-actions">{actions}</div>}
      </div>
    </header>
  );
}

/** 列表上方的一行：左边筛选，右边次要操作。 */
export function Toolbar({ children, right }: { children?: ReactNode; right?: ReactNode }) {
  return (
    <div className="toolbar">
      <div className="toolbar-group">{children}</div>
      {right && <div className="toolbar-group">{right}</div>}
    </div>
  );
}

export type Tone = "neutral" | "ok" | "warn" | "bad" | "info" | "progress";

/** 状态胶囊：带圆点，全站的状态都用它，颜色含义固定（绿＝完成或通过，黄＝等人处理，红＝失败或不通过，蓝＝系统在处理）。 */
export function Pill({ tone = "neutral", children, large, dot = true, ...rest }: {
  tone?: Tone; children: ReactNode; large?: boolean; dot?: boolean; "data-testid"?: string; title?: string;
}) {
  return <span className={`pill pill-${tone}${large ? " pill-lg" : ""}${dot ? "" : " no-dot"}`} {...rest}>{children}</span>;
}

/** 可点的筛选胶囊，带条数。 */
export function FilterPills<T extends string>({ value, onChange, options, label }: {
  value: T; onChange: (v: T) => void; options: { value: T; label: string; count?: number }[]; label: string;
}) {
  return (
    <div className="filter-pills" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" className="filter-pill" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
          {o.count != null && <b>{o.count}</b>}
        </button>
      ))}
    </div>
  );
}

export type MetaItem = { label: ReactNode; value: ReactNode } | null | false | undefined;

const orDash = (v: ReactNode) => (v == null || v === "" || v === false ? <span className="faint">—</span> : v);

/** 横向的信息栅格：小标签在上、值在下。详情页顶部的基本信息用。 */
export function MetaGrid({ items, columns = 4, plain, style }: { items: MetaItem[]; columns?: number; plain?: boolean; style?: CSSProperties }) {
  const rows = items.filter(Boolean) as { label: ReactNode; value: ReactNode }[];
  return (
    <dl className={`meta-grid${plain ? " plain" : ""}`} style={{ "--cols": columns, margin: 0, ...style } as CSSProperties}>
      {rows.map((it, i) => (
        <div key={i}>
          <dt>{it.label}</dt>
          <dd>{orDash(it.value)}</dd>
        </div>
      ))}
    </dl>
  );
}

/** 纵向的信息列表：标签在左、值在右。侧栏和抽屉用。 */
export function MetaList({ items, style }: { items: MetaItem[]; style?: CSSProperties }) {
  const rows = items.filter(Boolean) as { label: ReactNode; value: ReactNode }[];
  return (
    <dl className="meta-list" style={style}>
      {rows.map((it, i) => [<dt key={`t${i}`}>{it.label}</dt>, <dd key={`d${i}`}>{orDash(it.value)}</dd>])}
    </dl>
  );
}

/** 指标块：说明在上，大数字在下。 */
export function Stat({ label, value, unit, tone, note }: { label: ReactNode; value: ReactNode; unit?: ReactNode; tone?: "ok" | "bad"; note?: ReactNode }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className={`stat-value${tone ? ` is-${tone}` : ""}${typeof value === "string" && value.includes(" / ") ? " is-compact" : ""}`}>
        {value}
        {unit && <small>{unit}</small>}
      </div>
      {note && <div className="stat-note">{note}</div>}
    </div>
  );
}

export function SectionTitle({ children, extra, style }: { children: ReactNode; extra?: ReactNode; style?: CSSProperties }) {
  return (
    <h2 className="section-title" style={style}>
      {children}
      {extra}
    </h2>
  );
}

/** 分数加一条细进度条。ratio 为空时不画条。 */
export function MiniScore({ text, ratio }: { text: ReactNode; ratio: number | null }) {
  const pct = ratio == null ? null : Math.max(0, Math.min(1, ratio));
  return (
    <span className="mini-score">
      {pct != null && (
        <span className="bar" aria-hidden>
          <i className={pct < 0.5 ? "is-low" : pct < 0.75 ? "is-mid" : undefined} style={{ width: `${pct * 100}%` }} />
        </span>
      )}
      <span>{text}</span>
    </span>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty-state">
      <b>{title}</b>
      {children}
    </div>
  );
}

const CONFIG_TONE: Record<string, Tone> = { draft: "warn", published: "ok", retired: "neutral", issued: "info", used: "neutral", void: "neutral" };
const CONFIG_ZH: Record<string, string> = { draft: "草稿", published: "已发布", retired: "已停用", issued: "未使用", used: "已使用", void: "已作废" };

/** 配置版本和题单的状态：草稿、已发布、已停用；未使用、已使用、已作废。 */
export function ConfigStatus({ status }: { status: string }) {
  return <Pill tone={CONFIG_TONE[status] ?? "neutral"}>{CONFIG_ZH[status] ?? status}</Pill>;
}
