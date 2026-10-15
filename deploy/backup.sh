#!/bin/sh
# Nightly at ~03:00 IST: database dump + bill photos into ./backups, keeping KEEP_DAYS days.
set -eu
backup() {
  ts=$(date +%Y%m%d-%H%M)
  pg_dump -Fc -h db -U ohd ohd > "/backups/db-$ts.dump.tmp" && mv "/backups/db-$ts.dump.tmp" "/backups/db-$ts.dump"
  tar -czf "/backups/uploads-$ts.tgz" -C /data uploads
  find /backups -type f \( -name 'db-*.dump' -o -name 'uploads-*.tgz' \) -mtime +"${KEEP_DAYS:-14}" -delete
  echo "backup $ts done"
}
backup   # one on start, so a fresh install is covered immediately
while true; do
  now=$(date +%s)
  next=$(date -d "$(date +%Y-%m-%d) 03:00" +%s 2>/dev/null || echo $((now + 86400)))
  [ "$next" -le "$now" ] && next=$((next + 86400))
  sleep $((next - now))
  backup
done
