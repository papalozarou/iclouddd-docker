# Telegram

## Command format

Commands are only accepted from the chat ID configured in `H_TGM_CHAT_ID`.
If `H_TGM_CHAT_ID` is unset, Telegram command handling is disabled.

Supported command forms:

- `<username> backup`
- `<username> auth`
- `<username> auth 123456`
- `<username> reauth`
- `<username> reauth 123456`

N.B.

`<username>` must match the container username for that worker service.

## Authentication and reauthentication flow

1. On startup, the worker attempts iCloud authentication using saved session
   state and configured credentials.
2. If MFA is required, the worker marks auth pending and sends a prompt.
3. The user sends either `auth <code>` or `reauth <code>` via Telegram to
   complete the current pending challenge.
4. `auth <code>` and `reauth <code>` do not start a fresh login attempt; they
   only validate against the active pending session.
5. On worker startup, the container captures a startup cutover point, drains
   only older queued Telegram updates, then switches to live polling.
6. Commands that arrive after startup begins are preserved for active
   handling; only pre-start backlog is discarded.
7. Startup drain still completes if newer Telegram updates keep arriving while
   the worker is starting.
8. One-shot and scheduled modes both use the same cutover contract, so a
   restart does not change which commands count as backlog.
9. If a worker restart clears in-memory auth session state, send `auth` or
   `reauth` without a code first to trigger a new challenge prompt.
10. If successful, pending auth state is cleared and normal backup flow
    resumes.

## Password file behaviour

`<SVC>_ICLOUD_PASSWORD_FILE` can hold either:

- an Apple Account password; or
- an app-specific password.

The value is passed directly to `pyicloud`, and final auth/MFA handling still
follows Apple account policy.

## Outbound Telegram messages

Messages use this compact plain-text structure:

- Emoji header in sentence case.
- One-line action summary including Apple ID.
- Optional compact status lines.

Current message templates include:

- `🟢 PCD Drive - Container started`
- `🛑 PCD Drive - Container stopped`
- `🔑 PCD Drive - Authentication required`
- `🔑 PCD Drive - Reauthentication required`
- `🔒 PCD Drive - Authentication complete`
- `❌ PCD Drive - Authentication failed`
- `📥 PCD Drive - Backup requested`
- `⬇️ PCD Drive - Backup started`
- `📦 PCD Drive - Backup complete`
- `⏭️ PCD Drive - Backup skipped`
- `⚠️ PCD Drive - Safety net blocked`
- `📣 PCD Drive - Reauth reminder`

Backup completion messages include:

- `Transferred: <done>/<total>`
- `Skipped: <count>`
- `Errors: <count>` where the count includes both transfer and delete-phase errors
- `Delete errors: <count>` when mirror-delete encountered cleanup failures
- `Duration: <hh:mm:ss>`
- `Average speed: <value> MiB/s` (only when files were downloaded)

Backup start messages include:

- `Scheduled <plain English schedule>`
- `Manual, then <plain English schedule>`

Safety-net blocked messages include an explicit expected ownership line:

- `Expected uid <uid>, gid <gid>`
