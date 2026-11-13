import { Alert, Button, Card, Col, Descriptions, Modal, Row, Select, Space, Statistic, Table, Tabs, Tag, Tooltip, Typography } from "antd";
import dayjs from "dayjs";
import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { post, type S } from "../api/client";
import { LABEL_COLOR, LABEL_TEXT, type Hit, type ItemResult, type ReportDetail as RD } from "../api/report";
import { useAuth } from "../auth";
import { AUDIENCE_ZH, STATUS_ZH, useAction, useFetch } from "../components/hooks";
import { fmtMs } from "../components/upload";

const JUDGE: Record<string, string> = { count: "计入", not_count: "不计入" };

function segName(seg: string, segments: RD["media"]["segments"]) {
  if (seg === "main") return "主体段";
  if (seg === "reading") return "朗读";
  const qs = segments.filter((s) => s.segment.startsWith("question:"));
  return `知识题 ${qs.findIndex((s) => s.segment === seg) + 1}`;
}

function HitTag({ h }: { h: Hit }) {
  const d = h.delta;
  const color = h.issue ? "red" : d && d > 0 ? "green" : "default";
  const txt = `${h.item_name} ${h.label ?? ""}${d ? `（${d > 0 ? "+" : ""}${d}）` : ""}`;
  return (
    <Tooltip title={`${h.item_name}：${JUDGE[String(h.judgment)] ?? h.judgment}。${h.reason ?? ""}（置信度 ${h.confidence.toFixed(2)}）`}>
      <Tag color={color} style={{ marginBottom: 4 }}>{txt}</Tag>
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
      size="small"
      rowKey="item_id"
      pagination={false}
      dataSource={d.result.items}
      expandable={{
        expandedRowRender: (it) => (
          <Table<Hit> size="small" rowKey="evidence_id" pagination={false} dataSource={evByItem(it.item_id)} columns={[
            { title: "时间", dataIndex: "start_ms", width: 70, render: (v) => (v == null ? "—" : <a onClick={() => seek(v)}>{fmtMs(v)}</a>) },
            { title: "原句或指标", render: (_, e) => e.quote ?? (e.value != null ? `${e.label} = ${e.value}` : e.label) },
            { title: "判定", width: 90, render: (_, e) => `${e.label && e.kind !== "metric" ? `${e.label} · ` : ""}${JUDGE[String(e.judgment)] ?? e.judgment ?? ""}` },
            { title: "加扣分", dataIndex: "delta", width: 70, render: (v) => (v == null ? "" : v > 0 ? `+${v}` : v) },
            { title: "理由", dataIndex: "reason" },
            { title: "置信度", dataIndex: "confidence", width: 70, render: (c: number) => <span style={{ color: c < 0.6 ? "#d4380d" : undefined }}>{c.toFixed(2)}</span> },
          ]} />
        ),
      }}
      columns={[
        { title: "维度", dataIndex: "dimension", width: 90, render: (v: string) => dimName[v] ?? v },
        { title: "条目", render: (_, it) => it.name },
        { title: "得分", width: 90, render: (_, it) => (it.status === "not_applicable" ? "不适用" : `${it.score == null ? "—" : Math.round(it.score * 10) / 10} / ${it.max}`) },
        { title: "标记", width: 160, render: (_, it) => (
          <Space size={4} wrap>
            {it.low_confidence && <Tooltip title={it.low_confidence_reasons.join("；")}><Tag color="orange">低置信</Tag></Tooltip>}
            {it.status === "missing_evidence" && <Tag color="red">缺证据</Tag>}
            {it.source === "human" && (
              <Tooltip title={`评委 ${it.human?.by ?? ""} 打分${it.suggested_score != null ? `，机器建议 ${it.suggested_score}` : ""}${it.human?.note ? `。备注：${it.human.note}` : ""}`}>
                <Tag color="blue">人工打分</Tag>
              </Tooltip>
            )}
          </Space>
        ) },
        { title: "说明", render: (_, it) => <Typography.Text type="secondary">{it.notes.join("；")}</Typography.Text> },
      ]}
    />
  );
}

