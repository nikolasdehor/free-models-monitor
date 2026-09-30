# free-models-monitor

Monitora modelos de preço zero no OpenRouter e candidatos manuais legados da Groq, avisa quando um
modelo é adicionado ou removido, e sugere (ou aplica) uma troca de
fallback. Funciona sozinho via cron, ou como skill de qualquer harness de
agente.

## Instalação

```bash
pip install git+https://github.com/nikolasdehor/free-models-monitor.git
```

Ou direto do clone, sem instalar nada:

```bash
git clone https://github.com/nikolasdehor/free-models-monitor.git
cd free-models-monitor
python3 -m free_models_monitor.monitor --init
```

## Uso rápido

```bash
# Primeira execução: tira um snapshot, sem alertar
free-models-monitor --init

# Execuções seguintes: compara com o snapshot salvo
free-models-monitor
```

Códigos de saída: `0` sem mudança, `2` mudança detectada, `1` erro (rede,
config inválida).

## O que ele faz

- Busca o catálogo de modelos do OpenRouter (`/api/v1/models`) e mantém só
  os que têm preço zero em prompt e em completion.
- Inclui candidatos manuais legados da Groq com metadados de incerteza;
  esses candidatos não são sugeridos automaticamente como fallback.
- Compara com o último snapshot (`~/.free-models-monitor/snapshot.json` por
  padrão) e reporta adições e remoções.
- Mantém um histórico com limite de 200 entradas de cada mudança
  (`history.json`).
- Aplica uma lista de banimento (`banned.json`) para nunca sugerir modelos
  que você não quer usar.
- Sugere um fallback para um modelo removido, usando uma cadeia de
  preferência (`providers.py`, sobrescrevível com `--fallback-chain-file`)
  filtrada por contexto mínimo.
- Opcionalmente varre diretórios de configs de agentes (`--scan-dir`,
  repetível) para apontar quais configs referenciam um modelo removido.
- Opcionalmente notifica Telegram, Discord, Slack ou um webhook genérico,
  lendo credenciais só de variáveis de ambiente.

## Opções

| Flag | Padrão | Para que serve |
|---|---|---|
| `--state-dir` | `$FMM_STATE_DIR` ou `~/.free-models-monitor` | onde ficam snapshot, histórico e banlist |
| `--scan-dir DIR` (repetível) | nenhum | diretórios de configs de agentes para checar afetados |
| `--providers` | `openrouter,groq` | lista de providers separada por vírgula |
| `--format` | `text` | `text` (formato de chat, sem markdown) ou `json` |
| `--min-context` | `32768` | contexto mínimo para sugerir um fallback |
| `--notify` | `none` | `telegram`, `discord`, `slack`, `webhook` ou `none` |
| `--notify-always` | desligado | notifica mesmo sem mudança |
| `--init` | desligado | (re)grava o snapshot sem reportar mudança |
| `--fallback-chain-file` | nenhum | arquivo JSON que sobrescreve a ordem de preferência padrão |

## Configuração de notificação

Defina só as variáveis do canal que for usar:

| Canal | Variáveis de ambiente |
|---|---|
| `telegram` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| `discord` | `DISCORD_WEBHOOK_URL` |
| `slack` | `SLACK_WEBHOOK_URL` |
| `webhook` | `WEBHOOK_URL` (recebe `{"text": "..."}` via POST JSON) |

## Trocando um modelo em todo lugar que ele é usado

```bash
# Prévia
free-models-switch --from "openrouter/modelo-antigo:free" --to "openrouter/modelo-novo:free" --file agente1.json --file agente2.json --dry-run

# Aplica (faz backup de cada arquivo antes, como <arquivo>.bak-<timestamp>)
free-models-switch --from "openrouter/modelo-antigo:free" --auto --file agente1.json --apply
```

`--auto` escolhe a substituição pela cadeia de fallback usando o último
snapshot.

## Funciona com

- **OpenClaw**: [adapters/openclaw](adapters/openclaw), template de cron
  job e persona.
- **Hermes Agent**: [adapters/hermes](adapters/hermes), configuração de
  cron e skill.
- **Claude Code / Codex / OpenCode**: [adapters/claude-code](adapters/claude-code),
  usar o `SKILL.md` direto.
- **Cron puro, sem agente**: [adapters/cron](adapters/cron), entrada de
  `crontab` com `--notify`.

Todos eles chamam os mesmos dois comandos (`free-models-monitor`,
`free-models-switch`); os adapters só diferem em como agendam e como
entregam o relatório.

## Como skill de agente

O `SKILL.md` na raiz do repositório documenta como qualquer agente (não só
os harnesses acima) deve rodar o monitor, interpretar a saída e agir sobre
ela. Copie para o diretório de skills do seu harness, ou aponte seu harness
para este repositório.

## Desenvolvimento

```bash
ruff check .
python3 -m unittest discover -s tests -v
```

English: see [README.md](README.md).

## Licença

MIT, veja [LICENSE](LICENSE).

## Provider failures and catalog provenance

See [catalog reliability](docs/catalog-reliability.md) for partial failures, cache behavior, exit codes, JSON fields and Groq limits.
