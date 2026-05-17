# Operations

This is the day-to-day runbook: start it, check it, upgrade it, and know where
to look when something is not right.

For schedule setup, see [SCHEDULING.md](SCHEDULING.md). For Telegram commands,
see [TELEGRAM.md](TELEGRAM.md).

## Start the containers

Start the configured workers with Compose:

```bash
docker compose up -d
```

Check that the containers are running:

```bash
docker compose ps
```

The provided Compose examples use `init: true`. Leave that in place so worker
processes are reaped correctly inside the container.

## Check whether backups are running

Container health is based on the worker heartbeat file:

```text
/logs/pyiclodoc-drive-heartbeat.txt
```

The worker updates it every 30 seconds in scheduled mode and one-shot mode.

Use Docker health output for a quick check:

```bash
docker inspect --format='{{json .State.Health}}' icloud_drive_alice
```

`HEALTHCHECK_MAX_AGE_SECONDS` controls how old the heartbeat can be before the
worker or container health check treats it as stale. If unset, the default is
`65` seconds.

N.B.

Do not set `HEALTHCHECK_MAX_AGE_SECONDS` below `30`. That is shorter than the
heartbeat cadence and can make a healthy worker look unhealthy.

## Read the logs

The main worker log is:

```text
pyiclodoc-drive-worker.log
```

In the example setup it lives under the worker's logs directory, mounted at
`/logs` inside the container.

Useful lines to look for:

```text
Traversal finished.
Transfer finished.
Backup complete.
Transfer failure reason detail:
```

At `LOG_LEVEL=info`, the worker logs stage boundaries so you can see traversal,
transfer, and completion progress.

At `LOG_LEVEL=debug`, the worker logs more decisions, including auth attempts,
Telegram command handling, schedule checks, manual backup requests, safety-net
skips, traversal progress, transfer progress, and transfer failure reasons.

Debug logs show whether a Telegram command had arguments, but they do not log
MFA codes, passwords, bot tokens, or secret file contents.

Worker logs rotate daily and at the configured size threshold. Rotated logs are
compressed as:

```text
pyiclodoc-drive-worker.*.log.gz
```

## Trigger a manual backup

Send the worker a Telegram command:

```text
alice backup
```

The backup starts as soon as the worker can run it. The next scheduled run is
handled by the schedule mode:

- interval mode recalculates from the manual run time
- calendar modes stay pinned to the next calendar slot

## Upgrade the image

Pull the current code or update your Compose image tag, then recreate the
containers:

```bash
docker compose down
docker compose up -d
```

For a local source build:

```bash
docker compose up -d --build
```

After startup, check:

```bash
docker compose ps
```

Then watch for the normal run markers in the worker log:

```text
Traversal finished.
Transfer finished.
Backup complete.
```

## Run one backup and stop

Set one-shot mode for the worker:

```env
ALICE_RUN_ONCE=true
ALICE_RESTART_POLICY=no
```

The worker waits for Telegram `auth` or `reauth` if iCloud needs MFA, runs one
backup attempt, and exits.

Exit is non-zero when auth is incomplete, reauth is pending, or the first-run
safety net blocks backup.

N.B.

If the restart policy is `unless-stopped` or similar, Compose will restart the
container after it exits. That is nearly always the wrong pairing for one-shot
mode.

## Tune large backups

Incremental sync uses:

```text
/config/pyiclodoc-drive-manifest.json
```

Unchanged files are skipped. On first run with an empty manifest, the worker
checks existing local files under `/output` against remote size and modified
time, then seeds matching manifest entries without downloading those files
again.

The main tuning settings are:

- `SYNC_TRAVERSAL_WORKERS`: bounded parallel directory traversal
- `SYNC_DOWNLOAD_WORKERS`: changed-file download workers, or `auto`
- `SYNC_DOWNLOAD_CHUNK_MIB`: download stream chunk size