function Sentences({ d, seek }: { d: RD; seek: (ms: number | null) => void }) {
  const [onlyIssues, setOnlyIssues] = useState(false);
  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Button type={onlyIssues ? "primary" : "default"} onClick={() => setOnlyIssues(!onlyIssues)}>{onlyIssues ? "显示全部句子" : "只看有问题的句子"}</Button>
        <Typography.Text type="secondary">点时间跳到视频对应位置。红色为扣分或未得分；示范说法由 AI 生成，仅供辅导参考。</Typography.Text>
      </Space>
      {d.sentences.map((seg) => (
        <Card key={seg.segment} size="small" title={segName(seg.segment, d.media.segments)} style={{ marginBottom: 12 }}
          extra={seg.segment_hits.length ? <Space size={4} wrap>{seg.segment_hits.map((h) => <HitTag key={h.evidence_id} h={h} />)}</Space> : null}>
          {seg.sentences.filter((s) => !onlyIssues || s.issue).map((s) => (
            <div key={`${s.segment}-${s.start_ms}`} data-testid="sentence" style={{ padding: "6px 0", borderBottom: "1px solid #f0f0f0", background: s.issue ? "#fff1f0" : undefined }}>
              <a onClick={() => seek(s.start_ms)} style={{ marginRight: 8 }}>{fmtMs(s.start_ms)}</a>
              <span>{s.text}</span>
              <div>{s.hits.map((h) => <HitTag key={h.evidence_id} h={h} />)}</div>
              {s.suggestion && <div style={{ color: "#389e0d" }}>示范说法（AI 生成）：{s.suggestion}</div>}
            </div>
          ))}
        </Card>
      ))}
    </>
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
  const dims = Object.fromEntries(d.result.dimensions.map((x) => [x.id, x]));
  return (
    <>
      <Space style={{ marginBottom: 8 }} wrap>
        <Typography.Title level={4} style={{ margin: 0 }}>{d.candidate_name} 的试镜报告</Typography.Title>
        <Tag color={LABEL_COLOR[d.label]} style={{ fontSize: 16, padding: "2px 12px" }} data-testid="label">{LABEL_TEXT[d.label]}</Tag>
        {d.critical && <Tag color="gold">临界</Tag>}
        {d.informal && <Tag>非正式</Tag>}
        <Button href={`/api/reports/${d.id}/pdf`}>导出 PDF</Button>
        {can("config.write") && !d.superseded_at && <Rescore id={d.id} onDone={(r) => nav(`/reports/${r.id}`)} />}
        {can("report.read_all") && <Link to={`/recordings/${d.recording_id}`}>查看录像记录</Link>}
      </Space>
      <Typography.Paragraph style={{ fontSize: 15 }}>{d.verdict.reason}</Typography.Paragraph>
      {d.superseded_at && <Alert type="warning" showIcon style={{ marginBottom: 8 }} message="这是旧修订，已被按新版评分标准重算的版本取代" />}
      {Object.values(d.trace.model_manifest).some((v) => String(v).startsWith("mock")) && <Alert type="error" showIcon style={{ marginBottom: 8 }} message="模拟流程结果：本报告含 Mock 测试模型输出，不是该主播的真实综合得分，不进入默认真实排名。" />}
      {d.informal && <Alert type="warning" showIcon style={{ marginBottom: 8 }} message="非正式报告：使用了草稿版的评分标准或检测配置（含待确认规则和测试占位值），或用了开发测试用的模拟模型，仅供试用，不作录用依据" />}
      {d.critical && (
        <Alert type="info" showIcon style={{ marginBottom: 8 }} message={`临界样本：总档位接近达标线，共 ${d.verdict.rounds.length} 轮取多数，请谨慎使用`}
          description={d.verdict.rounds.map((r) => `第 ${r.round_no} 轮 ${r.total_grade} 档（${r.grade_pass ? "达标" : "不达标"}）`).join("；") + `；报告展示第 ${d.display_round} 轮`} />
      )}
      {d.result.low_confidence_items.length > 0 && <Alert type="warning" showIcon style={{ marginBottom: 8 }} message={`低置信条目：${d.result.low_confidence_items.map((i) => itemLabel(d, i)).join("、")}（照常出分，判断把握不足，可点开证据核对）`} />}
      <Row gutter={16}>
        <Col span={16}>
          <Tabs activeKey={tab} onChange={setTab} items={[
            { key: "overview", label: "总览与条目", children: (
              <>
                <Row gutter={12} style={{ marginBottom: 16 }}>
                  <Col span={4}><Statistic title="总档位" value={d.result.total_grade} suffix={`/ 达标线 < ${d.result.threshold}`} /></Col>
                  {["P", "S", "L", "O"].map((k) => (
                    <Col span={5} key={k}><Statistic title={dims[k].name} value={dims[k].score ?? "—"} suffix={`分 · ${dims[k].grade} 档`} /></Col>
                  ))}
                </Row>
                <Items d={d} seek={seek} />
              </>
            ) },
            { key: "sentences", label: "逐句评分", children: <Sentences d={d} seek={seek} /> },
            { key: "trace", label: "追溯信息", children: (
              <>
                <Descriptions bordered size="small" column={1}>
                  <Descriptions.Item label="评分标准">{d.trace.rubric_version}（{STATUS_ZH[d.trace.rubric_status]}）</Descriptions.Item>
                  <Descriptions.Item label="配置哈希"><Typography.Text code copyable>{d.trace.config_hash}</Typography.Text></Descriptions.Item>
                  <Descriptions.Item label="检测配置">{d.trace.detector_config_version}（{STATUS_ZH[d.trace.detector_config_status]}）</Descriptions.Item>
                  <Descriptions.Item label="红线">{d.result.redlines_enabled ? `启用（词表 ${d.trace.redline_lexicon_version}）` : "试镜不做红线（C33）"}</Descriptions.Item>
                  {Object.entries(d.trace.model_manifest).map(([k, v]) => <Descriptions.Item key={k} label={k}>{v}</Descriptions.Item>)}
                  <Descriptions.Item label="报告生成">{dayjs(d.created_at).format("YYYY-MM-DD HH:mm:ss")}，第 {d.revision} 版</Descriptions.Item>
                </Descriptions>
                <Typography.Title level={5} style={{ marginTop: 16 }}>修订历史</Typography.Title>
                <Table size="small" rowKey="id" pagination={false} dataSource={revs.data} columns={[
                  { title: "版本", dataIndex: "revision", render: (v, r) => (r.id === d.id ? `第 ${v} 版（当前）` : <Link to={`/reports/${r.id}`}>第 {v} 版</Link>) },
                  { title: "评分标准", dataIndex: "rubric_version" },
                  { title: "结论", dataIndex: "label", render: (l) => LABEL_TEXT[l] },
                  { title: "状态", dataIndex: "superseded_at", render: (s) => (s ? "已被取代" : "最新") },
                ]} />
              </>
            ) },
          ]} />
        </Col>
        <Col span={8}>
          <div style={{ position: "sticky", top: 16 }}>
            {d.media.video_asset_id ? (
              <video ref={video} src={`/api/media/${d.media.video_asset_id}`} controls preload="metadata" style={{ width: "100%", background: "#000" }} data-testid="report-video" />
            ) : (
              <Alert type="info" message={d.media.video_deleted ? "视频已按保存期限删除，报告和文字证据保留" : "没有视频"} />
            )}
            <Descriptions size="small" column={1} style={{ marginTop: 12 }}>
              <Descriptions.Item label="产品">{d.product_name}</Descriptions.Item>
              <Descriptions.Item label={d.mode === "live" ? "录播（无题单，整段评分）" : "题单"}>{d.sheet_code}</Descriptions.Item>
              <Descriptions.Item label="适用达标线">{AUDIENCE_ZH[d.audience] ?? d.audience}</Descriptions.Item>
              <Descriptions.Item label="道具">{d.props_available ? "有（计“肢体语言（贴片/KT板）”）" : "无（“肢体语言（贴片/KT板）”不适用）"}</Descriptions.Item>
              <Descriptions.Item label="提交时间">{d.submitted_at ? dayjs(d.submitted_at).format("YYYY-MM-DD HH:mm") : "—"}</Descriptions.Item>
            </Descriptions>
            <Typography.Title level={5}>分段</Typography.Title>
            {d.media.segments.map((s) => (
              <div key={s.segment}><a onClick={() => seek(s.start_ms)}>{fmtMs(s.start_ms)}</a> {segName(s.segment, d.media.segments)}</div>
            ))}
          </div>
        </Col>
      </Row>
    </>
  );
}
