# VPS runbook — server setup (phase 3) and backups (phase 4)

Target: Ubuntu 24.04 VPS at `193.124.115.214`, ~1 GB RAM. Rebuilding on another
machine? That IP appears throughout — substitute yours everywhere, including
the `deploy` job in [`ci.yml`](../.github/workflows/ci.yml).
Two keys are involved: your personal `~/.ssh/id_ed25519` for admin work, and a
separate `~/.ssh/ci_deploy` that only GitHub Actions uses (§8).
Run each block where indicated: **[home]** = your machine, **[vps]** = over SSH.

Reproducing the whole project from scratch: §0–§7 give a running server, §8
wires up automatic deploys, §9 the sensor, §10 backups.

## 0. Domain (DuckDNS)

1. Sign in at <https://www.duckdns.org> (GitHub/Google login).
2. Add a subdomain (say `<name>.duckdns.org`) and point it to `193.124.115.214`.
3. **[home]** verify: `dig +short <name>.duckdns.org` prints the IP.

*Why first:* Caddy asks Let's Encrypt for a certificate on first start; if DNS
doesn't resolve yet, it just loops on failed attempts. duckdns.org is on the
Public Suffix List, so your subdomain gets its own LE rate-limit bucket.
Swapping in a bought domain later is a one-line change of `DOMAIN` in `.env`.

## 1. Non-root user, SSH keys only

*Why:* password brute-forcing starts within minutes of a VPS going live; keys
kill that whole class of attacks. A separate user means no routine work as root.

**Shortcut for a fresh machine:** §1–5 are automated in
[`infra/cloud-init.yaml`](../infra/cloud-init.yaml) — paste it into the
provider's "user data" field when creating the VPS and skip straight to §6.
The manual steps below stay as documentation, and for servers already running
(cloud-init only fires on first boot).

```bash
# [home]
ssh root@193.124.115.214

# [vps, as root]
adduser deploy            # pick any strong password, it won't be used for SSH
usermod -aG sudo deploy
mkdir -p /home/deploy/.ssh
cp /root/.ssh/authorized_keys /home/deploy/.ssh/   # reuse the existing key
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh && chmod 600 /home/deploy/.ssh/authorized_keys

cat > /etc/ssh/sshd_config.d/90-hardening.conf <<'EOF'
PasswordAuthentication no
PermitRootLogin no
EOF
systemctl restart ssh
```

**Do not close this root session yet.** First, from a NEW terminal:

```bash
# [home]
ssh deploy@193.124.115.214   # must work with the key, no password prompt
```

Only after that succeeds, log out of the root session — it was your safety line.

## 2. Firewall

```bash
# [vps, as deploy]
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22,80,443/tcp
sudo ufw enable
```

*Why port 80 when everything is HTTPS:* Let's Encrypt's HTTP-01 challenge
arrives on 80, and Caddy redirects the rest to 443.

*Caveat to know:* Docker publishes ports by writing iptables rules directly,
bypassing ufw. That's fine here — only caddy publishes 80/443, which we allow
anyway — but never rely on ufw to block a port you've published in compose.

## 3. Automatic security updates

```bash
# [vps]
sudo apt update && sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades   # answer Yes
```

## 4. Swap

*Why:* the box has ~1 GB RAM; `docker build` next to a running Postgres can
hit OOM. 2 GB of swap costs nothing and removes the failure mode.

```bash
# [vps]
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 5. Docker (official repository)

*Why not `apt install docker.io` or snap:* Ubuntu's own packages lag behind
and split compose out awkwardly; the upstream repo ships current
`docker compose` as a plugin.

Follow <https://docs.docker.com/engine/install/ubuntu/> ("Install using the
apt repository", three blocks of commands), then:

```bash
# [vps]
sudo usermod -aG docker deploy   # membership in `docker` group == root on this box;
exit                             # that's why hardening came first. Re-login to apply.
```

## 6. Deploy the stack

```bash
# [vps, as deploy]
sudo mkdir -p /opt/weather-station && sudo chown deploy:deploy /opt/weather-station
git clone https://github.com/Shchurov-nk/weather-station.git /opt/weather-station
cd /opt/weather-station
cp .env.example .env
chmod 600 .env
nano .env   # DOMAIN=<name>.duckdns.org, real passwords,
            # SENSOR_TOKEN=$(openssl rand -hex 32)
