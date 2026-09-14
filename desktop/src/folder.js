// Folder access for the HiveOS Windows client (US-007, ADR-023 thin client).
//
// The owner's documents stay on the owner's machine: this module only reads
// the folder listing (relative path + size + a cheap change fingerprint) and
// the bytes of the files that are new or changed. Everything else - parsing,
// chunking, embedding - happens on the server.
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

// Must stay identical to the server's US-205 table: a file this module offers
// but the server refuses is a broken promise, and vice versa.
const ALLOWED_EXTENSIONS = new Set([
  "txt", "md", "pdf", "docx", "pptx", "xlsx", "csv",
  "jpg", "jpeg", "png", "tif", "tiff", "bmp", "webp",
]);

// Same ceilings the server enforces (US-201 Am2 + PO rule): max 25MB per file.
const MAX_FILE_MB = 25;
const MAX_FILES = 5000;
const MAX_DEPTH = 12;
const SKIP_DIRS = new Set([
  "node_modules", "$recycle.bin", "system volume information",
  ".git", ".svn", "appdata", "windows", "program files", "program files (x86)",
]);

function relativePath(root, fullPath) {
  return path.relative(root, fullPath).split(path.sep).join("/");
}

function isScannable(name) {
  const ext = path.extname(name).slice(1).toLowerCase();
  return ALLOWED_EXTENSIONS.has(ext);
}

/** Walk one folder and return the manifest entries the server understands. */
function scanFolder(folder) {
  const root = path.resolve(folder);
  const stat = fs.statSync(root);
  if (!stat.isDirectory()) throw new Error("NOT_A_DIRECTORY");

  const maxBytes = MAX_FILE_MB * 1024 * 1024;
  const entries = [];
  const skipped = [];
  let truncated = false;

  const walk = (dir, depth) => {
    if (truncated || depth > MAX_DEPTH) return;
    let items;
    try {
      items = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return; // an unreadable subfolder must not abort the whole scan
    }
    for (const item of items) {
      if (truncated) return;
      const full = path.join(dir, item.name);
      if (item.isDirectory()) {
        if (SKIP_DIRS.has(item.name.toLowerCase())) continue;
        if (item.name.startsWith(".")) continue;
        walk(full, depth + 1);
        continue;
      }
      if (!item.isFile() || item.name.startsWith("~$")) continue;
      const rel = relativePath(root, full);
      if (!isScannable(item.name)) {
        skipped.push({ rel_path: rel, code: "FORMAT_NOT_ALLOWED" });
        continue;
      }
      let fileStat;
      try {
        fileStat = fs.statSync(full);
      } catch {
        continue; // locked (open in Word/Excel) - picked up on the next round
      }
      if (fileStat.size > maxBytes) {
        skipped.push({ rel_path: rel, code: "TOO_LARGE", limit_mb: MAX_FILE_MB });
        continue;
      }
      if (entries.length >= MAX_FILES) {
        truncated = true;
        return;
      }
      // Cheap change detection: size + mtime. The server re-checks the content
      // it actually receives, so a stale mtime costs one re-upload, never a
      // silently skipped edit.
      entries.push({
        rel_path: rel,
        size_bytes: fileStat.size,
        mtime_ms: Math.floor(fileStat.mtimeMs),
        fingerprint: crypto
          .createHash("sha1")
          .update(`${rel}|${fileStat.size}|${Math.floor(fileStat.mtimeMs)}`)
          .digest("hex"),
      });
    }
  };

  walk(root, 0);
  return {
    folder: root,
    name: path.basename(root) || root,
    entries,
    skipped,
    truncated,
    max_files: MAX_FILES,
  };
}

/** Read one file for upload; the path is re-checked so it cannot escape root. */
function readFileForUpload(folder, relPath) {
  const root = path.resolve(folder);
  const target = path.resolve(root, relPath);
  const prefix = root.endsWith(path.sep) ? root : root + path.sep;
  if (target !== root && !target.startsWith(prefix)) throw new Error("PATH_ESCAPE");
  const stat = fs.statSync(target);
  if (!stat.isFile()) throw new Error("NOT_A_FILE");
  if (stat.size > MAX_FILE_MB * 1024 * 1024) throw new Error("TOO_LARGE");
  if (!isScannable(path.basename(target))) throw new Error("FORMAT_NOT_ALLOWED");
  return fs.readFileSync(target);
}

module.exports = {
  ALLOWED_EXTENSIONS,
  MAX_FILE_MB,
  MAX_FILES,
  scanFolder,
  readFileForUpload,
};
