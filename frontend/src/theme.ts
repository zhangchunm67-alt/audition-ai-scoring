import type { ThemeConfig } from "antd";

/** Shared system tokens; page components keep their native Ant Design behavior. */
export const appTheme: ThemeConfig = {
  token: {
    colorPrimary: "#2563eb",
    colorInfo: "#2563eb",
    colorSuccess: "#19734b",
    colorWarning: "#946200",
    colorError: "#c03432",
    colorText: "#202733",
    colorTextSecondary: "#626d7d",
    colorBgLayout: "#f5f6f8",
    colorBorder: "#d8dde5",
    colorBorderSecondary: "#e9ecf1",
    borderRadius: 10,
    fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif',
    fontSize: 14,
    controlHeight: 34,
    lineHeight: 1.65,
  },
  components: {
    Button: { primaryShadow: "none", defaultShadow: "none", fontWeight: 500 },
    Card: { headerFontSize: 16, headerHeight: 44, paddingLG: 18 },
    Menu: { itemHeight: 36, itemBorderRadius: 10, itemSelectedBg: "#e7eefc", itemSelectedColor: "#1d4ed8", itemMarginInline: 8 },
    Table: { headerBg: "#f8f9fb", headerColor: "#626d7d", rowHoverBg: "#f5f8ff", cellPaddingBlock: 10 },
    Tabs: { horizontalItemGutter: 28, titleFontSize: 14 },
    Modal: { borderRadiusLG: 16 },
    Typography: { titleMarginTop: 0, titleMarginBottom: 16 },
  },
};
