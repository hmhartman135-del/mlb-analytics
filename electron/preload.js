/**
 * Electron preload — exposes a safe API bridge to both the setup screen
 * and the main Next.js app.
 */
const { contextBridge, ipcRenderer, shell } = require("electron");

contextBridge.exposeInMainWorld("electronApp", {
  // Setup screen
  saveApiKey:    (key) => ipcRenderer.invoke("save-api-key", key),
  getApiKey:     ()    => ipcRenderer.invoke("get-api-key"),
  setupComplete: ()    => ipcRenderer.invoke("setup-complete"),

  // General
  getVersion:    ()    => ipcRenderer.invoke("app-version"),
  isDev:         ()    => ipcRenderer.invoke("is-dev"),
  openLogs:      ()    => ipcRenderer.invoke("open-logs"),
  openExternal:  (url) => shell.openExternal(url),
});