# Pull, don't build: the api image comes from GHCR (published by CI on every
# push to main). Building here would take minutes and can OOM on 1 GB.
docker compose pull
docker compose up -d
docker compose ps          # all services Up, db healthy
docker compose logs caddy  # look for "certificate obtained successfully"
```

Acceptance:

```bash
# [home]
curl -i https://<name>.duckdns.org/sensor -X POST \
     -H 'Content-Type: application/json' -d '{}'
# expect: HTTP/2 401 — TLS works, token required
curl -i https://<name>.duckdns.org/sensor -X POST \
     -H "Authorization: Bearer <your SENSOR_TOKEN>" \
     -H 'Content-Type: application/json' \
     -d '{"temp": 21.5, "hum": 40, "pres": 995}'
# expect: HTTP/2 201; then https://<name>.duckdns.org/table shows the row
```

Updates later are not built here — CI publishes the image, the VPS pulls it:

```bash
# [vps, as deploy]
cd /opt/weather-station && git pull --ff-only && ./scripts/deploy.sh
```

That is exactly what the `deploy` job in CI runs over ssh after a push to main.
The GHCR package must be **public**, otherwise `pull` gets a 401.

Roll back to an older build (tags are `sha-<short>`, one per push to main —
see the packages page on GitHub):

```bash
# [vps, as deploy]
sed -i 's/^API_TAG=.*/API_TAG=sha-abc1234/' .env
docker compose pull api         # pull first: with a build: section, a missing
docker compose up -d api        # image would otherwise be BUILT on the VPS
```

## 7. External check (phase 3 acceptance)

```bash
# [home]
nmap -p 1-1000 193.124.115.214
# open: 22, 80, 443 — nothing else
```

## 8. Continuous deployment (GitHub Actions → VPS)

After this section, a push to `main` deploys itself: CI runs the tests, publishes
the image to GHCR, then runs `scripts/deploy.sh` here over SSH. One-time setup,
except where noted "per server".

**a. Make the GHCR package public.** `github.com/users/<you>/packages/container/
weather-station-api/settings` → Change visibility → Public. Otherwise the VPS
gets a 401 on pull, and the alternative is storing a PAT on the server — another
secret to rotate.

**b. A separate key for CI.** Never hand GitHub your personal key: a leaked CI
secret must not open everything that key opens.

```bash
# [home]
ssh-keygen -t ed25519 -f ~/.ssh/ci_deploy -C ci@weather-station -N ""
```

No passphrase on purpose — there is nobody to type it in CI. The protection is
that the key lives in a GitHub secret and is crippled server-side in the next step.

**c. Install it, restricted to one command** (per server):

```bash
# [home]
{ echo; printf 'command="cd /opt/weather-station && git pull --ff-only && ./scripts/deploy.sh",restrict '; cat ~/.ssh/ci_deploy.pub; } \
  | ssh deploy@193.124.115.214 'cat >> ~/.ssh/authorized_keys'
