# Public Document Ingestion

This project uses a static, file-backed policy cache for web deployment. Render should read committed cache files and should not run browser automation or high-memory document fetching during a demo.

## Operating Rules

- Ingest only public documents from the allowlisted policy registry in `src/data/policy_registry.json`.
- Do not use login-only sources, private files, or restricted network locations.
- If a public page does not fetch cleanly, download the official public PDF/HTML/text manually through a normal browser and ingest it locally.
- Commit only cleaned `.txt` cache files and `data/manual_policy_cache/manifest.json`.
- Do not commit raw downloaded source files.

## Local Ingest Folder

Place manually downloaded public files in:

```text
data/manual_policy_ingest/
```

The folder is git-ignored except for `.gitkeep`.

Preferred filename format:

```text
<policy-registry-id>.pdf
<policy-registry-id>.html
<policy-registry-id>.txt
```

Example:

```text
data/manual_policy_ingest/pa-group-collective-agreement.pdf
```

## Ingest Commands

Ingest all supported files from the local ingest folder:

```bash
python3 scripts/ingest_public_documents.py
```

Ingest one file whose filename does not match a registry id:

```bash
python3 scripts/ingest_public_documents.py ~/Downloads/PA-CBA.pdf --id pa-group-collective-agreement
```

Preview without writing:

```bash
python3 scripts/ingest_public_documents.py --dry-run
```

Supported source formats:

- `.pdf` using local `pdftotext`
- `.html` / `.htm`
- `.txt`
- `.md`

## Output

The ingest script writes cleaned text to:

```text
data/manual_policy_cache/<policy-registry-id>.txt
```

It also updates:

```text
data/manual_policy_cache/manifest.json
```

Cache entries ingested this way use:

```json
"capture_method": "local_public_document"
```

## Render Behavior

Render uses the committed manual cache first. Keep these environment settings for demo stability:

```text
BROWSER_FETCH_ENABLED=false
PARSING_ENABLED=false
PARSING_TEACHER_LOOP_ENABLED=false
```

This keeps Render memory low and avoids runtime document extraction. New public documents should be ingested locally, committed, and deployed as static cache updates.
