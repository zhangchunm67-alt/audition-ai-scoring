import { Typography } from "antd";
import type { ReactNode } from "react";

export default function PageHeader({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return (
    <div className="page-heading">
      <div>
        <Typography.Title level={1}>{title}</Typography.Title>
        <Typography.Paragraph type="secondary">{description}</Typography.Paragraph>
      </div>
      {action && <div className="page-heading-action">{action}</div>}
    </div>
  );
}
