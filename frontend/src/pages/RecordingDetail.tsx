import { Alert, Button, Card, Col, Descriptions, Input, InputNumber, Popconfirm, Progress, Row, Space, Table, Tag, Typography, Upload } from "antd";
import dayjs from "dayjs";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { post, put, type S } from "../api/client";
import { useAuth } from "../auth";
import { AUDIENCE_ZH, MODE_ZH, useAction, useFetch } from "../components/hooks";
import { localUrlOf } from "../components/localMedia";
import { fmtBytes, fmtMs, uploadFile } from "../components/upload";
import { REC_STATUS } from "./Recordings";

type Rec = S<"RecordingOut">;
type Marks = { main: number | null; questions: (number | null)[]; reading: number | null; objections: number[] };

function initialMarks(rec: Rec): Marks {
  const seg = (name: string) => rec.segments.find((s) => s.segment === name)?.start_ms as number | undefined;
  return {
    main: seg("main") ?? null,
    questions: rec.sheet_questions.map((q) => seg(`question:${q.question_id}`) ?? null),
    reading: seg("reading") ?? null,
    objections: rec.objection_times.length ? rec.objection_times.map((o) => o.at_ms as number) : rec.sheet_objections.map((o) => o.at_ms as number),
  };
}

/** 边看边标：主体段、每道知识题、朗读段的起点，以及每条异议实际出现的时间（默认取题单，C28、C29）。 */
function Marker({ rec, src, onSaved }: { rec: Rec; src: string; onSaved: (r: Rec) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [m, setM] = useState<Marks>(() => initialMarks(rec));
  const act = useAction();
  const now = () => Math.round((video.current?.currentTime ?? 0) * 1000);
  const seek = (ms: number | null) => ms != null && video.current && (video.current.currentTime = ms / 1000);
  const ready = m.main != null && m.reading != null && m.questions.every((q) => q != null);
  const row = (key: string, label: string, ms: number | null, set: (v: number) => void, jump?: number | null) => ({ key, label, ms, set, jump: jump ?? ms });
  const rows = [
    row("main", "主体段开始", m.main, (v) => setM({ ...m, main: v })),
    ...rec.sheet_questions.map((q, i) =>
      row(`q${i}`, `知识题 ${i + 1}：${q.text}`, m.questions[i], (v) => setM({ ...m, questions: m.questions.map((x, j) => (j === i ? v : x)) })),
    ),
    row("reading", "朗读开始", m.reading, (v) => setM({ ...m, reading: v })),
  ];
  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} md={12}>
        <video ref={video} src={src} controls style={{ width: "100%", background: "#000" }} data-testid="marker-video" />
        <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>播放到某段开头时点“设为当前时间”。异议时间默认按题单（相对主体段开始），如候选人实际回应时间不同，可在视频里定位后修正。</Typography.Paragraph>
      </Col>
      <Col xs={24} md={12}>
        <Table size="small" pagination={false} rowKey="key" dataSource={rows} columns={[
          { title: "分段", dataIndex: "label", ellipsis: true },
          { title: "起点", dataIndex: "ms", width: 90, render: (v) => fmtMs(v) },
          { title: "", width: 190, render: (_, r) => (
            <Space>
              <Button size="small" onClick={() => r.set(now())}>设为当前时间</Button>
              <Button size="small" disabled={r.jump == null} onClick={() => seek(r.jump)}>跳到</Button>
            </Space>
          ) },
        ]} />
        <Typography.Title level={5} style={{ marginTop: 16 }}>异议时间</Typography.Title>
        <Table size="small" pagination={false} rowKey="objection_id" dataSource={rec.sheet_objections.map((o, i) => ({ ...o, i }))} columns={[
          { title: "异议", dataIndex: "text", ellipsis: true },
          { title: "题单", dataIndex: "at_ms", width: 70, render: (v) => fmtMs(v) },
          { title: "相对主体段", width: 90, render: (_, o) => fmtMs(m.objections[o.i]) },
          { title: "视频时间", width: 80, render: (_, o) => (m.main == null ? "—" : fmtMs(m.main + m.objections[o.i])) },
          { title: "", width: 190, render: (_, o) => (
            <Space>
              <Button size="small" disabled={m.main == null} onClick={() => setM({ ...m, objections: m.objections.map((x, j) => (j === o.i ? now() - (m.main ?? 0) : x)) })}>设为当前时间</Button>
              <Button size="small" disabled={m.main == null} onClick={() => seek((m.main ?? 0) + m.objections[o.i])}>跳到</Button>
            </Space>
          ) },
        ]} />
        <Button type="primary" style={{ marginTop: 16 }} disabled={!ready} onClick={async () => {
          const r = await act(() => put<Rec>(`/recordings/${rec.id}/segments`, {
            main_start_ms: m.main, question_starts_ms: m.questions, reading_start_ms: m.reading, objection_offsets_ms: m.objections,
          }), "分段已保存");
          if (r) onSaved(r);
        }}>
          保存分段
        </Button>
      </Col>
    </Row>
  );
}

