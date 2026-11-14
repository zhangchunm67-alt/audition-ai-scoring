import { Alert, Button, List, Popconfirm, Tag } from "antd";
import { useParams } from "react-router-dom";
import { post, type S } from "../api/client";
import { useAuth } from "../auth";
import { msToClock, useAction, useFetch } from "../components/hooks";
import { IconPrint } from "../components/icons";
import { ConfigStatus, MetaGrid, PageHeader, SectionTitle } from "../components/ui";

export default function SheetDetail() {
  const { id } = useParams();
  const { data: s, reload } = useFetch<S<"SheetOut">>(`/sheets/${id}`);
  const { can } = useAuth();
  const act = useAction();
  if (!s) return null;
  return (
    <>
      <PageHeader
        back={{ to: "/sheets", label: "试镜题单" }}
        title={`题单 ${s.code}`}
        tags={<ConfigStatus status={s.status} />}
        actions={<>
          {can("sheet.write") && s.status === "issued" && (
            <Popconfirm title="作废后不能再用于上传，确定？" onConfirm={async () => (await act(() => post(`/sheets/${id}/void`), "已作废")) && reload()}>
              <Button danger>作废</Button>
            </Popconfirm>
          )}
          <Button icon={<IconPrint />} href={`/sheets/${s.id}/print?copy=candidate`} target="_blank">打印候选人联</Button>
          <Button icon={<IconPrint />} href={`/sheets/${s.id}/print?copy=staff`} target="_blank">打印工作人员联</Button>
        </>}
      />
      {s.uses_draft_config && <Alert type="warning" showIcon style={{ marginBottom: 16 }} message="本题单使用的评分标准或红线词表是草稿，据此出的报告会标注“非正式”。" />}
      <MetaGrid columns={3} style={{ marginBottom: 24 }} items={[
        { label: "产品", value: s.product_name },
        { label: "卖点卡", value: `第 ${s.product_card_version} 版` },
        { label: "评分标准", value: s.rubric_version },
        { label: "红线词表", value: s.redline_lexicon_version },
        { label: "准备时间", value: `${Math.round((s.draw_rule.prep_seconds as number) / 60)} 分钟` },
        { label: "录制规则版本", value: s.recording_rules_version },
        s.note ? { label: "备注", value: s.note } : null,
      ]} />
      <div className="split">
        <div>
          <SectionTitle>主体段异议<small>按时间点提出</small></SectionTitle>
          <List bordered dataSource={s.objections} renderItem={(o) => <List.Item><Tag color="blue" className="mono">{msToClock(o.at_ms)}</Tag>{o.text}</List.Item>} />
          {s.questions.length > 0 && (
            <>
              <SectionTitle style={{ marginTop: 24 }}>知识问答<small>每题 {String(s.draw_rule.question_seconds)} 秒</small></SectionTitle>
              <List bordered dataSource={s.questions} renderItem={(q, i) => <List.Item>{i + 1}. {q.text}</List.Item>} />
            </>
          )}
        </div>
        <div>
          <SectionTitle>朗读稿</SectionTitle>
          <div className="prose-block">{s.reading_text}</div>
        </div>
      </div>
    </>
  );
}
