# Telegram

Telegram gives each worker a small control channel. Use it to complete iCloud
authentication, trigger manual backups, and receive backup status messages.

Commands only work from the chat ID configured in `H_TGM_CHAT_ID`. If that
value is unset, Telegram command handling is disabled.

## Commands

Send commands in this form:

```text
alice backup
alice auth
alice auth 123456
alice reauth
alice reauth 123456
```

Replace `alice` with the worker name set by `CONTAINER_USERNAME`.

The supported commands are:

- `<username> backup`: run a backup now
- `<username> auth`: start or restart the current authentication prompt
- `<username> auth 123456`: submit an MFA code for authentication
- `<username> reauth`: start or restart the current reauthentication prompt
- `<username> reauth 123456`: submit an MFA code for reauthentication

## First-time authentication

On startup, the worker tries to use saved session state and configured
credentials.

If iCloud asks for MFA, the worker sends an authentication prompt to Telegram.
Reply with:

```text
alice auth 123456
```

`auth 123456` does not start a fresh login. It answers the active challenge
that iCloud already issued.

If the worker restarts and loses the in-memory challenge, send this first:

```text
alice auth
```

That asks the worker to start a new challenge and send a fresh prompt.

## Reauthentication

Reauthentication uses the same shape as first-time authentication:

```text
alice reauth
alice reauth 123456
```

Use `reauth` when the worker says reauthentication is required. Use
`reauth 123456` to submit the code from Apple.

## Manual backups

Send:

```text
alice backup
```

The worker starts a backup as soon as it can. If another backup is already in
progress, the command is handled according to the live runtime state and the
worker reports the outcome in Telegram and logs.

## Messages you will see

Messages use compact plain text:

- an emoji header in sentence case
- one-line action summary including the Apple ID
- short status lines where useful

Common headers include:

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

Backup completion messages can include:

- `Transferred: <done>/<total>`
- `Skipped: <count>`
- `Errors: <count>`
- `Delete errors: <count>`
- `Duration: <hh:mm:ss>`
- `Average speed: <value> MiB/s`

`Errors` includes transfer errors and delete-phase errors. `Average speed` only
appears when files were downloaded.

Backup start messages include either:

- `Scheduled <plain English schedule>`
- `Manual, then <plain English schedule>`

Safety-net blocked messages include the ownership the worker expected:

```text
Expected uid <uid>, gid <gid>
```

## When commands are ignored

Commands are ignored when:

- they come from a different Telegram chat
- `H_TGM_CHAT_ID` is unset
- the username does not match that worker
- the command is not one of the supported forms above

On startup, the worker discards old queued Telegram updates once, then switches
to live polling. That stops stale commands from firing after a restart while
preserving commands that arrive after the worker has started.

## Password files

`<SVC>_ICLOUD_PASSWORD_FILE` can contain either:

- an Apple Account password
- an app-specific password

The worker passes the value to `pyicloud`. Apple still decides whether MFA is
required.