```

`command=` replaces whatever the client sends, `restrict` kills port/agent
forwarding and pty. *Why it matters:* `deploy` is in the `docker` group, which
is root on this box — unrestricted, this key would be a root shell in a CI
secret. Result: two lines in `authorized_keys`, your personal key plain and the
CI key prefixed. Do not leave an unprefixed copy of the CI key — SSH uses the
first matching line, so a plain duplicate silently defeats the restriction.

**d. Two repository secrets** (Settings → Secrets and variables → Actions):

| Secret | Value | Per server? |
|---|---|---|
| `VPS_SSH_KEY` | `cat ~/.ssh/ci_deploy` — the private half, `BEGIN`/`END` lines included | no |
| `VPS_KNOWN_HOSTS` | `ssh-keyscan -t ed25519 193.124.115.214` | **yes** — a new machine has a new host key |

`VPS_KNOWN_HOSTS` is what makes CI verify *which* server it is talking to;
without it the job would have to accept any host that answers on that IP, and a
MITM would collect the key. Verify before pasting — `ssh-keyscan` trusts
whoever replies:

```bash
# [home]
ssh-keygen -lf <(ssh-keyscan -t ed25519 193.124.115.214 2>/dev/null)
ssh-keygen -l -F 193.124.115.214    # what your machine recorded on first login
# the SHA256 fingerprints must match
```

**e. Acceptance.** Push anything to `main`; the `deploy` job turns green, and:

```bash
# [vps]
docker compose images api   # digest matches the newest package on GHCR
```

Note the trade-off you are accepting: a push to `main` reaches production in
about three minutes with no review. The smoke test in `deploy.sh` fails the job
if the site stops answering, and `API_TAG` (§6) rolls back to any `sha-<short>`
build. Branch protection with PR-only merges is the real fix when the project
stops being a single-person one.

## 9. Firmware bridge patch (data starts flowing)

> Done (2026-08-14) — implemented in `esp32/esp32.ino` + `esp32/certs.h`.
> The bundle pins four ISRG roots: X1 + X2 as planned below, plus the next-gen
> Root YE + YR (introduced 2025-09, already served in chains via cross-signs),
> so the device survives LE dropping the cross-signs later.

Minimal change so the ESP32 talks to the VPS over the public internet; the
full PlatformIO rework stays in phase 6. Three ideas:

- **TLS with a pinned root CA, not `setInsecure()`.** `setInsecure()` encrypts
  but doesn't check who the server is — an active MITM could collect the token.
  We embed the Let's Encrypt roots (ISRG Root X1 + X2, both PEMs concatenated —
  LE may serve either chain); leaf certs rotate every ~60–90 days but the roots
  are valid until 2035, so the firmware won't need touching.
- **NTP before the first request.** Certificate validation needs the current
  time; without it the handshake fails mysteriously.
- **Bearer token** in the `Authorization` header — same secret as `SENSOR_TOKEN`
  in `.env` on the VPS.

In `config.h` (copy from `config_example.h`):

```c
const char* ssid = "...";
const char* password = "...";
const char* serverURL = "https://<name>.duckdns.org/sensor";
const char* sensorToken = "<your SENSOR_TOKEN>";
```

Sketch changes:

```c
#include <WiFiClientSecure.h>
#include "certs.h"   // const char* LE_ROOTS = "-----BEGIN CERTIFICATE-----\n..." X1 + X2

// setup(), after WiFi connects: block until NTP sets the clock
configTime(0, 0, "pool.ntp.org");
while (time(nullptr) < 1000000000) delay(200);

// in printValues(): TLS client with pinned roots + token header
WiFiClientSecure client;
client.setCACert(LE_ROOTS);
HTTPClient http;
http.begin(client, serverURL);
http.addHeader("Content-Type", "application/json");
http.addHeader("Authorization", String("Bearer ") + sensorToken);
int httpCode = http.POST(jsonPayload);
```

Root PEMs: <https://letsencrypt.org/certificates/> — "ISRG Root X1" and
"ISRG Root X2", self-signed PEM versions.

Acceptance for the whole phase: a row from the real sensor appears in
`https://<name>.duckdns.org/table`. ✔ Passed 2026-08-14 — real readings arrive
every 60 s.

### 9.1 Flashing from the Linux CLI (how it was actually done)

Arduino IDE is not required; the whole cycle ran headless with `arduino-cli`.
The everyday cycle (compile → upload → serial monitor) is wrapped in
`scripts/flash.sh`; the one-time toolchain setup below is its prerequisite.
Reproducible steps on the workstation:

```bash
# [workstation]
curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh \
    | BINDIR=~/.local/bin sh
arduino-cli config init
arduino-cli config set board_manager.additional_urls \
    https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index && arduino-cli core install esp32:esp32
arduino-cli compile --fqbn esp32:esp32:esp32 esp32/
arduino-cli upload -p /dev/ttyUSB0 --fqbn esp32:esp32:esp32 esp32/
```

Snags hit on the way, and the workarounds:

- **`downloads.arduino.cc` returns 403 on this network** (blocked region/CDN;
  curl with a browser User-Agent gets 403 too). That server hosts the official
  library index and the "builtin" tools, so `lib install <name>` and parts of
  the build break. The ESP32 board index lives on `espressif.github.io` and
  works fine — the core itself installs normally.
- **Libraries** — install straight from git instead of the index:

  ```bash
  arduino-cli config set library.enable_unsafe_install true
  arduino-cli lib install --git-url \
      https://github.com/adafruit/Adafruit_Sensor.git \
      https://github.com/adafruit/Adafruit_BME280_Library.git \
      https://github.com/adafruit/Adafruit_BusIO.git \
      https://github.com/bblanchon/ArduinoJson.git
  ```

