# Установка ps.kz DNS-плагина в Proxmox VE

Proxmox VE не использует Certbot — у него собственный встроенный ACME-клиент
(`pvenode acme`), который реализует **тот же интерфейс DNS-плагинов, что и
acme.sh** (шелл-функции `dns_<name>_add` / `dns_<name>_rm`), а не Python-плагины
Certbot. Поэтому для Proxmox нужен отдельный shell-скрипт — `dns_pskz.sh` в этой
папке. Логика поиска зоны (обход `wiki.example.kz` → `example.kz` → `kz`) в нём
идентична Python-плагину `certbot-dns-pskz`.

## 1. Установка скрипта

```bash
sudo cp dns_pskz.sh /usr/share/proxmox-acme/dnsapi/dns_pskz.sh
sudo chmod 755 /usr/share/proxmox-acme/dnsapi/dns_pskz.sh
```

Требуется `jq` на самом узле Proxmox:

```bash
sudo apt-get update && sudo apt-get install -y jq
```

## 2. Регистрация плагина в схеме Proxmox

Proxmox проверяет доступные API по списку в
`/usr/share/proxmox-acme/dns-challenge-schema.json`. Добавь туда `pskz`:

```bash
sudo cp /usr/share/proxmox-acme/dns-challenge-schema.json \
        /usr/share/proxmox-acme/dns-challenge-schema.json.bak

sudo jq '. + {"pskz": {}}' \
  /usr/share/proxmox-acme/dns-challenge-schema.json.bak \
  | sudo tee /usr/share/proxmox-acme/dns-challenge-schema.json > /dev/null

sudo systemctl restart pveproxy
```

**Важно:** этот файл — часть пакета `proxmox-acme` и может быть перезаписан
при обновлении пакета (`apt upgrade`). После каждого обновления `proxmox-acme`
проверяй, что запись `"pskz": {}` всё ещё на месте, и повторяй шаг при
необходимости. Резервная копия (`.bak`) остаётся рядом на этот случай.

## 3. Создание credentials-файла

```bash
cat > /etc/pve/priv/pskz.env << 'EOF'
PSKZ_Token=xxxxxxxxxxxxxxxx.accountid.userid
EOF
chmod 600 /etc/pve/priv/pskz.env
```

(Каждый токен ps.kz привязан к одному аккаунту — если зоны разбросаны по
нескольким аккаунтам, потребуется отдельный плагин/файл на каждый.)

## 4. Регистрация ACME-аккаунта (если ещё не сделано)

```bash
pvenode acme account register default admins@example.kz
```

## 5. Добавление DNS-плагина

```bash
pvenode acme plugin add dns pskz --api pskz --data /etc/pve/priv/pskz.env
```

## 6. Привязка домена к узлу и заказ сертификата

```bash
pvenode config set --acmedomain0 proxmox.example.kz,plugin=pskz
pvenode acme cert order
```

Или через веб-интерфейс: **Datacenter → узел → System → Certificates → ACME**
— там же появится плагин `pskz` в выпадающем списке после шага 5.

## Диагностика

Если `pvenode acme cert order` падает на этапе DNS-валидации — прогони
скрипт вручную с теми же аргументами, что использует Proxmox:

```bash
export PSKZ_Token="xxxxxxxxxxxxxxxx.accountid.userid"
source /usr/share/proxmox-acme/dnsapi/dns_pskz.sh
dns_pskz_add "_acme-challenge.proxmox.example.kz" "test-value-123"
# проверь, что TXT-запись появилась в консоли ps.kz, затем:
dns_pskz_rm "_acme-challenge.proxmox.example.kz" "test-value-123"
```

Скрипт пишет диагностику (`Resolved ps.kz zone: ...`) в stderr — она попадёт
в вывод задачи `pvenode acme cert order` или в журнал `pveproxy`/`task log`
в веб-интерфейсе.

## Бонус: renewal-hook для Proxmox Backup Server + рассылка fingerprint

Если сертификат выпускается для отдельного хоста **Proxmox Backup Server**
(не для PVE через `pvenode acme` — на PBS нет такого встроенного клиента,
там сертификат ставится либо через certbot напрямую с нашим `dns-pskz`
Python-плагином, либо руками), `proxmox/pbs-deploy.sh` автоматизирует
остальное:

1. Копирует `fullchain.pem`/`privkey.pem` в `/etc/proxmox-backup/proxy.pem`
   и `proxy.key`.
2. `systemctl reload proxmox-backup-proxy`.
3. Достаёт новый TLS-fingerprint через
   `proxmox-backup-manager cert info`.
4. Рассылает его по всем PVE-нодам из `pbs-storage-hosts.txt` командой
   `pvesm set <storage-id> --fingerprint <fingerprint>` по SSH — так PVE
   продолжит доверять PBS-сторажу после смены сертификата, не считая его
   протухшим/недоверенным.

### Установка

```bash
sudo mkdir -p /etc/letsencrypt/pskz
sudo cp proxmox/pbs-deploy.sh /etc/letsencrypt/pskz/pbs-deploy.sh
sudo chmod 700 /etc/letsencrypt/pskz/pbs-deploy.sh

sudo cp proxmox/pbs-storage-hosts.txt.example /etc/letsencrypt/pskz/pbs-storage-hosts.txt
sudo "$EDITOR" /etc/letsencrypt/pskz/pbs-storage-hosts.txt   # впиши свои 10 хостов
```

**Требование:** passwordless SSH по ключу с хоста PBS на все перечисленные
PVE-ноды под `root` (`ssh-copy-id root@pveN` для каждой, либо раскатать
публичный ключ через уже имеющуюся у тебя инфраструктуру Samba AD/Ansible).

### Выпуск сертификата с этим hook'ом

```bash
sudo certbot certonly \
  --authenticator dns-pskz \
  --dns-pskz-credentials /etc/letsencrypt/pskz/credentials.ini \
  --renew-hook "/etc/letsencrypt/pskz/pbs-deploy.sh" \
  --agree-tos -n \
  -m admins@example.kz \
  -d backup.example.kz \
  --cert-name backup.example.kz
```

`--renew-hook` не срабатывает при первом `certonly` (только при
последующих `renew`) — поэтому сразу после первого выпуска прогони
скрипт руками, эмулируя переменную, которую обычно подставляет certbot:

```bash
export RENEWED_LINEAGE="/etc/letsencrypt/live/backup.example.kz"
sudo -E bash -x /etc/letsencrypt/pskz/pbs-deploy.sh
```

### Проверка

```bash
sudo certbot renew --dry-run --cert-name backup.example.kz
proxmox-backup-manager cert info | grep Fingerprint
```

Скрипт продолжает обход всех хостов, даже если SSH до одного из них не
достучался — в конце вернёт ненулевой код выхода и список конкретных
проблемных хостов, но не остановит рассылку остальным 9 из-за одного
недоступного.
