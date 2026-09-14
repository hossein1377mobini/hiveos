// HiveOS Windows client (thin): installs small, connects to the HiveOS server
// and shows the app UI in a desktop window. Server URL is editable via config.
const { app, BrowserWindow, shell, Menu } = require("electron");
const fs = require("fs");
const path = require("path");

const DEFAULT_URL = "http://193.93.169.136/";
const cfgPath = path.join(app.getPath("userData"), "config.json");

function serverUrl() {
  try {
    const cfg = JSON.parse(fs.readFileSync(cfgPath, "utf-8"));
    if (cfg && typeof cfg.server_url === "string" && cfg.server_url.startsWith("http")) {
      return cfg.server_url;
    }
  } catch {}
  return DEFAULT_URL;
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1360,
    height: 860,
    autoHideMenuBar: true,
    title: "HiveOS",
    webPreferences: { contextIsolation: true, sandbox: true },
  });
  // open target=_blank / window.open in the OS browser, not inside the app.
  // E: openExternal hands the string to the OS, so only real web links may
  // reach it - a file://, smb:// or custom-scheme URL from page content would
  // otherwise launch an arbitrary local handler.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (!/^https?:[/][/]/i.test(url)) return { action: "deny" };
    shell.openExternal(url);
    return { action: "deny" };
  });
  win.loadURL(serverUrl());
}

Menu.setApplicationMenu(null);
app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
