import { Alert, Button, Card, Form, Progress, Radio, Select, Space, Typography, Upload } from "antd";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { post, type S } from "../api/client";
import { AUDIENCE_ZH, useAction, useFetch } from "../components/hooks";
import { rememberLocal } from "../components/localMedia";
import { fmtBytes, uploadFile } from "../components/upload";
import { ConsentForm, NewCandidateModal, registerConsent } from "./Candidates";

type Rec = S<"RecordingOut">;

/** 上传录像：选候选人和书面同意 → 选题单 → 选达标线和有无道具 → 选文件分片上传 → 进入分段标注。 */
export default function NewRecording() {
  const nav = useNavigate();
  const act = useAction();
  const [form] = Form.useForm();
  const [consentForm] = Form.useForm();
  const candidates = useFetch<S<"CandidateRow">[]>("/candidates");
  const sheets = useFetch<S<"SheetOut">[]>("/sheets?status=issued");
  const rubric = useFetch<S<"RubricDetail">>("/rubrics/reference");
  const candidateId = Form.useWatch("candidate_id", form) as string | undefined;
  const detail = useFetch<S<"CandidateDetail">>(candidateId ? `/candidates/${candidateId}` : null);
  const [newCand, setNewCand] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<[number, number] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const consents = candidateId ? (detail.data?.consents ?? []) : [];

  const start = async () => {
    const v = await form.validateFields();
    if (!file) return setError("请选择视频文件");
    setBusy(true);
    setError(null);
    try {
      const rec = await act(() =>
        post<Rec>("/recordings", { ...v, filename: file.name, content_type: file.type || "video/mp4", size_bytes: file.size }),
      );
      if (!rec?.upload) return;
      const done = await uploadFile(file, rec.upload, (a, b) => setProgress([a, b]));
      rememberLocal(done.id, file);
      nav(`/recordings/${done.id}`);
    } catch (e) {
      setError(`${(e as Error).message}。可以在“试镜录像”里打开这条记录，重新选择同一文件继续上传。`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Typography.Title level={4}>上传录像</Typography.Title>
      <Card style={{ maxWidth: 760 }}>
        <Form form={form} layout="vertical" disabled={busy}>
          <Form.Item label="候选人" required>
            <Space.Compact style={{ width: "100%" }}>
              <Form.Item name="candidate_id" noStyle rules={[{ required: true, message: "请选择候选人" }]}>
                <Select showSearch optionFilterProp="label" placeholder="选择候选人" style={{ width: "100%" }}
                  options={(candidates.data ?? []).map((c) => ({ value: c.id, label: `${c.name}${c.phone_masked ? `（${c.phone_masked}）` : ""}` }))}
                  onChange={() => form.setFieldValue("consent_record_id", undefined)} />
              </Form.Item>
              <Button onClick={() => setNewCand(true)}>新建</Button>
            </Space.Compact>
          </Form.Item>
          {candidateId && detail.data && consents.length === 0 && (
            <Card size="small" title="该候选人还没有登记书面同意，未登记不能上传" style={{ marginBottom: 16, borderColor: "#faad14" }}>
              <ConsentForm form={consentForm} />
              <Button onClick={async () => {
                const v = await consentForm.validateFields();
                const c = await act(() => registerConsent(candidateId, v), "已登记");
                if (c) {
                  detail.reload();
                  form.setFieldValue("consent_record_id", c.id);
                }
              }}>
                登记
              </Button>
            </Card>
          )}
          <Form.Item name="consent_record_id" label="书面同意" rules={[{ required: true, message: "请选择已登记的书面同意" }]}>
            <Select placeholder={candidateId ? "选择本次使用的同意书登记" : "先选择候选人"}
              options={consents.map((c) => ({ value: c.id, label: `${c.consent_text_version}，签署于 ${c.signed_on}` }))} />
          </Form.Item>
          <Form.Item name="sheet_id" label="试镜题单" rules={[{ required: true, message: "请选择题单" }]} extra="候选人按哪张题单录制，就选哪张；一张题单只能用一次。">
            <Select showSearch optionFilterProp="label" placeholder="选择未使用的题单"
              options={(sheets.data ?? []).map((s) => ({ value: s.id, label: `${s.code} · ${s.product_name}${s.note ? ` · ${s.note}` : ""}` }))} />
          </Form.Item>
          <Form.Item name="audience" label="适用达标线" rules={[{ required: true, message: "请选择适用达标线" }]}>
            <Radio.Group>
              {Object.entries(rubric.data?.thresholds ?? {}).map(([k, v]) => (
                <Radio.Button key={k} value={k}>{AUDIENCE_ZH[k] ?? k}（总档位 &lt; {v}）</Radio.Button>
              ))}
            </Radio.Group>
          </Form.Item>
          <Form.Item name="props_available" label="画面里有没有贴片或 KT 板" rules={[{ required: true, message: "请选择" }]}
            extra="有：计 P9 道具使用，人设塑造满分 95；没有：P9 不适用，满分 90。">
            <Radio.Group>
              <Radio.Button value={true}>有</Radio.Button>
              <Radio.Button value={false}>没有</Radio.Button>
            </Radio.Group>
          </Form.Item>
          <Form.Item label="视频文件" required extra="主体段、知识问答、朗读连续录在一个文件里；MP4 / MOV / M4V / WEBM。">
            <Upload beforeUpload={(f) => (setFile(f), false)} maxCount={1} accept=".mp4,.mov,.m4v,.webm,video/*" onRemove={() => setFile(null)}>
              <Button>选择文件</Button>
            </Upload>
            {file && <Typography.Text type="secondary">{fmtBytes(file.size)}</Typography.Text>}
          </Form.Item>
        </Form>
        {error && <Alert type="error" message={error} style={{ marginBottom: 16 }} />}
        {progress && <Progress percent={Math.floor((progress[0] / progress[1]) * 100)} format={() => `${fmtBytes(progress[0])} / ${fmtBytes(progress[1])}`} />}
        <Button type="primary" loading={busy} onClick={start} style={{ marginTop: 8 }}>
          开始上传
        </Button>
      </Card>
      <NewCandidateModal open={newCand} onClose={() => setNewCand(false)} onCreated={(c) => {
        setNewCand(false);
        candidates.reload();
        form.setFieldValue("candidate_id", c.id);
      }} />
    </>
  );
}
