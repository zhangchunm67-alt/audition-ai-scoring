import { Alert, Button, Descriptions, Modal, Select, Space, Table, Tabs, Tag, Tooltip, Typography } from "antd";
import dayjs from "dayjs";
import { useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { post, type S } from "../api/client";
import { LABEL_TEXT, LABEL_TONE, type Hit, type ItemResult, type ReportDetail as RD } from "../api/report";
import { useAuth } from "../auth";
import { AUDIENCE_ZH, STATUS_ZH, useAction, useFetch } from "../components/hooks";
import { IconDownload } from "../components/icons";
import { MetaList, MiniScore, PageHeader, Pill, SectionTitle } from "../components/ui";
import { fmtMs } from "../components/upload";

const JUDGE: Record<string, string> = { count: "计入", not_count: "不计入" };

function segName(seg: string, segments: RD["media"]["segments"]) {
  if (seg === "main") return "主体段";
  if (seg === "reading") return "朗读";
  const qs = segments.filter((s) => s.segment.startsWith("question:"));
  return `知识题 ${qs.findIndex((s) => s.segment === seg) + 1}`;
}

/** 点时间跳到视频对应位置。 */
function TimeLink({ ms, seek, children }: { ms: number; seek: (ms: number | null) => void; children?: ReactNode }) {
  return (
    <a className="time-link" role="button" tabIndex={0} onClick={() => seek(ms)}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), seek(ms))}>
      {children ?? fmtMs(ms)}
    </a>
  );
}

function HitTag({ h }: { h: Hit }) {
  const d = h.delta;
  const color = h.issue ? "red" : d && d > 0 ? "green" : "default";
  const txt = `${h.item_name} ${h.label ?? ""}${d ? `（${d > 0 ? "+" : ""}${d}）` : ""}`;
  return (
    <Tooltip title={`${h.item_name}：${JUDGE[String(h.judgment)] ?? h.judgment}。${h.reason ?? ""}（置信度 ${h.confidence.toFixed(2)}）`}>
      <Tag color={color} style={{ margin: 0 }}>{txt}</Tag>
    </Tooltip>
  );
}

/** 按评分表的位置称呼条目，如“人设塑造·普通话标准”。 */
export function itemLabel(d: RD, itemId: string): string {
  const it = d.result.items.find((x) => x.item_id === itemId);
  const dim = d.result.dimensions.find((x) => x.id === it?.dimension);
  return it ? `${dim?.name ?? it.dimension}·${it.name}` : itemId;
}

function Items({ d, seek }: { d: RD; seek: (ms: number | null) => void }) {
  const dimName = Object.fromEntries(d.result.dimensions.map((x) => [x.id, x.name]));
  const evByItem = (id: string) => d.evidence.filter((e) => e.item_id === id);
  return (
    <Table<ItemResult>
      className="table-card"
      size="small"
      rowKey="item_id"
      pagination={false}
      dataSource={d.result.items}
      scroll={{ x: 760 }}
      expandable={{
        rowExpandable: (it) => evByItem(it.item_id).length > 0,
        expandedRowRender: (it) => (
          <Table<Hit> size="small" rowKey="evidence_id" pagination={false} dataSource={evByItem(it.item_id)} columns={[
            { title: "时间", dataIndex: "start_ms", width: 80, render: (v) => (v == null ? "—" : <TimeLink ms={v} seek={seek} />) },
            { title: "原句或指标", render: (_, e) => e.quote ?? (e.value != null ? `${e.label} = ${e.value}` : e.label) },
            { title: "判定", width: 110, render: (_, e) => `${e.label && e.kind !== "metric" ? `${e.label} · ` : ""}${JUDGE[String(e.judgment)] ?? e.judgment ?? ""}` },
            { title: "加扣分", dataIndex: "delta", width: 70, render: (v) => (v == null ? "" : <span className="num" style={{ color: v > 0 ? "var(--ok)" : v < 0 ? "var(--bad)" : undefined }}>{v > 0 ? `+${v}` : v}</span>) },
            { title: "理由", dataIndex: "reason" },
            { title: "置信度", dataIndex: "confidence", width: 70, render: (c: number) => <span className="num" style={{ color: c < 0.6 ? "var(--bad)" : undefined }}>{c.toFixed(2)}</span> },
          ]} />
        ),
      }}
      columns={[
        { title: "维度", dataIndex: "dimension", width: 96, render: (v: string) => <span className="muted">{dimName[v] ?? v}</span> },
        { title: "条目", width: 150, render: (_, it) => it.name },
        { title: "得分", width: 150, render: (_, it) => (it.status === "not_applicable"
          ? <span className="faint">不适用</span>
          : <MiniScore ratio={it.score == null || !it.max ? null : it.score / it.max} text={<>{it.score == null ? "—" : Math.round(it.score * 10) / 10} <span className="faint">/ {it.max}</span></>} />) },
        { title: "标记", width: 130, render: (_, it) => (
          <Space size={4} wrap>
            {it.low_confidence && <Tooltip title={it.low_confidence_reasons.join("；")}><Tag color="orange" style={{ margin: 0 }}>低置信</Tag></Tooltip>}
            {it.status === "missing_evidence" && <Tag color="red" style={{ margin: 0 }}>缺证据</Tag>}
            {it.source === "human" && (
              <Tooltip title={`评委 ${it.human?.by ?? ""} 打分${it.suggested_score != null ? `，机器建议 ${it.suggested_score}` : ""}${it.human?.note ? `。备注：${it.human.note}` : ""}`}>
                <Tag color="blue" style={{ margin: 0 }}>人工打分</Tag>
              </Tooltip>
            )}
          </Space>
        ) },
        { title: "说明", render: (_, it) => <span className="muted" style={{ fontSize: 13 }}>{it.notes.join("；")}</span> },
      ]}
    />
  );
}

