# iCloud Drive Backup Container

This project provides an Alpine-based Docker container that performs
incremental iCloud Drive backups with Telegram-driven control and
authentication prompts. The example Compose setup runs two isolated worker
services, one for Alice and one for Bob, with separate state, output, and log
paths.

## Features

- Multi-stage image build with a reduced runtime footprint.
- Required `microcheck`-backed health checks with heartbeat age validation.
- Runtime user and group mapping via container `PUID` and `PGID`.
- Incremental sync model backed by `/config/manifest.json`.
- Session persistence in `/config/session` and cookies in `/config/cookies`.
- Compatibility symlinks in `/config/icloudpd/{cookies,session}`.
- First-run safety net to detect risky local permission mismatches.
- Telegram command handling for backup and authentication workflows.

## Telegram commands

Send commands from the chat configured by `H_TG_CHAT_ID`.

- `<username> backup`
- `<username> auth`
- `<username> auth 123456`
- `<username> reauth`
- `<username> reauth 123456`

`<username>` must match `CONTAINER_USERNAME`.

## Configuration model

The Compose example uses:

- Host-scoped variables prefixed with `H_`.
- Container-scoped variables prefixed with `C_<SVC>_`.
- Service codes `ICA` and `ICB` for the two workers in
  `compose.yml.example`.

### Host-scoped variables (`H_`)

- `H_UID`, host user ID mapped into containers.
- `H_GID`, host group ID mapped into containers.
- `H_TZ`, timezone used by worker time calculations.
- `H_TG_CHAT_ID`, Telegram chat ID accepted by command parser.

### Service-scoped variables (`C_ICA_*`, `C_ICB_*`)

- `C_<SVC>_CONTAINER_USERNAME`, command prefix and runtime username.
- `C_<SVC>_BACKUP_INTERVAL_MINUTES`, scheduled backup interval.
- `C_<SVC>_STARTUP_DELAY_SECONDS`, startup delay to spread API load.
- `C_<SVC>_REAUTH_INTERVAL_DAYS`, reauthentication window length.
- `C_<SVC>_TELEGRAM_BOT_TOKEN_FILE`, bot token secret path.
- `C_<SVC>_ICLOUD_EMAIL_FILE`, iCloud email secret path.
- `C_<SVC>_ICLOUD_PASSWORD_FILE`, iCloud password secret path.

### Worker path defaults

- `/config` for auth state, manifest, session, and cookie data.
- `/output` for downloaded iCloud Drive files.
- `/logs` for worker logs and health heartbeat files.

## Run with Docker Compose

1. Copy `compose.yml.example` to `compose.yml` for local use.
2. Copy `.env.example` to `.env` and set host/service values.
3. Create secret files under `./secrets/`:
   `telegram_bot_token.txt`, `alice_icloud_email.txt`,
   `alice_icloud_password.txt`, `bob_icloud_email.txt`,
   `bob_icloud_password.txt`.
4. Build and run:

```bash
docker compose up -d --build
```

5. Check container and health status:

```bash
docker compose ps
docker inspect --format='{{json .State.Health}}' icloud_alice
docker inspect --format='{{json .State.Health}}' icloud_bob
```

## Runtime notes

- Compose `init: true` is required by the provided service definitions.
- Health checks require `microcheck`, bundled into the image build.
- Telegram commands are ignored unless they come from `H_TG_CHAT_ID`.

## Safety net behaviour

On first run only, each worker samples existing files in `/output` and checks
whether permissions are consistent.

If mismatches are found, backup is blocked. Details are written to worker logs
and sent via Telegram. This prevents destructive rewrites over existing backup
trees created with different ownership or mode patterns.
