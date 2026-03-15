# Configuration

This is the practical map of what needs setting in `.env`, what it does, and
which values you can mostly leave alone.

## How the variables are grouped

- service environment variables are the values the worker actually receives.
- `.env.example` service variables are the source values Compose maps into each
  service.
- `H_` values describe the host.
- `C_` values describe shared in-container paths and IDs.
- build variables control image names and versions.

## Service environment variables

These are the env names used under `services.*.environment` in
[compose.yml.example](compose.yml.example) and
[compose.build.yml.example](compose.build.yml.example).

| Variable name | Possible values | `.env.example` |
| --- | --- | --- |
| `CONTAINER_USERNAME` | Service label string, for example `alice` or `bob` | Fixed in Compose, not sourced from `.env.example` |
| `ICLOUD_EMAIL_FILE` | In-container file path containing the Apple ID email | `<SVC>_ICLOUD_EMAIL_FILE`, for example `ALICE_ICLOUD_EMAIL_FILE` |
| `ICLOUD_PASSWORD_FILE` | In-container file path containing the Apple ID password | `<SVC>_ICLOUD_PASSWORD_FILE`, for example `ALICE_ICLOUD_PASSWORD_FILE` |
| `REAUTH_INTERVAL_DAYS` | Integer day count, default `30` | `<SVC>_REAUTH_INTERVAL_DAYS`, for example `ALICE_REAUTH_INTERVAL_DAYS` |
| `RUN_ONCE` | `true` or `false`, default `false` | `<SVC>_RUN_ONCE`, for example `ALICE_RUN_ONCE` |
| `SCHEDULE_MODE` | `interval`, `daily`, `weekly`, `twice_weekly`, or `monthly` | `<SVC>_SCHEDULE_MODE`, for example `ALICE_SCHEDULE_MODE` |
| `SCHEDULE_BACKUP_TIME` | `HH:MM` 24-hour local time, default `02:00` | `<SVC>_SCHEDULE_BACKUP_TIME`, for example `ALICE_SCHEDULE_BACKUP_TIME` |
| `SCHEDULE_WEEKDAYS` | Comma-separated weekday names, for example `monday` or `monday,thursday` | `<SVC>_SCHEDULE_WEEKDAYS`, for example `ALICE_SCHEDULE_WEEKDAYS` |
| `SCHEDULE_MONTHLY_WEEK` | `first`, `second`, `third`, `fourth`, or `last` | `<SVC>_SCHEDULE_MONTHLY_WEEK`, for example `ALICE_SCHEDULE_MONTHLY_WEEK` |
| `SCHEDULE_INTERVAL_MINUTES` | Integer minute count, default `1440` | `<SVC>_SCHEDULE_INTERVAL_MINUTES`, for example `ALICE_SCHEDULE_INTERVAL_MINUTES` |
| `SYNC_TRAVERSAL_WORKERS` | Integer `1` to `8`, default `1` | `<SVC>_SYNC_TRAVERSAL_WORKERS`, for example `ALICE_SYNC_TRAVERSAL_WORKERS` |
| `SYNC_DOWNLOAD_WORKERS` | `auto` or integer `1` to `16`, default `auto` | `<SVC>_SYNC_DOWNLOAD_WORKERS`, for example `ALICE_SYNC_DOWNLOAD_WORKERS` |
| `SYNC_DOWNLOAD_CHUNK_MIB` | Integer `1` to `16`, default `4` | `<SVC>_SYNC_DOWNLOAD_CHUNK_MIB`, for example `ALICE_SYNC_DOWNLOAD_CHUNK_MIB` |
| `BACKUP_DELETE_REMOVED` | `true` or `false`, default `false` | `<SVC>_BACKUP_DELETE_REMOVED`, for example `ALICE_BACKUP_DELETE_REMOVED` |
| `TELEGRAM_CHAT_ID` | Telegram chat ID integer string | `H_TGM_CHAT_ID` |
| `TELEGRAM_BOT_TOKEN_FILE` | In-container file path containing the bot token | `<SVC>_TGM_BOT_TOKEN_FILE`, for example `ALICE_TGM_BOT_TOKEN_FILE` |

*N.B.*

