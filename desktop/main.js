const { app, BrowserWindow, ipcMain, dialog, shell } = require("electron");
const path = require("path");
const fs = require("fs");
const os = require("os");
const { spawn } = require("child_process");

const BACKEND_PORT = 8756;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const BACKEND_DIR = path.join(__dirname, "..", "backend");

let mainWindow = null;
let backendProcess = null;

// --- Settings -----------------------------------------------------------

function settingsPath() {
  return path.join(app.getPath("userData"), "settings.json");
}

function loadSettings() {
  try {
    return JSON.parse(fs.readFileSync(settingsPath(), "utf-8"));
  } catch {
    return { anthropicApiKey: "", moosePath: "", mistPath: "", dcsMissionsFolder: "" };
  }
}

function saveSettings(partial) {
  const current = loadSettings();
  const merged = { ...current, ...partial };
  fs.mkdirSync(path.dirname(settingsPath()), { recursive: true });
  fs.writeFileSync(settingsPath(), JSON.stringify(merged, null, 2));
  return merged;
}

function autodetectDcsMissionsFolder() {
  const savedGames = path.join(os.homedir(), "Saved Games");
  for (const variant of ["DCS.openbeta", "DCS"]) {
    const candidate = path.join(savedGames, variant, "Missions");
    if (fs.existsSync(path.join(savedGames, variant))) {
      fs.mkdirSync(candidate, { recursive: true });
      return candidate;
    }
  }
  return null;
}

// --- Python backend -------------------------------------------------------

function pythonExecutable() {
  const win = process.platform === "win32";
  return path.join(BACKEND_DIR, "venv", win ? "Scripts" : "bin", win ? "python.exe" : "python3");
}

function startBackend() {
  const pythonPath = pythonExecutable();
  if (!fs.existsSync(pythonPath)) {
    console.error(
      `Python venv not found at ${pythonPath}. Run the backend setup steps in README.md first.`
    );
    return;
  }
  backendProcess = spawn(
    pythonPath,
    ["-m", "uvicorn", "app.server:app", "--host", "127.0.0.1", "--port", String(BACKEND_PORT)],
    { cwd: BACKEND_DIR, env: process.env }
  );
  backendProcess.stdout.on("data", (d) => console.log(`[backend] ${d}`));
  backendProcess.stderr.on("data", (d) => console.error(`[backend] ${d}`));
  backendProcess.on("exit", (code) => console.log(`[backend] exited with code ${code}`));
}

async function waitForBackend(timeoutMs = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(`${BACKEND_URL}/health`);
      if (res.ok) return true;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  return false;
}

// --- IPC --------------------------------------------------------------

function registerIpcHandlers() {
  ipcMain.handle("settings:get", () => loadSettings());
  ipcMain.handle("settings:save", (_evt, partial) => saveSettings(partial));
  ipcMain.handle("settings:autodetect-dcs", () => autodetectDcsMissionsFolder());

  ipcMain.handle("dialog:pick-file", async (_evt, filters) => {
    const result = await dialog.showOpenDialog(mainWindow, {
      properties: ["openFile"],
      filters: filters || [],
    });
    return result.canceled ? null : result.filePaths[0];
  });

  ipcMain.handle("dialog:pick-directory", async () => {
    const result = await dialog.showOpenDialog(mainWindow, { properties: ["openDirectory"] });
    return result.canceled ? null : result.filePaths[0];
  });

  ipcMain.handle("shell:show-item", (_evt, filePath) => {
    shell.showItemInFolder(filePath);
  });

  ipcMain.handle("backend:health", async () => waitForBackend(1000));

  ipcMain.handle("backend:options", async () => {
    const res = await fetch(`${BACKEND_URL}/options`);
    if (!res.ok) throw new Error(`Backend error (${res.status})`);
    return res.json();
  });

  ipcMain.handle("generate-mission", async (_evt, prompt, overrides = {}) => {
    const settings = loadSettings();
    // save_path is a full file path and the filename depends on the
    // mission title, which we don't know until the backend generates the
    // spec - so always let the backend write to a temp path, then copy it
    // into the configured DCS Missions folder below once we have a name.
    // Overrides left empty/null by the UI are omitted so the backend treats
    // them as "Auto" (inferred from the prompt).
    const body = {
      prompt,
      moose_lua_path: settings.moosePath || null,
      mist_lua_path: settings.mistPath || null,
      anthropic_api_key: settings.anthropicApiKey || null,
      save_path: null,
      theater: overrides.theater || null,
      player_aircraft: overrides.player_aircraft || null,
      time_of_day: overrides.time_of_day || null,
      weather: overrides.weather || null,
    };

    const res = await fetch(`${BACKEND_URL}/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || `Backend error (${res.status})`);
    }

    if (settings.dcsMissionsFolder) {
      const destName = path.basename(data.saved_path);
      const dest = path.join(settings.dcsMissionsFolder, destName);
      fs.mkdirSync(settings.dcsMissionsFolder, { recursive: true });
      fs.copyFileSync(data.saved_path, dest);
      data.saved_path = dest;
    }

    return data;
  });
}

// --- App lifecycle ------------------------------------------------------

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 900,
    height: 760,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
}

app.whenReady().then(() => {
  registerIpcHandlers();
  startBackend();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("will-quit", () => {
  if (backendProcess) backendProcess.kill();
});
