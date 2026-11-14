import { Alert, Button, Card, Form, Progress, Radio, Select, Space, Typography, Upload } from "antd";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { post, type S } from "../api/client";
import { useAuth } from "../auth";
import { AUDIENCE_ZH, useAction, useFetch } from "../components/hooks";
import { rememberLocal } from "../components/localMedia";
import NewProductModal from "../components/NewProductModal";
import { PageHeader } from "../components/ui";
import { fmtBytes, uploadFile } from "../components/upload";
import { ConsentForm, NewCandidateModal, SHOW_CONSENT_UI, ensureConsent, registerConsent } from "./Candidates";

type Rec = S<"RecordingOut">;

/** 上传录像：选候选人（书面同意 UI 暂隐，后台自动补登记）→ 试镜选题单 / 录播选产品 → 选达标线和有无道具 → 选文件分片上传 → 进入标注。
 *  录播（老主播、上播 1 个月的主播）没有题单，整段视频评分。 */
export default function NewRecording() {
  const nav = useNavigate();
  const { can } = useAuth();
  const act = useAction();
  const [form] = Form.useForm();
  const [consentForm] = Form.useForm();
  const candidates = useFetch<S<"CandidateRow">[]>("/candidates");
  const sheets = useFetch<S<"SheetOut">[]>("/sheets?status=issued");
  const rubric = useFetch<S<"RubricDetail">>("/rubrics/reference?for_processing=true");
  const products = useFetch<S<"ProductOut">[]>("/products");
  const mode = (Form.useWatch("mode", form) as string | undefined) ?? "audition";
  const candidateId = Form.useWatch("candidate_id", form) as string | undefined;
  const productId = Form.useWatch("product_id", form) as string | undefined;
  const detail = useFetch<S<"CandidateDetail">>(candidateId ? `/candidates/${candidateId}` : null);
  const [newCand, setNewCand] = useState(false);
  const [newProduct, setNewProduct] = useState(false);
  const [createdProduct, setCreatedProduct] = useState<S<"ProductOut"> | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<[number, number] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const consents = candidateId ? (detail.data?.consents ?? []) : [];
  const productOptions = [...(products.data ?? [])];
  if (createdProduct && !productOptions.some((p) => p.id === createdProduct.id)) productOptions.push(createdProduct);
  const selectedProduct = productOptions.find((p) => p.id === productId);
  const productReady = !!selectedProduct?.published_card_version && !products.loading && !products.error;

  useEffect(() => {
    if (mode !== "live") return;
    window.addEventListener("focus", products.reload);
    return () => window.removeEventListener("focus", products.reload);
  }, [mode, products.reload]);

  const start = async () => {
    const v = await form.validateFields();
    if (v.mode === "live" && !productReady) return setError("请先发布该产品的资料版本，再上传录播");
    if (!file) return setError("请选择视频文件");
    setBusy(true);
    setError(null);
    try {
      let consentId = v.consent_record_id as string | undefined;
      if (!consentId) {
        if (!candidateId) throw new Error("请选择候选人");
        const c = await ensureConsent(candidateId, consents);
        consentId = c.id;
        form.setFieldValue("consent_record_id", consentId);
        detail.reload();
      }
      const rec = await act(() =>
        post<Rec>("/recordings", {
          ...v,
          ...(v.mode === "live" && rubric.data ? { rubric_version_id: rubric.data.id } : {}),
          consent_record_id: consentId,
          filename: file.name,
          content_type: file.type || "video/mp4",
          size_bytes: file.size,
        }),
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
      <PageHeader
        back={{ to: "/recordings", label: "试镜录像" }}
        title="上传录像"
        description="试镜按题单录制，上传后标出分段；直播录播没有题单，整段视频评分，上传完可以直接提交。"
      />
      <Card style={{ maxWidth: 760 }}>
        {rubric.error && <Alert type="error" message={rubric.error} style={{ marginBottom: 16 }} />}
        <Form form={form} layout="vertical" disabled={busy} initialValues={{ mode: "audition" }}>
          <Form.Item name="mode" label="录像类型" rules={[{ required: true }]}
            extra={mode === "live"
              ? "直播录播：没有题单，整段视频评分。上传完可以直接提交，观众问题从逐字稿自动识别；有副播等其他人讲话的时段可以在提交前排除。"
              : "按题单录制的试镜：上传后标出主体段、朗读段的起点和异议时间。"}>
            <Radio.Group onChange={() => form.setFieldsValue({ sheet_id: undefined, product_id: undefined })}>
              <Radio.Button value="audition">试镜（按题单录制）</Radio.Button>
              <Radio.Button value="live">录播（老主播、上播 1 个月，无题单）</Radio.Button>
            </Radio.Group>
          </Form.Item>
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
          {SHOW_CONSENT_UI && candidateId && detail.data && consents.length === 0 && (
            <Card size="small" title="该候选人还没有登记书面同意，未登记不能上传" style={{ marginBottom: 16, borderColor: "var(--warn)" }}>
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
          {SHOW_CONSENT_UI && (
            <Form.Item name="consent_record_id" label="书面同意" rules={[{ required: true, message: "请选择已登记的书面同意" }]}>
              <Select placeholder={candidateId ? "选择本次使用的同意书登记" : "先选择候选人"}
                options={consents.map((c) => ({ value: c.id, label: `${c.consent_text_version}，签署于 ${c.signed_on}` }))} />
            </Form.Item>
          )}
          {mode === "audition" ? (
            <Form.Item name="sheet_id" label="试镜题单" rules={[{ required: true, message: "请选择题单" }]} extra="候选人按哪张题单录制，就选哪张；一张题单只能用一次。">
              <Select showSearch optionFilterProp="label" placeholder="选择未使用的题单"
                options={(sheets.data ?? []).map((s) => ({ value: s.id, label: `${s.code} · ${s.product_name}${s.note ? ` · ${s.note}` : ""}` }))} />
            </Form.Item>
          ) : (
            <Form.Item label="直播讲的产品" htmlFor="product_id" required
              extra="一条录播按一个产品评分，产品须有已启用的资料版本。缺少参考脚本或校准记录时，“产品讲解”由评委打分。">
              <Space.Compact style={{ width: "100%" }}>
                <Form.Item name="product_id" noStyle rules={[{ required: true, message: "请选择产品" }]}>
                  <Select showSearch optionFilterProp="label" placeholder="选择产品" style={{ width: "100%" }} loading={products.loading}
                    options={productOptions.map((p) => ({ value: p.id, label: p.name }))} />
                </Form.Item>
                {can("config.write") && <Button onClick={() => setNewProduct(true)}>新建产品</Button>}
              </Space.Compact>
            </Form.Item>
          )}
          {mode === "live" && products.error && <Alert type="error" message={products.error} style={{ marginBottom: 16 }} />}
          {mode === "live" && selectedProduct && !selectedProduct.published_card_version && (
            <Alert type="warning" style={{ marginBottom: 16 }} message="该产品尚未启用资料版本，请先添加参考脚本并发布后再上传。"
              description={<Space wrap>
                {can("config.write")
                  ? <Typography.Link href={`/products/${selectedProduct.id}`} target="_blank" rel="noopener noreferrer">完善产品资料</Typography.Link>
                  : <Typography.Text>请联系管理员补充并发布产品资料。</Typography.Text>}
                <Button size="small" onClick={products.reload} loading={products.loading}>刷新产品列表</Button>
              </Space>} />
          )}
          {mode === "live" && rubric.data && (
            <Typography.Paragraph type="secondary">
              评分标准：{rubric.data.version}{rubric.data.status === "draft" ? "（草稿，报告标注“非正式”）" : ""}
            </Typography.Paragraph>
          )}
          <Form.Item name="audience" label="适用达标线" rules={[{ required: true, message: "请选择适用达标线" }]}>
            <Radio.Group>
              {Object.entries(rubric.data?.thresholds ?? {}).map(([k, v]) => (
                <Radio.Button key={k} value={k}>{AUDIENCE_ZH[k] ?? k}（总档位 &lt; {v}）</Radio.Button>
              ))}
            </Radio.Group>
          </Form.Item>
          <Form.Item name="props_available" label="画面里有没有贴片或 KT 板" rules={[{ required: true, message: "请选择" }]}
            extra="有：计“人设塑造·肢体语言（贴片/KT板）”，人设塑造满分 100；没有：该条不适用，人设塑造按 95 分折算。">
            <Radio.Group>
              <Radio.Button value={true}>有</Radio.Button>
              <Radio.Button value={false}>没有</Radio.Button>
            </Radio.Group>
          </Form.Item>
          <Form.Item label="视频文件" required extra={mode === "live" ? "一段完整的直播录播；MP4 / MOV / M4V / WEBM。" : "主体段、朗读连续录在一个文件里；MP4 / MOV / M4V / WEBM。"}>
            <Upload beforeUpload={(f) => (setFile(f), false)} maxCount={1} accept=".mp4,.mov,.m4v,.webm,video/*" onRemove={() => setFile(null)}>
              <Button>选择文件</Button>
            </Upload>
            {file && <Typography.Text type="secondary">{fmtBytes(file.size)}</Typography.Text>}
          </Form.Item>
        </Form>
        {error && <Alert type="error" message={error} style={{ marginBottom: 16 }} />}
        {progress && <Progress percent={Math.floor((progress[0] / progress[1]) * 100)} format={() => `${fmtBytes(progress[0])} / ${fmtBytes(progress[1])}`} />}
        <Button type="primary" size="large" loading={busy} disabled={!rubric.data || !!rubric.error || (mode === "live" && !productReady)} onClick={start} style={{ marginTop: 8 }}>
          开始上传
        </Button>
      </Card>
      <NewCandidateModal open={newCand} onClose={() => setNewCand(false)} onCreated={(c) => {
        setNewCand(false);
        candidates.reload();
        form.setFieldValue("candidate_id", c.id);
      }} />
      {can("config.write") && <NewProductModal open={newProduct} onClose={() => setNewProduct(false)} onCreated={(p) => {
        setNewProduct(false);
        setCreatedProduct(p);
        products.reload();
        form.setFieldValue("product_id", p.id);
      }} />}
    </>
  );
}