type LiveObj = { key: number; text: string; video_ms: number };
type LiveEx = { key: number; start_ms: number; end_ms: number | null };

/** 录播标注（C37，可选）：整段视频都评，不截取、不分段。不标也能直接提交，观众异议在处理时从逐字稿自动识别。
 *  想人工指定观众问题（出现时间和原文），或要排除不是主播本人在讲的时段（副播插话等，排除后不参与评分）时才需要标。 */
function LiveMarker({ rec, src, onSaved }: { rec: Rec; src: string; onSaved: (r: Rec) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const seq = useRef(0);
  const [objs, setObjs] = useState<LiveObj[]>(() => rec.objection_times.map((o) => ({
    key: seq.current++, video_ms: o.video_ms as number,
    text: (rec.sheet_objections.find((s) => s.objection_id === o.objection_id)?.text as string | undefined) ?? "",
  })));
  const [exs, setExs] = useState<LiveEx[]>(() => rec.exclusions.map((x) => ({ key: seq.current++, start_ms: x.start_ms as number, end_ms: x.end_ms as number })));
  const act = useAction();
  const now = () => Math.round((video.current?.currentTime ?? 0) * 1000);
  const seek = (ms: number | null) => ms != null && video.current && (video.current.currentTime = ms / 1000);
  const ready = objs.every((o) => o.text.trim()) && exs.every((x) => x.end_ms != null && x.end_ms > x.start_ms);
  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} md={12}>
        <video ref={video} src={src} controls style={{ width: "100%", background: "#000" }} data-testid="marker-video" />
        <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
          整段视频都参与评分，不截取 10 分钟，没有朗读段（“普通话标准”由评委听录像打分）。按次计的条目（口头禅、语速、小动作、加分项等）都按每 10 分钟的次数换算后计分。
        </Typography.Paragraph>
      </Col>
      <Col xs={24} md={12}>
        <Space style={{ marginBottom: 8 }}>
          <Typography.Title level={5} style={{ margin: 0 }}>观众异议（{objs.length} 条）</Typography.Title>
          <Button size="small" data-testid="live-add-objection" onClick={() => setObjs([...objs, { key: seq.current++, text: "", video_ms: now() }])}>在当前时间添加</Button>
        </Space>
        <Typography.Paragraph type="secondary">
          可以不标：系统会从逐字稿里自动识别主播念出或回应过的观众问题（主播没理会的弹幕识别不到）。想人工指定时，播放到观众提出问题的时刻点“添加”，填上问题原文；标了就以人工为准，不再自动识别。“解答异议”按实际条数折算；一条都没有时该条不适用，“节奏与气氛”由评委打分。
        </Typography.Paragraph>
        <Table size="small" pagination={false} rowKey="key" dataSource={objs} locale={{ emptyText: "没有人工标注，处理时自动识别" }} columns={[
          { title: "出现时间", dataIndex: "video_ms", width: 80, render: (v) => fmtMs(v) },
          { title: "问题原文", render: (_, o) => (
            <Input size="small" maxLength={500} value={o.text} placeholder="观众问了什么"
              onChange={(e) => setObjs(objs.map((x) => (x.key === o.key ? { ...x, text: e.target.value } : x)))} />
          ) },
          { title: "", width: 210, render: (_, o) => (
            <Space>
              <Button size="small" onClick={() => setObjs(objs.map((x) => (x.key === o.key ? { ...x, video_ms: now() } : x)))}>设为当前时间</Button>
              <Button size="small" onClick={() => seek(o.video_ms)}>跳到</Button>
              <Button size="small" danger onClick={() => setObjs(objs.filter((x) => x.key !== o.key))}>删</Button>
            </Space>
          ) },
        ]} />
        <Space style={{ margin: "16px 0 8px" }}>
          <Typography.Title level={5} style={{ margin: 0 }}>排除时段（{exs.length} 段）</Typography.Title>
          <Button size="small" data-testid="live-add-exclusion" onClick={() => setExs([...exs, { key: seq.current++, start_ms: now(), end_ms: null }])}>从当前时间开始</Button>
        </Space>
        <Typography.Paragraph type="secondary">副播、场控等其他人在讲话的时段。排除后这些话不算到主播头上，时长也不计入。</Typography.Paragraph>
        <Table size="small" pagination={false} rowKey="key" dataSource={exs} locale={{ emptyText: "没有排除时段" }} columns={[
          { title: "开始", dataIndex: "start_ms", width: 80, render: (v) => fmtMs(v) },
          { title: "结束", dataIndex: "end_ms", width: 80, render: (v) => fmtMs(v) },
          { title: "", render: (_, x) => (
            <Space>
              <Button size="small" onClick={() => setExs(exs.map((y) => (y.key === x.key ? { ...y, end_ms: now() } : y)))}>结束设为当前时间</Button>
              <Button size="small" onClick={() => seek(x.start_ms)}>跳到</Button>
              <Button size="small" danger onClick={() => setExs(exs.filter((y) => y.key !== x.key))}>删</Button>
            </Space>
          ) },
        ]} />
        <Button type="primary" style={{ marginTop: 16 }} disabled={!ready} data-testid="live-save" onClick={async () => {
          const r = await act(() => put<Rec>(`/recordings/${rec.id}/live-marks`, {
            objections: objs.map((o) => ({ text: o.text.trim(), video_ms: o.video_ms })),
            exclusions: exs.map((x) => ({ start_ms: x.start_ms, end_ms: x.end_ms })),
          }), "标注已保存");
          if (r) onSaved(r);
        }}>
          {objs.length || exs.length ? "保存标注" : "清空标注"}
        </Button>
      </Col>
    </Row>
  );
}