- **`ctags` (builtin tool) can't download** → build dies with
  `fork/exec {runtime.tools.ctags.path}/ctags: no such file`. Fetch it from
  the GitHub release and drop it where the CLI expects builtin tools:

  ```bash
  curl -fsSLO https://github.com/arduino/ctags/releases/download/5.8-arduino11/ctags-5.8-arduino11-x86_64-pc-linux-gnu.tar.bz2
  mkdir -p ~/.arduino15/packages/builtin/tools/ctags/5.8-arduino11
  tar xjf ctags-*.tar.bz2 -C ~/.arduino15/packages/builtin/tools/ctags/5.8-arduino11
  # note: the archive is flat (just the binary) — no --strip-components
  ```

  The `serial-discovery`/`mdns-discovery` warnings that remain are harmless:
  they only power `board list` auto-detection, and `upload -p /dev/ttyUSB0`
  names the port explicitly.
- **Serial port permissions**: the device shows up as `/dev/ttyUSB0` owned by
  `root:dialout`. Either `sudo usermod -aG dialout $USER` (permanent, needs
  re-login) or `sudo chmod a+rw /dev/ttyUSB0` (until re-plug).
- **Serial monitor without the IDE** (`arduino-cli monitor` needs another
  builtin tool — same 403): plain termios does the job:

  ```bash
  stty -F /dev/ttyUSB0 9600 raw -echo && cat /dev/ttyUSB0
  ```

### 9.2 Debugging a 401 from the device (what actually happened)

The first flash got `Response: 401, {"error":"unauthorized"}` — a useful
failure, because a JSON error from Flask proves WiFi, NTP, TLS and routing all
work; only the credential is wrong. The layer-by-layer isolation that found it:

1. **Same token, different client.** `curl` from the workstation with the
   token out of `config.h` → also 401. So the firmware is innocent; the
   *value* is wrong.
2. **Is the server checking what we think?** Env vars freeze when a container
   is *created*, not when `.env` changes — a stale container is the classic
   trap. Compare without exposing secrets, by hash:

   ```bash
   # [vps]
   docker compose exec api printenv SENSOR_TOKEN | tr -d '\n' | sha256sum
   grep -oP '^SENSOR_TOKEN=\K.*' .env        | tr -d '\n' | sha256sum
   # differ → docker compose up -d --force-recreate api
   ```

3. **Is the code broken?** Ran the exact prod image from GHCR locally with a
   known token: 401 without it, auth passes with it. Code cleared.
4. **What's left must be the answer**: the token pasted into `config.h` was a
   *different* (valid-looking, 64-hex) token — a manual-copy casualty. Fix
   that removes the human from the loop:

   ```bash
   # [workstation]
   ssh deploy@<vps> 'grep -oP "^SENSOR_TOKEN=\K.*" /opt/weather-station/.env' \
     | xargs -I{} sed -i 's|sensorToken = ".*"|sensorToken = "{}"|' esp32/config.h
   ```

Takeaways: an error *message* is information (401-in-JSON ≠ TLS failure);
compare secrets by hash, never by eyeball; when two ends must share a secret,
script the transfer.

## 10. Backups (phase 4)

`scripts/backup.sh` is in the repo. On the VPS:

```bash
# [vps]
crontab -e
# add:
10 2 * * * /opt/weather-station/scripts/backup.sh >> /home/deploy/backup.log 2>&1
```

Then register a check at <https://healthchecks.io> (free) and put its ping URL
into the last line of `backup.sh`. *Why:* a backup job that silently stopped
is worse than no backup — you find out during a disaster.

**Off-VPS copy is a pull, not a push.** From home (laptop/desktop, cron or
manually):

```bash
# [home]
rsync -a deploy@193.124.115.214:/opt/weather-station/backups/ ~/ws-backups/
```

*Why pull:* a compromised VPS must not hold keys to anything else you own.
If the home machine isn't reliably on, the alternative is `rclone` from the
VPS to object storage (Backblaze B2 / S3).

**Restore test — the actual acceptance.** A backup is a hypothesis until
restored once:

```bash
# [home or vps]
docker run --rm -d --name restore-test -e POSTGRES_PASSWORD=x postgres:17
docker cp ~/ws-backups/ws_<date>.dump restore-test:/tmp/
docker exec restore-test createdb -U postgres ws
docker exec restore-test pg_restore -U postgres -d ws /tmp/ws_<date>.dump
docker exec restore-test psql -U postgres -d ws \
    -c 'SELECT count(*), max(reading_time) FROM sensor_readings'
# numbers match production? done. Repeat quarterly.
docker stop restore-test
```

Bonus: this same dump/restore pair is the upgrade path between Postgres major
versions (17 → 18), whose data volumes are not compatible.
