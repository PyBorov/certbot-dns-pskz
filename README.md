# certbot-dns-pskz

[![CI](https://github.com/PyBorov/certbot-dns-pskz/actions/workflows/ci.yml/badge.svg)](https://github.com/PyBorov/certbot-dns-pskz/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/certbot-dns-pskz.svg)](https://pypi.org/project/certbot-dns-pskz/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[EN README](https://github.com/PyBorov/certbot-dns-pskz/blob/main/README_EN.md)

Плагин-аутентификатор [Certbot](https://certbot.eff.org/) для DNS-провайдера
[ps.kz](https://ps.kz) — автоматизирует прохождение DNS-01 challenge (создание
и удаление TXT-записи `_acme-challenge`) через GraphQL API ps.kz, чтобы можно
было выпускать и автоматически продлевать wildcard- и обычные TLS-сертификаты
без ручного редактирования DNS-записей.

## Зачем это нужно

DNS-консоль ps.kz (`console.ps.kz/dns/graphql`) предоставляет GraphQL API, но
он нигде публично не задокументирован, а авторизация требует специфического
заголовка `X-User-Token` (а не более привычных схем вида
`Authorization: Bearer` или cookie-сессии, которые можно было бы ожидать от
типового Apollo Server). Этот плагин оборачивает данный API в стандартный
Certbot-аутентификатор.

## Требования

* Certbot >= 1.1.0
* Python 3.7+
* API-токен, созданный в консоли ps.kz для аккаунта, которому принадлежит
  нужная DNS-зона

## Установка

```bash
pip install certbot-dns-pskz
#Alma Linux 10 и может еще RHEL подобные:
pip uninstall certbot-dns-pskz -y # на случай если уже выолнили первую
pip install --prefix=/usr certbot-dns-pskz

```

Либо из исходников:

```bash
git clone https://github.com/PyBorov/certbot-dns-pskz.git
cd certbot-dns-pskz
pip install -e .
```

Проверь, что Certbot видит плагин:

```bash
certbot plugins --text | grep -A3 pskz
```

## Учётные данные

Создай INI-файл с твоим API-токеном ps.kz:

```ini
# /etc/letsencrypt/pskz/credentials.ini
dns_pskz_token = xxxxxxxxxxxxxxxx.accountid.userid
```

```bash
chmod 600 /etc/letsencrypt/pskz/credentials.ini
```

**Важно:** каждый API-токен ps.kz жёстко привязывается к одному конкретному
аккаунту в момент создания. Если твои зоны разбросаны по нескольким аккаунтам
ps.kz — понадобится отдельный токен (и отдельный запуск `certbot` / отдельный
credentials-файл) на каждый аккаунт.

## Использование

```bash
certbot certonly \
  --authenticator dns-pskz \
  --dns-pskz-credentials /etc/letsencrypt/pskz/credentials.ini \
  --dns-pskz-propagation-seconds 60 \
  -d example.kz -d '*.example.kz'
```

| Флаг | Описание | По умолчанию |
|---|---|---|
| `--dns-pskz-credentials` | Путь к INI-файлу с учётными данными | *(обязателен)* |
| `--dns-pskz-propagation-seconds` | Сколько секунд ждать распространения DNS перед тем, как попросить CA проверить запись | `60` |

Продление работает как у любого другого плагина Certbot — вызов выше
(вместе с этими флагами) сохраняется в
`/etc/letsencrypt/renewal/<cert-name>.conf` и автоматически переиспользуется
при `certbot renew`.

## Как определяется зона

Плагин находит нужную DNS-зону для домена, запрашивая
`dns.zones(searchName: ...)` и последовательно поднимаясь вверх по уровням
домена, пока не найдёт точное совпадение среди зон, доступных токену —
например, для `wiki.example.kz` он пробует по порядку `wiki.example.kz`,
затем `example.kz`, затем `kz`, и использует первое точное совпадение. Это
значит, что плагин корректно работает и с поддоменами, не требуя заранее
указывать имя зоны.

## Подключение вместе с другими сервисами (например, GitLab Omnibus)

DNS-01-плагины Certbot занимаются только валидацией домена — они не
устанавливают сертификат никуда. Для сервисов вроде GitLab Omnibus, которые
ждут сертификат в конкретном месте, используй `--deploy-hook` /
`--renew-hook`, чтобы скопировать выпущенный сертификат и перезапустить
нужный сервис, например:

```bash
certbot certonly \
  --authenticator dns-pskz \
  --dns-pskz-credentials /etc/letsencrypt/pskz/credentials.ini \
  --renew-hook "/etc/letsencrypt/pskz/gitlab-deploy.sh" \
  -d gitlab.example.kz -d registry.gitlab.example.kz \
  --cert-name gitlab.example.kz
```

## Предыстория: недокументированный API

ps.kz не публикует документацию по API DNS-консоли. Этот плагин появился
благодаря тому, что схема была восстановлена через GraphQL-интроспекцию
эндпоинта `console.ps.kz/dns/graphql`, а правильный заголовок авторизации
(`X-User-Token`, а не схема `Authorization: Bearer`, которую можно было бы
предположить исходя из формата токенов `secret.accountId.userId`) был найден
методом проб и ошибок по официальной документации Cloud API ps.kz.

Две вещи, которые стоит знать, если будешь дебажить это сам, либо если ps.kz
что-то поменяет на своей стороне без предупреждения:

- **Токены жёстко привязаны к одному аккаунту в момент создания.** Сегмент
  `accountId` в строке токена — чисто косметический: подмена его на другой
  ID не меняет, к какому аккаунту резолвится токен. Если твои домены
  разбросаны по нескольким аккаунтам ps.kz — нужен отдельный токен (и
  отдельный вызов `certonly`/`renew`) на каждый аккаунт.
- **Имена зон возвращаются с точкой на конце** (например, `example.kz.`) —
  как в стандартной DNS FQDN-нотации. Плагин обрезает точку для сравнения,
  но всегда отправляет в API имя зоны ровно в том виде, в котором оно было
  получено.

Если ps.kz когда-нибудь опубликует официальный API или изменит эту схему —
пожалуйста, заведи issue.

## Тестирование

Тесты полностью мокают HTTP-слой — ни один реальный запрос к API не
выполняется, и для запуска тестов не нужны никакие учётные данные.

```bash
pip install -e ".[test]"
pytest -v
```

## Лицензия

MIT — см. [LICENSE](LICENSE).