function Resume({ rec, onDone }: { rec: Rec; onDone: (r: Rec) => void }) {
  const [p, setP] = useState<[number, number] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const up = rec.upload!;
  return (
    <Card size="small" title="上传未完成" style={{ marginBottom: 16 }}>
      <Typography.Paragraph>已收到 {fmtBytes(up.received_bytes)} / {fmtBytes(up.total_size)}。重新选择同一个文件，会从断点继续上传。</Typography.Paragraph>
      <Upload showUploadList={false} accept=".mp4,.mov,.m4v,.webm,video/*" beforeUpload={(f) => {
        setErr(null);
        uploadFile(f, up, (a, b) => setP([a, b])).then(onDone).catch((e: Error) => setErr(e.message));
        return false;
      }}>
        <Button type="primary">选择文件继续上传</Button>
      </Upload>
      {p && <Progress percent={Math.floor((p[0] / p[1]) * 100)} />}
      {err && <Alert type="error" message={err} style={{ marginTop: 8 }} />}
    </Card>
  );
}

type Pending = {
  item_id: string; label: string; max: number; reasons: string[]; suggested: Record<string, number | null>;
  evidence: { start_ms: number | null; quote: string | null; label: string | null; judgment: unknown; reason: string | null }[];
};
type HumanReview = { status: string; items: Pending[]; scores: Record<string, { score: number; by?: string; note?: string }> };

