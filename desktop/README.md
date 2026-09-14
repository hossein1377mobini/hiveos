# HiveOS Windows client

Thin Electron shell (ADR-023). It does **not** contain the web app: it opens
`https://hivesystem.ir/` in a window and adds the one thing a browser cannot do —
a native folder picker so the owner can point at their own documents folder.

Because the UI is loaded from the server, a frontend deploy reaches desktop
users with no client rebuild. Rebuild is only needed when `src/` itself changes.

## What the shell may do

The renderer is untrusted hosted code, so the bridge in `src/preload.js` is
deliberately tiny: pick a folder, list it, read one file, save/load the server
URL. No Node, no `fs`, no `ipcRenderer` reaches the page. `contextIsolation`
and `sandbox` are both on.

`src/folder.js` enforces the same rules the server does, so the client never
offers a file the server would refuse:

| Rule | Value | Source |
| --- | --- | --- |
| Formats | txt md pdf docx pptx xlsx csv jpg jpeg png tif tiff bmp webp | US-205 |
| Max size | 25 MB per file | PO rule |
| Max files | 5000 per scan | safety |
| Max depth | 12 | safety |

Files stay on the owner's machine: the client reads a listing plus the bytes of
new or changed files, and everything else (parsing, chunking, embedding) happens
on the server.

## Build

```bash
npm install
npm run start      # run against the live server
npm run dist       # NSIS installer -> dist/HiveOS Setup <version>.exe
```

The published installer is served at
`https://hivesystem.ir/downloads/HiveOS-Setup-0.1.0.exe`. The file name is
stable, so a rebuild must be copied over that path or users keep downloading the
old build.

## Server URL

Read from `<userData>/config.json` (`{"server_url": "..."}`) and editable in
the app; the default is `https://hivesystem.ir/`. A non-HTTP value is ignored.
