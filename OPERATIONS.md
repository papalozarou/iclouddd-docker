# Operations

## Runtime notes

- Compose `init: true` is required by the provided service definitions.
- Health checks use `microcheck` (bundled in the image).
- Telegram commands are ignored unless they come from `H_TGM_CHAT_ID`.

## Scheduling modes

### `interval` mode

Runs backup every `<SVC>_BACKUP_INTERVAL_MINUTES`.

### `daily_time` mode

Runs backup at `<SVC>_BACKUP_DAILY_TIME` local time each day.

### `weekly` mode

Runs backup on `<SVC>_SCHEDULE_WEEKDAY` at `<SVC>_BACKUP_DAILY_TIME`.

### `twice_weekly` mode

Runs backup on the two days in `<SVC>_SCHEDULE_WEEKDAYS` at
`<SVC>_BACKUP_DAILY_TIME`.

### `monthly` mode

Runs backup on the `<SVC>_SCHEDULE_MONTHLY_WEEK` `<SVC>_SCHEDULE_WEEKDAY` of
the month at `<SVC>_BACKUP_DAILY_TIME` (for example: `first monday`).

## Manual backup command behaviour

If a user sends `<username> backup`, backup runs immediately.

After that run:

- in `interval` mode, the next scheduled run is recalculated from command run
  time;
- in all calendar-based modes (`daily_time`, `weekly`, `twice_weekly`,
  `monthly`), the next scheduled run stays pinned to the next valid calendar
  slot for that mode.

## One-shot mode

- Enable with `<SVC>_RUN_ONCE=true`.
- Recommended with `restart: "no"` to avoid automatic restarts.
- Worker exits after one backup attempt.
- Exit is non-zero when auth is incomplete, reauth is pending, or first-run
  safety net blocks backup.

## Transfer performance

- Incremental sync uses `manifest.json` and skips unchanged files.
- Changed-file downloads run in parallel automatically based on host CPU.
- Worker count is internally bounded to `1..8`.
- No extra tuning variables are required.

## Safety-net behaviour

On first run only, each worker samples existing files in `/output` and checks
permissions for consistency.

If mismatches are found, backup is blocked. Details are written to worker logs
and sent via Telegram. This is intended to avoid destructive rewrites over
existing backup trees with mixed ownership/modes.