/** 评委打分（T39）：机器评不了或须人工确认的条目。机器建议分只作参考，可以改。可分几次录入。 */
function HumanScoring({ id, onDone, seek }: { id: string; onDone: () => void; seek: (ms: number) => void }) {
  const { data, reload } = useFetch<HumanReview>(`/recordings/${id}/human-review`);
  const [vals, setVals] = useState<Record<string, { score: number | null; note: string }>>({});
  const act = useAction();
  useEffect(() => {
    if (!data) return;
    const init: Record<string, { score: number | null; note: string }> = {};
    for (const it of data.items) {
      const sug = Object.values(it.suggested).find((v) => v != null) ?? null;
      init[it.item_id] = { score: data.scores[it.item_id]?.score ?? sug, note: data.scores[it.item_id]?.note ?? "" };
    }
    setVals(init);
  }, [data]);
  if (!data || data.items.length === 0) return null;
  const filled = Object.entries(vals).filter(([, v]) => v.score != null);
  const submit = async () => {
    const scores = Object.fromEntries(filled.map(([k, v]) => [k, { score: v.score, note: v.note || null }]));
    const r = await act(() => put<HumanReview>(`/recordings/${id}/human-scores`, { scores }), "已保存");
    if (r) { reload(); if (r.status !== "awaiting_human") onDone(); }
  };
  return (
    <Card title="评委打分" size="small" style={{ marginBottom: 16 }} data-testid="human-scoring"
      extra={<Button type="primary" disabled={filled.length === 0} onClick={submit}>保存（{filled.length}/{data.items.length}）</Button>}>
      <Typography.Paragraph type="secondary">
        以下条目机器评不了，或在校准达标前须由评委确认。请看视频后按评分表打分；有机器建议分的已预填，可以修改。全部填完后自动出报告。
      </Typography.Paragraph>
      <div className="human-review-list">
        {data.items.map((r) => <section className="human-review-item" key={r.item_id}>
          <div className="human-review-score">
            <label htmlFor={`human-${r.item_id}`}>{r.label}</label>
            <div className="score-input">
              <InputNumber id={`human-${r.item_id}`} aria-label={`${r.label}评委打分`} min={0} max={r.max} step={0.5} value={vals[r.item_id]?.score ?? null} data-testid={`human-${r.item_id}`}
                onChange={(v) => setVals({ ...vals, [r.item_id]: { ...vals[r.item_id], score: v } })} />
              <span>/ {r.max}</span>
            </div>
          </div>
          <div className="human-review-suggestion">机器建议：{Object.values(r.suggested).filter((v) => v != null).join(" / ") || "无，需人工评分"}</div>
          <details>
            <summary>评分依据与备注{r.evidence.length ? ` · ${r.evidence.length} 条证据` : ""}{vals[r.item_id]?.note ? " · 已填备注" : ""}</summary>
            <Typography.Paragraph type="secondary">{r.reasons.join("；")}</Typography.Paragraph>
            {r.evidence.length > 0 && <ul>{r.evidence.map((e, i) => <li key={i}>
              {e.start_ms != null && <Button type="link" size="small" onClick={() => seek(e.start_ms!)} aria-label={`播放证据 ${fmtMs(e.start_ms)}`}>{fmtMs(e.start_ms)}</Button>}
              {e.quote ?? e.label} {e.reason ? `—— ${e.reason}` : ""}
            </li>)}</ul>}
            <Input.TextArea aria-label={`${r.label}备注`} autoSize={{ minRows: 1, maxRows: 4 }} maxLength={500} placeholder="填写评分备注（可选）" value={vals[r.item_id]?.note ?? ""}
              onChange={(e) => setVals({ ...vals, [r.item_id]: { ...vals[r.item_id], note: e.target.value } })} />
          </details>
        </section>)}
      </div>
    </Card>
  );
}

