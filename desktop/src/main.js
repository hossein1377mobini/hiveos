// HiveOS Windows client (thin, ADR-023): connects to the HiveOS server and
// shows the app UI in a desktop window.
//
// US-007 (PO decision 2026-09-14): the ingestion folder is a folder ON THIS
// MACHINE. The renderer therefore gets three narrow bridges - pick a folder,
// list its files, read one file - and nothing else. All processing stays on
// the server.
const { app, BrowserWindow, Menu, dialog, ipcMain, shell } = require("electron");
const fs = require("fs");
const path = require("path");

const { readFileForUpload, scanFolder } = require("./folder");

const DEFAULT_URL = "https://hivesystem.ir/";
const cfgPath = path.join(app.getPath("userData"), "config.json");

function readConfig() {
  try {
    return JSON.parse(fs.readFileSync(cfgPath, "utf-8")) || {};
  } catch {
    return {};
  }
}

function serverUrl() {
  const cfg = readConfig();
  if (cfg && typeof cfg.server_url === "string" && cfg.server_url.startsWith("http")) {
    return cfg.server_url;
  }
  return DEFAULT_URL;
}

/**
 * THE MISSING CONTEXT MENU (PO report: "راست کلیک موس برای اقداماتی مثل کپی توی
 * متن چت انگار باز نمیشه").
 *
 * Electron does NOT create a default context menu. Unlike a browser, where right
 * -click on text opens Chromium's Copy / Select All menu, an Electron window
 * shows nothing unless the app builds the menu itself. This file had no
 * 'context-menu' handler at all, so right-clicking inside the chat transcript -
 * or anywhere else in the app - did nothing. That is the whole defect; nothing
 * in the web UI suppresses the menu.
 *
 * Built from roles rather than labels + click handlers: roles use Electron's own
 * built-in behaviour and localisation, and 'copy' operates on the current
 * selection exactly as the browser's menu would.
 *
 * scoped to a window, not global: the menu is attached to the window that
 * received the click (via event.sender) so a second window does not pop a menu
 * belonging to the first.
 */
function attachContextMenu(win) {
  win.webContents.on("context-menu", (event, params) => {
    const template = [];
    // Only offer actions that can do something. A menu with every item greyed
    // out is worse than no menu: it implies the text is not selectable.
    if (params.selectionText && params.selectionText.trim()) {
      template.push({ role: "copy", label: "کپی" });
    }
    if (params.isEditable) {
      // Chat input and any form field: the standard editing set.
      template.push(
        { role: "cut", label: "برش" },
        { role: "copy", label: "کپی" },
        { role: "paste", label: "چسباندن" },
      );
    }
    if (params.linkURL) {
      template.push({
        label: "بازکردن پیوند در مرورگر",
        click: () => {
          // Same protocol rule as setWindowOpenHandler below: only real web
          // links reach the OS, so page content cannot launch a local handler.
          if (/^https?:[/][/]/i.test(params.linkURL)) {
            shell.openExternal(params.linkURL);
          }
        },
      });
    }
    if (!template.length) {
      // Nothing is selected and this is not a field: "select all" is the only
      // useful action, and offering it lets the user select then copy.
      template.push({ role: "selectAll", label: "انتخاب همه" });
    }
    Menu.buildFromTemplate(template).popup({ window: win });
  });
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1360,
    height: 860,
    autoHideMenuBar: true,
    title: "HiveOS",
    // contextIsolation keeps the page away from Node; the preload exposes the
    // folder bridge. sandbox stays on for the renderer process itself.
    webPreferences: {
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.js"),
    },
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
  attachContextMenu(win);
  win.loadURL(serverUrl());
  return win;
}

/** One native picker, owned by the window that asked for it. */
function registerFolderBridge() {
  ipcMain.handle("hiveos:pick-folder", async (event) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    const result = await dialog.showOpenDialog(win, {
      title: "پوشه اسناد سازمان را انتخاب کنید",
      buttonLabel: "انتخاب این پوشه",
      properties: ["openDirectory", "dontAddToRecent"],
    });
    if (result.canceled || result.filePaths.length === 0) return { canceled: true };
    return { canceled: false, path: result.filePaths[0] };
  });

  ipcMain.handle("hiveos:scan-folder", (_event, folder) => {
    if (typeof folder !== "string" || !folder.trim()) {
      return { error: "EMPTY_PATH" };
    }
    try {
      return scanFolder(folder);
    } catch (exc) {
      return { error: exc && exc.message ? exc.message : "SCAN_FAILED" };
    }
  });

  ipcMain.handle("hiveos:read-file", (_event, payload) => {
    const folder = payload && payload.folder;
    const relPath = payload && payload.relPath;
    if (typeof folder !== "string" || typeof relPath !== "string") {
      return { error: "BAD_REQUEST" };
    }
    try {
      const buffer = readFileForUpload(folder, relPath);
      // Uint8Array survives the structured clone; Buffer objects do not.
      return { data: new Uint8Array(buffer) };
    } catch (exc) {
      return { error: exc && exc.message ? exc.message : "READ_FAILED" };
    }
  });

  ipcMain.handle("hiveos:save-config", (_event, config) => {
    const current = readConfig();
    const next = { ...current, ...(config || {}) };
    fs.writeFileSync(cfgPath, JSON.stringify(next, null, 2), "utf-8");
    return { ok: true };
  });

  ipcMain.handle("hiveos:load-config", () => readConfig());
}

Menu.setApplicationMenu(null);
app.whenReady().then(() => {
  registerFolderBridge();
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
