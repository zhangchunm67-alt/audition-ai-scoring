import { Alert, Button, Descriptions, List, Popconfirm, Space, Tag, Typography } from "antd";
import { useParams } from "react-router-dom";
import { post, type S } from "../api/client";
import { useAuth } from "../auth";
import { msToClock, STATUS_ZH, useAction, useFetch } from "../components/hooks";

export default function SheetDetail() {
  const { id } = useParams();
  const { data: s, reload } = useFetch<S<"SheetOut">>(`/sheets/${id}`);
  const { can } = useAuth();
  const act = useAction();
  if (!s) return null;
  return (
    <>
      <Space style={{ marginBottom: 16 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          题单 {s.code}
        </Typography.Title>
        <Tag>{STATUS_ZH[s.status]}</Tag>
        {can("sheet.write") && s.status === "issued" && (
          <Popconfirm title="作废后不能再用于上传，确定？" onConfirm={async () => (await act(() => post(`/sheets/${id}/void`), "已作废")) && reload()}>
            <Button danger>作废</Button>
          </Popconfirm>
        )}
      </Space>
      {s.uses_draft_config && <Alert type="warning" showIcon style={{ marginBottom: 16 }} message="本题单使用的评分标准或红线词表是草稿，据此出的报告会标注“非正式”。" />}
      <Descriptions bordered size="small" column={2} style={{ marginBottom: 24 }}>
        <Descriptions.Item label="产品">{s.product_name}</Descriptions.Item>
        <Descriptions.Item label="卖点卡">第 {s.product_card_version} 版</Descriptions.Item>
        <Descriptions.Item label="评分标准">{s.rubric_version}</Descriptions.Item>
        <Descriptions.Item label="红线词表">{s.redline_lexicon_version}</Descriptions.Item>
        <Descriptions.Item label="准备时间">{Math.round((s.draw_rule.prep_seconds as number) / 60)} 分钟</Descriptions.Item>
        <Descriptions.Item label="录制规则版本">{s.recording_rules_version}</Descriptions.Item>
        <Descriptions.Item label="备注" span={2}>
          {s.note ?? "—"}
        </Descriptions.Item>
      </Descriptions>
      <Typography.Title level={5}>主体段异议（按时间点提出）</Typography.Title>
      <List bordered dataSource={s.objections} style={{ marginBottom: 24 }} renderItem={(o) => <List.Item><Tag color="blue">{msToClock(o.at_ms)}</Tag>{o.text}</List.Item>} />
      <Typography.Title level={5}>知识问答（每题 {String(s.draw_rule.question_seconds)} 秒）</Typography.Title>
      <List bordered dataSource={s.questions} style={{ marginBottom: 24 }} renderItem={(q, i) => <List.Item>{i + 1}. {q.text}</List.Item>} />
      <Typography.Title level={5}>朗读稿</Typography.Title>
      <Typography.Paragraph style={{ background: "#fafafa", padding: 16 }}>{s.reading_text}</Typography.Paragraph>
      <Space>
        <Button href={`/sheets/${s.id}/print?copy=staff`} target="_blank">打印工作人员联</Button>
        <Button href={`/sheets/${s.id}/print?copy=candidate`} target="_blank">打印候选人联</Button>
      </Space>
    </>
  );
}