function Sentences({ d, seek }: { d: RD; seek: (ms: number | null) => void }) {
  const [onlyIssues, setOnlyIssues] = useState(false);
  return (
    <div className="stack">
      <Space wrap>
        <Button type={onlyIssues ? "primary" : "default"} onClick={() => setOnlyIssues(!onlyIssues)}>{onlyIssues ? "显示全部句子" : "只看有问题的句子"}</Button>
        <span className="muted" style={{ fontSize: 13 }}>点时间跳到视频对应位置。红色为扣分或未得分；示范说法由 AI 生成，仅供辅导参考。</span>
      </Space>
      {d.sentences.map((seg) => (
        <section key={seg.segment} className="panel panel-pad">
          <SectionTitle>{segName(seg.segment, d.media.segments)}</SectionTitle>
          {seg.segment_hits.length > 0 && <Space size={4} wrap style={{ marginBottom: 12 }}>{seg.segment_hits.map((h) => <HitTag key={h.evidence_id} h={h} />)}</Space>}
          {seg.sentences.filter((s) => !onlyIssues || s.issue).map((s) => (
            <div key={`${s.segment}-${s.start_ms}`} data-testid="sentence" className={`sentence${s.issue ? " is-issue" : ""}`}>
              <TimeLink ms={s.start_ms} seek={seek} />
              <div className="sentence-body">
                <span>{s.text}</span>
                {s.hits.length > 0 && <div className="hits">{s.hits.map((h) => <HitTag key={h.evidence_id} h={h} />)}</div>}
                {s.suggestion && <div className="suggestion">示范说法（AI 生成）：{s.suggestion}</div>}
              </div>
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}

function Rescore({ id, onDone }: { id: string; onDone: (r: RD) => void }) {
  const [open, setOpen] = useState(false);
  const [rv, setRv] = useState<string>();
  const { data } = useFetch<S<"RubricSummary">[]>(open ? "/rubrics" : null);
  const act = useAction();
  return (
    <>
      <Button onClick={() => setOpen(true)}>按新版评分标准重算</Button>
      <Modal title="按新版评分标准重算" open={open} onCancel={() => setOpen(false)} okButtonProps={{ disabled: !rv }}
        onOk={async () => {
          const r = await act(() => post<RD>(`/reports/${id}/rescore`, { rubric_version_id: rv }), "已生成新修订");
          if (r) (setOpen(false), onDone(r));
        }}>
        <Typography.Paragraph>用已存的证据按所选版本重新计分，不重跑模型；生成新的报告修订，当前修订保留。新版本如需更多轮次，需要重新处理录像。</Typography.Paragraph>
        <Select style={{ width: "100%" }} placeholder="选择评分标准版本" value={rv} onChange={setRv}
          options={(data ?? []).filter((x) => x.status !== "retired").map((x) => ({ value: x.id, label: `${x.version}（${STATUS_ZH[x.status]}）` }))} />
      </Modal>
    </>
  );
}

function ScoreBoard({ d }: { d: RD }) {
  const dims = d.result.dimensions;
  return (
    <div className="score-board" style={{ "--dims": dims.length } as CSSProperties}>
      <div className="score-cell">
        <div className="score-label">总档位</div>
        <div className="score-num">{d.result.total_grade}</div>
        <div className="score-sub">达标线 &lt; {d.result.threshold}</div>
      </div>
      {dims.map((x) => (
        <div className="score-cell" key={x.id}>
          <div className="score-label">{x.name}</div>
          <div className="score-num">{x.score ?? "—"}<small>分 · {x.grade} 档</small></div>
          <div className="bar" aria-hidden><i style={{ width: `${Math.max(0, Math.min(100, x.score ?? 0))}%` }} /></div>
        </div>
      ))}
    </div>
  );
}

export default function ReportDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const { data: d } = useFetch<RD>(`/reports/${id}`);
  const revs = useFetch<{ id: string; revision: number; label: string; rubric_version: string; superseded_at: string | null }[]>(`/reports/${id}/revisions`);
  const { can } = useAuth();
  const video = useRef<HTMLVideoElement>(null);
  const [tab, setTab] = useState("overview");
  if (!d) return null;
  const seek = (ms: number | null) => {
    if (ms == null || !video.current) return;
    video.current.currentTime = ms / 1000;
    void video.current.play().catch(() => undefined);
  };
  const all = can("report.read_all");
  const live = d.mode === "live";
  return (
    <>
      <PageHeader
        back={{ to: "/reports", label: all ? "报告与排名" : "我的试镜记录" }}
        title={`${d.candidate_name} 的${live ? "录播" : "试镜"}报告`}
        tags={<>
          <Pill tone={LABEL_TONE[d.label]} large data-testid="label">{LABEL_TEXT[d.label]}</Pill>
          {d.critical && <Tag color="gold" style={{ margin: 0 }}>临界</Tag>}
          {d.informal && <Tag style={{ margin: 0 }}>非正式</Tag>}
        </>}
        actions={<>
          {all && <Button type="link" onClick={() => nav(`/recordings/${d.recording_id}`)}>查看录像记录</Button>}
          {can("config.write") && !d.superseded_at && <Rescore id={d.id} onDone={(r) => nav(`/reports/${r.id}`)} />}
          <Button icon={<IconDownload />} href={`/api/reports/${d.id}/pdf`}>导出 PDF</Button>
        </>}
      />
      <p className="verdict">{d.verdict.reason}</p>
      <div className="stack-sm" style={{ marginBottom: 20 }}>
        {d.superseded_at && <Alert type="warning" showIcon message="这是旧修订，已被按新版评分标准重算的版本取代" />}
        {Object.values(d.trace.model_manifest).some((v) => String(v).startsWith("mock")) && <Alert type="error" showIcon message="模拟流程结果：本报告含 Mock 测试模型输出，不是该主播的真实综合得分，不进入默认真实排名。" />}
        {d.informal && <Alert type="warning" showIcon message="非正式报告：使用了草稿版的评分标准或检测配置（含待确认规则和测试占位值），或用了开发测试用的模拟模型，仅供试用，不作录用依据" />}
        {d.critical && (
          <Alert type="info" showIcon message={`临界样本：总档位接近达标线，共 ${d.verdict.rounds.length} 轮取多数，请谨慎使用`}
            description={d.verdict.rounds.map((r) => `第 ${r.round_no} 轮 ${r.total_grade} 档（${r.grade_pass ? "达标" : "不达标"}）`).join("；") + `；报告展示第 ${d.display_round} 轮`} />
        )}
        {d.result.low_confidence_items.length > 0 && <Alert type="warning" showIcon message={`低置信条目：${d.result.low_confidence_items.map((i) => itemLabel(d, i)).join("、")}（照常出分，判断把握不足，可点开证据核对）`} />}
      </div>
      <div className="split-report">
        <div>
          <ScoreBoard d={d} />
          <Tabs activeKey={tab} onChange={setTab} items={[
            { key: "overview", label: "总览与条目", children: <Items d={d} seek={seek} /> },
            { key: "sentences", label: "逐句评分", children: <Sentences d={d} seek={seek} /> },
            { key: "trace", label: "追溯信息", children: (
              <>
                <Descriptions bordered size="small" column={1}>
                  <Descriptions.Item label="评分标准">{d.trace.rubric_version}（{STATUS_ZH[d.trace.rubric_status]}）</Descriptions.Item>
                  <Descriptions.Item label="配置哈希"><Typography.Text code copyable>{d.trace.config_hash}</Typography.Text></Descriptions.Item>
                  <Descriptions.Item label="检测配置">{d.trace.detector_config_version}（{STATUS_ZH[d.trace.detector_config_status]}）</Descriptions.Item>
                  <Descriptions.Item label="红线">{d.result.redlines_enabled ? `启用（词表 ${d.trace.redline_lexicon_version}）` : "试镜不做红线（C33）"}</Descriptions.Item>
                  {/* 模型清单里有对象（人工打分分工 human_review），直接渲染会让整页白屏 */}
                  {Object.entries(d.trace.model_manifest as Record<string, unknown>).map(([k, v]) => (
                    <Descriptions.Item key={k} label={k}><span style={{ overflowWrap: "anywhere" }}>{v !== null && typeof v === "object" ? JSON.stringify(v) : String(v)}</span></Descriptions.Item>
                  ))}
                  <Descriptions.Item label="报告生成">{dayjs(d.created_at).format("YYYY-MM-DD HH:mm:ss")}，第 {d.revision} 版</Descriptions.Item>
                </Descriptions>
                <SectionTitle style={{ marginTop: 24 }}>修订历史</SectionTitle>
                <Table className="table-card" size="small" rowKey="id" pagination={false} dataSource={revs.data} columns={[
                  { title: "版本", dataIndex: "revision", render: (v, r) => (r.id === d.id ? `第 ${v} 版（当前）` : <Link to={`/reports/${r.id}`}>第 {v} 版</Link>) },
                  { title: "评分标准", dataIndex: "rubric_version" },
                  { title: "结论", dataIndex: "label", render: (l) => LABEL_TEXT[l] },
                  { title: "状态", dataIndex: "superseded_at", render: (s) => (s ? "已被取代" : "最新") },
                ]} />
              </>
            ) },
          ]} />
        </div>
        <aside className="sticky-col stack">
          {d.media.video_asset_id ? (
            <div className="video-frame">
              <video ref={video} src={`/api/media/${d.media.video_asset_id}`} controls preload="metadata" data-testid="report-video" />
            </div>
          ) : (
            <Alert type="info" message={d.media.video_deleted ? "视频已按保存期限删除，报告和文字证据保留" : "没有视频"} />
          )}
          {d.media.segments.length > 0 && (
            <div className="seg-chips" aria-label="分段">
              {d.media.segments.map((s) => (
                <button type="button" className="seg-chip" key={s.segment} onClick={() => seek(s.start_ms)}>
                  {segName(s.segment, d.media.segments)}<span>{fmtMs(s.start_ms)}</span>
                </button>
              ))}
            </div>
          )}
          <div className="panel panel-pad">
            <MetaList items={[
              { label: "产品", value: d.product_name },
              { label: "类型", value: live ? "录播（无题单，整段评分）" : "试镜（按题单录制）" },
              { label: live ? "录播编号" : "题单", value: <span className="mono">{d.sheet_code}</span> },
              { label: "适用达标线", value: AUDIENCE_ZH[d.audience] ?? d.audience },
              { label: "道具", value: d.props_available ? "有（计“肢体语言（贴片/KT板）”）" : "无（“肢体语言（贴片/KT板）”不适用）" },
              { label: "提交时间", value: d.submitted_at ? dayjs(d.submitted_at).format("YYYY-MM-DD HH:mm") : "—" },
            ]} />
          </div>
        </aside>
      </div>
    </>
  );
}