const STAGE_ZH: Record<string, string> = { asr: "语音转写", acoustic: "声音特征分析", detectors: "模型检测与证据提取", scoring: "计算得分", human: "等待人工评分", done: "本轮完成" };
const RUN_ZH: Record<string, string> = { queued: "排队中", running: "进行中", awaiting_human: "等待人工评分", completed: "已完成", failed: "本次尝试失败" };
const MODEL_ZH: Record<string, string> = { asr: "转写", llm: "文本", vision: "视觉", voice: "声音", speech_eval: "普通话", laugh: "笑声" };

function ScoringProgress({ rec, reload, error }: { rec: Rec; reload: () => void; error: string | null }) {
  const active = ["submitted", "processing"].includes(rec.status);
  const runs = rec.scoring_runs ?? [];
  if (!active && !runs.length) return null;
  return <Card size="small" title="自动评分进度" style={{ marginBottom: 16 }} extra={<Button size="small" onClick={reload}>刷新进度</Button>} data-testid="scoring-progress">
    {error && <Alert type="warning" showIcon message="进度更新失败，正在显示上次状态" description={error} style={{ marginBottom: 12 }} />}
    {active && <Typography.Paragraph type="secondary">每 3 秒更新。显示实际完成的检测项，不代表剩余时间；临界结果才会追加第 2、3 轮复评。</Typography.Paragraph>}
    {!runs.length && <Alert type="info" showIcon message={rec.status === "submitted" ? "已提交，等待工作进程接收" : "正在准备音频和视频帧，尚未开始评分轮次"} />}
    {runs.map(run => {
      const settled = run.detectors_completed + run.detectors_failed;
      const total = run.detectors_total;
      return <div key={run.round_no} style={{ padding: "12px 0", borderTop: "1px solid #f0f0f0" }}>
        <Space wrap><Typography.Text strong>第 {run.round_no} 轮{run.round_no > 1 ? "复评" : "评分"}</Typography.Text>
          <Tag color={run.status === "failed" ? "error" : run.status === "completed" ? "success" : "processing"}>{RUN_ZH[run.status] ?? run.status}</Tag>
          <Typography.Text>{run.status === "queued" ? "等待执行" : STAGE_ZH[run.stage ?? ""] ?? "准备中"}</Typography.Text>
          {run.retry_count > 0 && <Typography.Text type="warning">已重试 {run.retry_count} 次</Typography.Text>}
        </Space>
        {total != null && <div style={{ maxWidth: 600, marginTop: 8 }}>
          <Progress percent={total ? Math.round(settled / total * 100) : 100} status={run.detectors_failed ? "exception" : settled < total ? "active" : "success"} format={() => `${settled}/${total} 项已返回`} />
          <Typography.Text type="secondary">成功 {run.detectors_completed} 项{run.detectors_failed > 0 ? `，失败 ${run.detectors_failed} 项` : ""}；检测完成后还需计算得分及汇总报告。</Typography.Text>
        </div>}
        <div style={{ marginTop: 8 }}>{Object.entries(run.models).map(([role, model]) => <Tag key={role}>{MODEL_ZH[role] ?? role}：{model}{run.model_tasks[role] && ` · ${run.model_tasks[role].completed + run.model_tasks[role].failed}/${run.model_tasks[role].total} 项已返回${run.model_tasks[role].failed ? `，失败 ${run.model_tasks[role].failed} 项` : ""}`}</Tag>)}</div>
      </div>;
    })}
    {active && runs.length > 0 && runs.every(r => r.status === "completed") && <Alert type="info" message="评分轮次已完成，正在汇总报告与辅导建议" />}
  </Card>;
}

