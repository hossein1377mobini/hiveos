// Preload bridge for the HiveOS Windows client.
//
// The renderer is the hosted web app, so it is untrusted code as far as the
// desktop shell is concerned: expose exactly the few capabilities the US-007
// onboarding needs (pick a folder, walk it, read one file, watch for changes)
// and nothing else. No Node, no fs, no ipcRenderer leaks into the page.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("hiveosDesktop", {
  // Marker: the web app uses this to decide whether a native picker exists.
  isDesktop: true,
  platform: process.platform,
  pickFolder: () => ipcRenderer.invoke("hiveos:pick-folder"),
  scanFolder: (folder) => ipcRenderer.invoke("hiveos:scan-folder", folder),
  readFile: (folder, relPath) =>
    ipcRenderer.invoke("hiveos:read-file", { folder, relPath }),
  saveConfig: (config) => ipcRenderer.invoke("hiveos:save-config", config),
  loadConfig: () => ipcRenderer.invoke("hiveos:load-config"),
  // Live progress for a sync run, so the onboarding step can show a real
  // "۳ از ۱۲ فایل" counter instead of a frozen spinner.
  onSyncProgress: (handler) => {
    const listener = (_event, payload) => handler(payload);
    ipcRenderer.on("hiveos:sync-progress", listener);
    return () => ipcRenderer.removeListener("hiveos:sync-progress", listener);
  },
});
