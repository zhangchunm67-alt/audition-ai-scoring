import { Button, Table, Tag, Typography } from "antd";
import { useState } from "react";
import { Link } from "react-router-dom";
import type { S } from "../api/client";
import { useAuth } from "../auth";
import { useFetch } from "../components/hooks";
import NewProductModal from "../components/NewProductModal";

type P = S<"ProductOut">;

export default function Products() {
  const { data, loading, reload } = useFetch<P[]>("/products");
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Typography.Title level={4}>产品资料</Typography.Title>
      {can("config.write") && (
        <Button type="primary" style={{ marginBottom: 16 }} onClick={() => setOpen(true)}>
          新建产品
        </Button>
      )}
      <Table<P>
        rowKey="id"
        loading={loading}
        dataSource={data}
        pagination={false}
        columns={[
          { title: "产品", dataIndex: "name", render: (n, p) => <Link to={`/products/${p.id}`}>{n}</Link> },
          { title: "编码", dataIndex: "code" },
          { title: "已启用资料版本", dataIndex: "published_card_version", render: (v) => (v ? <Tag color="green">第 {v} 版</Tag> : <Tag color="orange">未启用</Tag>) },
        ]}
      />
      <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
        按产品维护参考脚本、资料版本和校准状态。录播中的实际观众问题在录像页标注；按题单试镜的题库和抽题规则从“试镜题单”进入设置。
      </Typography.Paragraph>
      <NewProductModal open={open} onClose={() => setOpen(false)} onCreated={() => {
        setOpen(false);
        reload();
      }} />
    </>
  );
}