- When `RUN_ONCE=true`, set `<SVC>_RESTART_POLICY=no`.
- If `<SVC>_RESTART_POLICY` uses `unless-stopped` or similar, a one-shot
  container restarts after exit and loops.
- For schedule mode rules and examples, see [SCHEDULING.md](SCHEDULING.md).

## Service source variables (`ALICE_*`, `BOB_*`)

These are the remaining `.env.example` service values not already covered by
the service-environment table above.

### Paths and secrets

- `<SVC>_CONFIG_PATH`: host path mounted to `/config`.
- `<SVC>_OUTPUT_PATH`: host path mounted to `/output`.
- `<SVC>_LOGS_PATH`: host path mounted to `/logs`.
- `<SVC>_TGM_BOT_TOKEN_FILE`: in-container Telegram bot token file path.
- `<SVC>_ICLOUD_EMAIL_FILE`: in-container iCloud email file path.
- `<SVC>_ICLOUD_PASSWORD_FILE`: in-container iCloud password file path.
- `<SVC>_RESTART_POLICY`: Compose restart policy for the service, for example
  `unless-stopped` or `no`.

## Host variables (`H_`)

- `H_UID`: host user ID mapped into containers.
- `H_GID`: host group ID mapped into containers.
- `H_TZ`: timezone for worker behaviour and schedule calculations.
- `H_TGM_CHAT_ID`: only this Telegram chat is accepted for commands.
- `H_DKR_SECRETS`: host path containing source secret files.
- `H_DATA_PATH`: base host path for service data directories.

## Runtime identity mapping

These are usually left as-is unless you need explicit UID or GID mapping.

- `C_UID`: source UID value in `.env` (normally mirrors `H_UID`).
- `C_GID`: source GID value in `.env` (normally mirrors `H_GID`).
- Compose maps `PUID=${C_UID}` and `PGID=${C_GID}` into each service.
- Entrypoint drops from root to `PUID:PGID` before starting the worker.

## Shared container variables (`C_`)

These are usually left as-is unless you have a specific reason to change them.

- `C_DKR_SECRETS`: in-container secret root used by `_FILE` env vars.

## Logging

- `C_LOG_LEVEL`: shared log verbosity value set in `.env`.
  Compose maps this to container env `LOG_LEVEL` through `default-env`.
  Supported values are `info` and `debug`; default is `info`.
  `debug` includes per-item sync traces such as directories ensured,
  files queued/transferred, unchanged skips, and transfer failures.
- `C_LOG_ROTATE_DAILY`: rotate `pyiclodoc-drive-worker.log` when local date changes
  (`true`/`false`, default `true`).
- `C_LOG_ROTATE_MAX_MIB`: rotate `pyiclodoc-drive-worker.log` when file size reaches this MiB
  threshold (default `100`).
- `C_LOG_ROTATE_KEEP_DAYS`: keep rotated `pyiclodoc-drive-worker.*.log.gz` archives for this
  many days before pruning (default `14`).

## Build variables

- `IMG_NAME`: image repository/name used by both Compose examples.
- `IMG_TAG`: published release tag used by `compose.yml.example`.
- `ALP_VER`: Alpine base image version used during Docker build.
- `MCK_VER`: Microcheck image version used during Docker build.

## Default container paths

- `/config`: auth/session state, manifest, and runtime metadata.
- `/output`: downloaded iCloud Drive files.
- `/logs`: worker and healthcheck output.

## `/config` layout

Each worker mounts `/config` from a different host location:

- `icloud_alice` -> `${ALICE_CONFIG_PATH}`
- `icloud_bob` -> `${BOB_CONFIG_PATH}`

Runtime layout:

```text
/config
├── pyiclodoc-drive-auth_state.json
├── pyiclodoc-drive-manifest.json
├── pyiclodoc-drive-safety_net_done.flag
├── pyiclodoc-drive-safety_net_blocked.flag
├── cookies/
├── session/
├── icloudpd/
│   ├── cookies -> /config/cookies
│   └── session -> /config/session
└── keyring/
    └── keyring_pass.cfg
```

*N.B.*

- `pyiclodoc-drive-safety_net_done.flag` is created when first-run safety checks pass.
- `pyiclodoc-drive-safety_net_blocked.flag` is created when first-run safety checks block
  backup.
- `icloudpd/cookies` and `icloudpd/session` are compatibility symlinks.
