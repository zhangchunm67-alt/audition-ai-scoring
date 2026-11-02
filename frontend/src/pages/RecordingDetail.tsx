import { Alert, Button, Card, Col, Descriptions, Popconfirm, Progress, Row, Space, Table, Tag, Typography, Upload } from "antd";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { post, put, type S } from "../api/client";
import { useAuth } from "../auth";
import { AUDIENCE_ZH, useAction, useFetch } from "../components/hooks";
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
    <Row gutter={24}>
      <Col span={12}>
        <video ref={video} src={src} controls style={{ width: "100%", background: "#000" }} data-testid="marker-video" />
        <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>播放到某段开头时点“设为当前时间”。异议时间默认按题单（相对主体段开始），如候选人实际回应时间不同，可在视频里定位后修正。</Typography.Paragraph>
      </Col>
      <Col span={12}>
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

export default function RecordingDetail() {
  const { id } = useParams();
  const { data, reload } = useFetch<Rec>(`/recordings/${id}`);
  const [rec, setRec] = useState<Rec | undefined>();
  const { can } = useAuth();
  const act = useAction();
  useEffect(() => setRec(data), [data]);
  if (!rec) return null;
  const src = localUrlOf(rec.id) ?? (rec.video_asset_id ? `/api/media/${rec.video_asset_id}` : null);
  const editable = can("recording.upload");
  return (
    <>
      <Space style={{ marginBottom: 16 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>{rec.candidate_name} · {rec.sheet_code}</Typography.Title>
        <Tag color={REC_STATUS[rec.status]?.[1]}>{REC_STATUS[rec.status]?.[0]}</Tag>
        {editable && rec.status === "uploaded" && rec.segments.length > 0 && (
          <Popconfirm title="提交后分段不能再改，确定提交处理？" onConfirm={async () => { const r = await act(() => post<Rec>(`/recordings/${id}/submit`), "已提交"); if (r) setRec(r); }}>
            <Button type="primary">提交处理</Button>
          </Popconfirm>
        )}
        {editable && ["uploading", "uploaded"].includes(rec.status) && (
          <Popconfirm title="取消会删除已上传的视频，题单恢复为未使用。确定？" onConfirm={async () => { const r = await act(() => post<Rec>(`/recordings/${id}/cancel`), "已取消"); if (r) setRec(r); }}>
            <Button danger>取消</Button>
          </Popconfirm>
        )}
      </Space>
      {rec.uses_draft_config && <Alert type="warning" showIcon style={{ marginBottom: 16 }} message="题单使用了草稿评分标准或红线词表，出的报告将标注“非正式”。" />}
      {rec.warnings.map((w) => <Alert key={w} type="info" showIcon style={{ marginBottom: 8 }} message={w} />)}
      <Descriptions size="small" bordered column={3} style={{ marginBottom: 16 }}>
        <Descriptions.Item label="产品">{rec.product_name}</Descriptions.Item>
        <Descriptions.Item label="适用达标线">{AUDIENCE_ZH[rec.audience] ?? rec.audience}</Descriptions.Item>
        <Descriptions.Item label="道具">{rec.props_available ? "有（计 P9）" : "无（P9 不适用）"}</Descriptions.Item>
        <Descriptions.Item label="视频时长">{fmtMs(rec.video_duration_ms)}</Descriptions.Item>
        <Descriptions.Item label="主体段时长">{fmtMs(rec.main_duration_ms)}</Descriptions.Item>
        <Descriptions.Item label="提交时间">{rec.submitted_at ?? "—"}</Descriptions.Item>
      </Descriptions>
      {rec.status === "uploading" && rec.upload && editable && <Resume rec={rec} onDone={(r) => (setRec(r), reload())} />}
      {rec.status === "uploaded" && src && editable && <Marker rec={rec} src={src} onSaved={setRec} />}
      {["submitted", "processing", "done", "failed"].includes(rec.status) && src && (
        <Row gutter={24}>
          <Col span={12}><video src={src} controls style={{ width: "100%", background: "#000" }} /></Col>
          <Col span={12}>
            <Table size="small" pagination={false} rowKey="segment" dataSource={rec.segments} columns={[
              { title: "分段", dataIndex: "segment" },
              { title: "开始", dataIndex: "start_ms", render: fmtMs },
              { title: "结束", dataIndex: "end_ms", render: fmtMs },
            ]} />
          </Col>
        </Row>
      )}
    </>
  );
}