Leave these alone unless a real backup is too slow or you are testing a
specific performance change.

Long traversal is normal for large iCloud Drives. At `LOG_LEVEL=debug`, the
worker emits progress lines every 30 seconds during traversal and transfer so
you can tell the run is still moving.

## Use mirror delete

By default, local files are not deleted just because they disappear from iCloud.

Enable mirror delete with:

```env
ALICE_BACKUP_DELETE_REMOVED=true
```

When enabled, the worker prunes local files and empty directories under
`/output` when they no longer exist in iCloud.

Non-empty directories are skipped during cleanup. Other directory deletion
failures are counted and logged as real errors.

## Understand the safety net

On first run only, each worker samples existing files in `/output` and checks
UID and GID against the container runtime user.

If ownership does not match, backup is blocked. Details are written to worker
logs and sent via Telegram.

This is there for the boring but important case: running this over an existing
backup tree from another container. It is better to stop early than rewrite a
large backup with unexpected ownership.

Safety-net state lives in `/config`:

```text
pyiclodoc-drive-safety_net_done.flag
pyiclodoc-drive-safety_net_blocked.flag
```

## Troubleshooting

### The one-shot container keeps restarting

Set the worker restart policy to `no`:

```env
ALICE_RESTART_POLICY=no
```

Then recreate the container.

### Telegram commands are ignored

Check:

- `H_TGM_CHAT_ID` is set
- the command came from that exact chat
- the username matches `CONTAINER_USERNAME`
- the command uses one of the supported forms in [TELEGRAM.md](TELEGRAM.md)

### Authentication is stuck

If the worker restarted after iCloud issued a challenge, the in-memory
challenge may be gone. Send:

```text
alice auth
```

or:

```text
alice reauth
```

The worker should request a fresh challenge.

### Traversal takes a long time

That can be normal for a large iCloud Drive. Set debug logging if you need
progress evidence:

```env
C_LOG_LEVEL=debug
```

Then look for traversal progress and `Traversal finished.` in the worker log.

### Transfer errors are non-zero

Look for:

```text
Transfer failure reason detail:
```

That line groups the failure reasons from the run. It is usually more useful
than reading hundreds of per-file lines first.

### The safety net blocks backup

Read the Telegram message or worker log. It includes the expected UID and GID.

Fix the ownership mismatch or choose a clean output directory before trying
again.

## Runtime reference

Some implementation details are worth knowing, but they should not be the first
thing you have to read.

- The worker runtime is non-root.
- The entrypoint starts as root only to read Docker secret files, then drops to
  `PUID:PGID`.
- Services keep `cap_drop: ALL` and add only `SETUID` and `SETGID` so privilege
  drop works.
- If your Docker runtime blocks group switching with `setgroups`, startup can
  fail during privilege drop.
- Health checks run the bundled shell script through `sh` inside the worker
  image.
- If heartbeat writes fail from startup and no successful heartbeat is recorded
  within the health budget, the worker exits non-zero.
- Telegram notifications are skipped quietly when Telegram is not configured.
- If Telegram rejects a notification or the request fails, the worker logs the
  failure detail.
- Startup discards old queued Telegram updates once, then switches to live
  polling from the captured offset.
- Transfer workers report structured per-file outcomes back to sync
  aggregation, so retry counts and failure reasons stay tied to the right file.
- Transient transfer exceptions, such as throttling and 5xx responses, are
  retried with bounded backoff.
- Directory traversal also uses bounded retry and backoff for transient iCloud
  API failures.
- If a remote path changes between file and directory across runs, the worker
  replaces the conflicting local path and continues.
- Successful downloads preserve remote modified timestamps on local files.
- Keyring bootstrap sets an explicit keyring file path and XDG data path, but
  does not rewrite `HOME`.
- Stored keyring credentials are updated only after a successful iCloud login.
- Worker JSON state writes use a temporary file and atomic replace.
