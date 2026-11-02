/** 刚上传完的本地文件预览地址，只存在内存里：刷新页面后 blob 地址失效，自动改用后端代理播放。 */
const urls = new Map<string, string>();

export const rememberLocal = (recordingId: string, file: File) => {
  const old = urls.get(recordingId);
  if (old) URL.revokeObjectURL(old);
  urls.set(recordingId, URL.createObjectURL(file));
};

export const localUrlOf = (recordingId: string) => urls.get(recordingId);