export default function RecordingDetail() {
  const { id } = useParams();
  const { data, reload, error } = useFetch<Rec>(`/recordings/${id}`);
  const nav = useNavigate();
  const [rec, setRec] = useState<Rec | undefined>();
  const { can } = useAuth();
  const act = useAction();
  const reviewVideo = useRef<HTMLVideoElement>(null);
  const seekEvidence = (ms: number) => {
    if (!reviewVideo.current) return;
    reviewVideo.current.currentTime = ms / 1000;
    void reviewVideo.current.play().catch(() => undefined);
  };
  useEffect(() => setRec(data), [data]);
  useEffect(() => {  // 处理中每 3 秒自动刷新一次状态
    if (!rec || !["submitted", "processing"].includes(rec.status)) return;
    const t = setInterval(reload, 3000);
    return () => clearInterval(t);
  }, [rec?.status, reload]);
  if (!rec) return null;
  const src = localUrlOf(rec.id) ?? (rec.video_asset_id ? `/api/media/${rec.video_asset_id}` : null);
  const editable = can("recording.upload");
  const live = rec.mode === "live";
  return (
    <>
      <Space style={{ marginBottom: 16 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>{rec.candidate_name} · {rec.sheet_code}</Typography.Title>
        <Tag color={REC_STATUS[rec.status]?.[1]}>{REC_STATUS[rec.status]?.[0]}</Tag>
        {editable && rec.status === "uploaded" && rec.segments.length > 0 && (
          <Popconfirm title={live ? "提交后标注不能再改，确定提交处理？" : "提交后分段不能再改，确定提交处理？"} onConfirm={async () => { setRec({ ...rec, status: "submitted", scoring_runs: [] }); const r = await act(() => post<Rec>(`/recordings/${id}/submit`), "已提交"); if (r) setRec(r); reload(); }}>
            <Button type="primary">提交处理</Button>
          </Popconfirm>
        )}
        {editable && ["uploading", "uploaded"].includes(rec.status) && (
          <Popconfirm title={live ? "取消会删除已上传的视频。确定？" : "取消会删除已上传的视频，题单恢复为未使用。确定？"} onConfirm={async () => { const r = await act(() => post<Rec>(`/recordings/${id}/cancel`), "已取消"); if (r) setRec(r); }}>
            <Button danger>取消</Button>
          </Popconfirm>
        )}
      </Space>
      {rec.status === "failed" && (
        <Alert type="error" showIcon style={{ marginBottom: 16 }} message="处理失败，已告警管理员。多半是模型或系统问题，排查后可重新处理；确认是录像本身的问题再联系候选人重录" description={rec.failure_reason}
          action={editable && <Button onClick={async () => { setRec({ ...rec, status: "submitted", scoring_runs: [] }); const r = await act(() => post<Rec>(`/recordings/${id}/reprocess`), "已重新处理"); if (r) setRec(r); reload(); }}>重新处理</Button>} />
      )}
      <ScoringProgress rec={rec} reload={reload} error={error} />
      {rec.status === "awaiting_human" && <Alert type="warning" showIcon style={{ marginBottom: 16 }} message="机器部分已完成，等评委给下面的条目打分" />}

      {rec.status === "done" && (
        <Alert type="success" showIcon style={{ marginBottom: 16 }} message="评分已完成"
          action={rec.report_id && <Button type="primary" onClick={() => nav(`/reports/${rec.report_id}`)}>查看报告</Button>} />
      )}
      {rec.uses_draft_config && <Alert type="warning" showIcon style={{ marginBottom: 16 }} message="使用了草稿评分标准或红线词表，出的报告将标注“非正式”。" />}
      {rec.warnings.map((w) => <Alert key={w} type="info" showIcon style={{ marginBottom: 8 }} message={w} />)}
      <details className="recording-meta">
        <summary>录像信息 · {rec.product_name} · {MODE_ZH[rec.mode] ?? rec.mode}
          <span>视频 {fmtMs(rec.video_duration_ms)}</span>
          <span>{live ? "参与评分" : "主体段"} <span>{rec.main_duration_ms == null ? "未标注" : fmtMs(rec.main_duration_ms)}</span></span>
        </summary>
        <Descriptions size="small" bordered column={{ xs: 1, sm: 2, lg: 3 }} style={{ marginBottom: 16 }}>
        <Descriptions.Item label="类型">{MODE_ZH[rec.mode] ?? rec.mode}{live ? "（无题单，整段视频评分）" : ""}</Descriptions.Item>
        <Descriptions.Item label="产品">{rec.product_name}</Descriptions.Item>
        <Descriptions.Item label="适用达标线">{AUDIENCE_ZH[rec.audience] ?? rec.audience}</Descriptions.Item>
        <Descriptions.Item label="道具">{rec.props_available ? "有（计“肢体语言（贴片/KT板）”）" : "无（“肢体语言（贴片/KT板）”不适用）"}</Descriptions.Item>
        <Descriptions.Item label="视频时长">{fmtMs(rec.video_duration_ms)}</Descriptions.Item>
        <Descriptions.Item label={live ? "参与评分时长" : "主体段时长"}>{fmtMs(rec.main_duration_ms)}</Descriptions.Item>
        <Descriptions.Item label="提交时间">{rec.submitted_at ? dayjs(rec.submitted_at).format("YYYY-MM-DD HH:mm:ss") : "—"}</Descriptions.Item>
        <Descriptions.Item label="出结果时间">{rec.finished_at ? dayjs(rec.finished_at).format("YYYY-MM-DD HH:mm:ss") : "—"}</Descriptions.Item>
      </Descriptions>
      </details>
      {rec.status === "awaiting_human" && can("human.score") && (
        <div className="review-workspace">
          <aside className="review-player">
            {src ? <video ref={reviewVideo} src={src} controls preload="metadata" data-testid="human-review-video" /> : <Alert type="info" message="没有可播放的视频" />}
            <Typography.Paragraph type="secondary">展开评分条目的证据，点击时间即可定位视频。</Typography.Paragraph>
          </aside>
          <section className="review-scores"><HumanScoring id={rec.id} onDone={reload} seek={seekEvidence} /></section>
        </div>
      )}
      {rec.status === "uploading" && rec.upload && editable && <Resume rec={rec} onDone={(r) => (setRec(r), reload())} />}
      {rec.status === "uploaded" && live && editable && rec.segments.length > 0 && (
        <Alert type="success" showIcon style={{ marginBottom: 16 }} message="视频已上传，可以直接点上方“提交处理”" description="下面的标注是可选的：只在想人工指定观众问题，或要排除副播等其他人讲话的时段时才需要。" />
      )}
      {rec.status === "uploaded" && src && editable && (live ? <LiveMarker rec={rec} src={src} onSaved={setRec} /> : <Marker rec={rec} src={src} onSaved={setRec} />)}
      {["submitted", "processing", "awaiting_human", "done", "failed"].includes(rec.status) && !(rec.status === "awaiting_human" && can("human.score")) && src && (
        <Row gutter={[16, 16]}>
          <Col xs={24} md={12}><video src={src} controls style={{ width: "100%", background: "#000" }} /></Col>
          <Col xs={24} md={12}>
            <Table size="small" pagination={false} rowKey="segment" dataSource={rec.segments} columns={[
              { title: "分段", dataIndex: "segment" },
              { title: "开始", dataIndex: "start_ms", render: fmtMs },
              { title: "结束", dataIndex: "end_ms", render: fmtMs },
            ]} />
            {live && (
              <Typography.Paragraph style={{ marginTop: 12 }}>
                观众异议 {rec.objection_times.length} 条{rec.objection_times.some((o) => o.source === "auto") ? "（从逐字稿自动识别）" : ""}{rec.objection_times.length ? "：" : "；"}
                {rec.objection_times.map((o) => (
                  <span key={o.objection_id as string} style={{ display: "block" }}>
                    {fmtMs(o.video_ms as number)} {(rec.sheet_objections.find((s) => s.objection_id === o.objection_id)?.text as string | undefined) ?? ""}
                  </span>
                ))}
                排除时段 {rec.exclusions.length} 段{rec.exclusions.length ? `：${rec.exclusions.map((x) => `${fmtMs(x.start_ms as number)}–${fmtMs(x.end_ms as number)}`).join("、")}` : ""}。
              </Typography.Paragraph>
            )}
          </Col>
        </Row>
      )}
    </>
  );
}
