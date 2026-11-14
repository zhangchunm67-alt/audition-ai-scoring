import {
  BarChartOutlined, DownOutlined, DownloadOutlined, KeyOutlined, LogoutOutlined, PlusOutlined, PrinterOutlined,
  ReadOutlined, ReloadOutlined, SettingOutlined, SlidersOutlined, UploadOutlined, VideoCameraOutlined,
} from "@ant-design/icons";
import type { ComponentType } from "react";

type AnyIcon = ComponentType<Record<string, unknown>>;

/** 图标都是装饰性的：加 aria-hidden，读屏和按名称查找控件时只认文字。 */
const decorative = (Icon: unknown) => {
  const I = Icon as AnyIcon;
  return () => <I aria-hidden />;
};

export const IconPlus = decorative(PlusOutlined);
export const IconUpload = decorative(UploadOutlined);
export const IconDownload = decorative(DownloadOutlined);
export const IconPrint = decorative(PrinterOutlined);
export const IconReload = decorative(ReloadOutlined);
export const IconDown = decorative(DownOutlined);
export const IconKey = decorative(KeyOutlined);
export const IconLogout = decorative(LogoutOutlined);
export const IconSettings = decorative(SettingOutlined);
export const IconVideo = decorative(VideoCameraOutlined);
export const IconChart = decorative(BarChartOutlined);
export const IconBook = decorative(ReadOutlined);
export const IconSliders = decorative(SlidersOutlined);
