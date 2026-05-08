# Operação do sardbot — guia do dia a dia

Manual prático com comandos copia-e-cola pra operar o bot já deployado.
Pra setup inicial (primeira vez que você está subindo), veja [DEPLOY.md](DEPLOY.md).

## Configuração

Os comandos abaixo usam variáveis shell. Defina-as uma vez antes de copiar/colar:

```bash
export PROJECT_ID=seu-project-id          # ex: sardbot-meunome-prod
export REGION=southamerica-east1          # região onde o deploy foi feito
export BUCKET=${PROJECT_ID}-sardbot-state
export JOB=sardbot-paper-trade            # Cloud Run Job (cron diário)
export SCHEDULER=sardbot-paper-trade-daily
export WEBHOOK=sardbot-webhook            # Cloud Run Service (responde Telegram)
export IMAGE=${REGION}-docker.pkg.dev/${PROJECT_ID}/sardbot/sardbot:latest
```

`SCHEDULE = 5 0 * * * Etc/UTC` (00:05 UTC = ~21:05 BRT)

## Comandos do Telegram

Mande pro bot no Telegram:

- `/status` — posição atual, equity, drawdown, último bar processado
- `/equity` — equity vs initial, high water, PnL, mudança 7 runs
- `/trades` — últimos 5 trades (entry/exit) com PnL
- `/why` — explica por que estou flat/long agora (mostra valores de Donchian, SMA200, ATR)
- `/help` — lista de comandos

Comandos administrativos (pause, resume, reset) ficam **fora do Telegram** por
segurança — use os gcloud commands na seção apropriada.

---

## 1. Cheat sheet — comandos mais comuns

```bash
# Ver estado atual
gcloud storage cat gs://${BUCKET}/state.json | python3 -m json.tool

# Forçar run manual
gcloud run jobs execute ${JOB} --region=${REGION}

# Ver logs da última execução
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=${JOB}" \
  --limit=20 --format="value(textPayload)" --order="desc"

# Pausar bot
gcloud scheduler jobs pause ${SCHEDULER} --location=${REGION}

# Resumir bot
gcloud scheduler jobs resume ${SCHEDULER} --location=${REGION}
```

---

## 2. Operações diárias / verificação

### Ver estado atual

```bash
gcloud storage cat gs://${BUCKET}/state.json | python3 -m json.tool
```

Campos importantes:
- `last_processed_bar` — último candle processado (deve ser de hoje ou ontem)
- `last_run` — timestamp da última execução
- `position.is_long` — `true` se está comprado em BTC
- `position.entry_price` / `entry_time` — quando entrou
- `position.stop_level` — onde sai por stop-loss
- `equity.current` — patrimônio atual em USD
- `equity.high_watermark` — pico de patrimônio
- `last_signal` — sinal mais recente (0 = flat, 1 = long)
- `stopped_out_cooldown` — `true` se está esperando sinal voltar a 0 antes de re-entrar

### Verificar se o run automático aconteceu hoje

```bash
gcloud storage cat gs://${BUCKET}/state.json | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print(f'last_run: {d[\"last_run\"]}')"
```

Se `last_run` não for de hoje, ou o scheduler não disparou ou o run falhou.
Veja seção 4 (logs) pra investigar.

### Ver histórico de trades

```bash
gcloud storage cp gs://${BUCKET}/trades.parquet /tmp/trades.parquet 2>/dev/null && \
python3 -c "
import pandas as pd
df = pd.read_parquet('/tmp/trades.parquet')
print(df.to_string(index=False))
print(f'\\n{len(df)} trades total')
"
```

Se o arquivo não existir, é porque ainda não houve nenhum trade (bot está flat
desde o início). Normal nas primeiras semanas.

### Ver curva de equity

```bash
gcloud storage cp gs://${BUCKET}/equity.parquet /tmp/equity.parquet && \
python3 -c "
import pandas as pd
df = pd.read_parquet('/tmp/equity.parquet')
print(df.tail(20).to_string(index=False))
"
```

### Forçar run manual (não espera scheduler)

Útil pra testar mudanças, debugar, ou conferir que o bot ainda funciona:

```bash
gcloud run jobs execute ${JOB} --region=${REGION} --wait
```

`--wait` faz a CLI esperar até o job terminar (~15-30 segundos).
Sem `--wait`, dispara e retorna imediatamente.

---

## 3. Pausar / Resumir o bot

### Pausar (parar runs automáticos)

```bash
gcloud scheduler jobs pause ${SCHEDULER} --location=${REGION}
```

O scheduler para de disparar. Estado preservado, retomada limpa.

### Resumir

```bash
gcloud scheduler jobs resume ${SCHEDULER} --location=${REGION}
```

### Verificar status do scheduler

```bash
gcloud scheduler jobs describe ${SCHEDULER} --location=${REGION} \
  --format="value(state,schedule,lastAttemptTime)"
```

`state` deve ser `ENABLED` (rodando) ou `PAUSED`.

---

## 4. Logs e debugging

### Logs da última execução

```bash
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=${JOB}" \
  --limit=20 --format="value(textPayload)" --order="desc"
```

### Logs de uma execução específica

```bash
# Listar execuções recentes
gcloud run jobs executions list --job=${JOB} --region=${REGION} --limit=5

# Pegar logs de uma execução específica (pelo nome)
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=${JOB} AND labels.\"run.googleapis.com/execution_name\"=NOME-DA-EXECUCAO" \
  --limit=50 --format="value(textPayload)" --order="asc"
```

### Logs de erro apenas

```bash
gcloud logging read "resource.type=cloud_run_job AND severity>=ERROR" \
  --limit=20 --format="value(textPayload,timestamp)" --order="desc"
```

### Ver no console (interface gráfica)

`https://console.cloud.google.com/run/jobs/details/<REGION>/<JOB>/executions?project=<PROJECT_ID>`

Substitua `<REGION>`, `<JOB>` e `<PROJECT_ID>` pelos seus valores antes de abrir.

---

## 5. Atualizar código / estratégia

Workflow padrão pra deploy de mudanças:

```bash
# 1. Mexer no código localmente, rodar testes
uv run pytest

# 2. Build da imagem (--platform=linux/amd64 obrigatório no Mac M1/M2)
docker build --platform=linux/amd64 -t sardbot:latest .

# 3. Tag e push pro Artifact Registry
docker tag sardbot:latest \
  ${IMAGE}
docker push \
  ${IMAGE}

# 4. Forçar Cloud Run Job a usar a nova imagem
#    (o job aponta pra ":latest" mas precisa update pra criar nova revisão)
gcloud run jobs update ${JOB} --region=${REGION} \
  --image=${IMAGE}

# 5. Testar com run manual antes de deixar o scheduler
gcloud run jobs execute ${JOB} --region=${REGION} --wait

# 6. Verificar logs e estado
gcloud storage cat gs://${BUCKET}/state.json | python3 -m json.tool
```

### Atualizações que mudam infra (não só código)

Se você mexer em `terraform/main.tf` (ex: mudou parâmetros do scheduler, adicionou
recursos), tem que aplicar com terraform:

```bash
cd terraform
terraform plan      # confere o que vai mudar
terraform apply     # aplica
```

---

## 6. Resetar estado

⚠️ **Destrutivo**. Use só pra começar do zero (ex: mudou de estratégia
fundamentalmente, ou estado ficou corrompido).

```bash
# Backup primeiro
gcloud storage cp gs://${BUCKET}/state.json /tmp/state-backup-$(date +%Y%m%d).json
gcloud storage cp gs://${BUCKET}/trades.parquet /tmp/trades-backup-$(date +%Y%m%d).parquet 2>/dev/null
gcloud storage cp gs://${BUCKET}/equity.parquet /tmp/equity-backup-$(date +%Y%m%d).parquet 2>/dev/null

# Apagar arquivos (próximo run vai criar estado fresh)
gcloud storage rm gs://${BUCKET}/state.json
gcloud storage rm gs://${BUCKET}/trades.parquet 2>/dev/null
gcloud storage rm gs://${BUCKET}/equity.parquet 2>/dev/null

# Próximo run vai inicializar com $10k de capital, flat, signal 0
```

---

## 7. Telegram

### Re-registrar webhook (raro — só se URL mudar)

Se você destruir e recriar o Service, a URL muda e o Telegram fica chamando
endpoint antigo. Pra re-registrar:

```bash
TOKEN=$(gcloud secrets versions access latest --secret=sardbot-telegram-token)
SECRET=$(gcloud secrets versions access latest --secret=sardbot-webhook-secret)
URL=$(cd terraform && terraform output -raw webhook_url)/telegram

curl -s -X POST "https://api.telegram.org/bot${TOKEN}/setWebhook" \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"${URL}\",\"secret_token\":\"${SECRET}\",\"allowed_updates\":[\"message\"]}"
```

### Verificar status do webhook

```bash
TOKEN=$(gcloud secrets versions access latest --secret=sardbot-telegram-token)
curl -s "https://api.telegram.org/bot${TOKEN}/getWebhookInfo" | python3 -m json.tool
```

Campos importantes:
- `url` — deve apontar pro nosso Service
- `pending_update_count` — se > 0, há mensagens em fila não processadas
- `last_error_message` — se aparecer, há problema (ex: timeout, 500)

### Logs do webhook

```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=${WEBHOOK}" \
  --limit=20 --format="value(textPayload,timestamp)" --order="desc"
```

### Trocar token (rotacionar)

Recomendado periodicamente, ou se suspeitar de vazamento:

```bash
# 1. Em @BotFather no Telegram: /revoke → escolha o bot → recebe novo token
# 2. Atualizar secret no GCP
echo -n "NOVO_TOKEN_AQUI" | gcloud secrets versions add sardbot-telegram-token --data-file=-

# Cloud Run Job pega a versão "latest" automaticamente no próximo run.
# Pra forçar agora:
gcloud run jobs execute ${JOB} --region=${REGION}
```

### Trocar chat (mudar destinatário)

```bash
echo -n "NOVO_CHAT_ID" | gcloud secrets versions add sardbot-telegram-chat --data-file=-
```

### Testar Telegram manualmente

```bash
TOKEN=$(gcloud secrets versions access latest --secret=sardbot-telegram-token)
CHAT=$(gcloud secrets versions access latest --secret=sardbot-telegram-chat)
curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -H "Content-Type: application/json" \
  -d "{\"chat_id\":\"${CHAT}\",\"text\":\"teste manual\"}"
```

### Desabilitar notificações temporariamente

Não tem flag direto. Caminhos:
- Mute o bot no app do Telegram (mais simples)
- Ou apague o secret de chat — bot vai logar erro mas continuar funcionando
  (porque `NullNotifier` é fallback)

---

## 8. Custos

### Verificar gasto do mês

```bash
gcloud billing accounts list
gcloud alpha billing budgets list --billing-account=BILLING_ACCOUNT_ID 2>/dev/null
```

Ou no console: https://console.cloud.google.com/billing

### Esperado vs realidade

Free tier deve cobrir tudo. Se você vir > $5/mês, alguma coisa está errada:
- Imagens demais no Artifact Registry (limpe versões antigas)
- Logs gerando muito (improvável com 1 run/dia)
- Storage com muito dado (improvável — state.json é pequeno)

### Limpar imagens antigas do Artifact Registry

```bash
# Listar
gcloud artifacts docker images list \
  ${REGION}-docker.pkg.dev/${PROJECT_ID}/sardbot

# Deletar uma imagem específica (substitua DIGEST)
gcloud artifacts docker images delete \
  ${REGION}-docker.pkg.dev/${PROJECT_ID}/sardbot/sardbot@sha256:DIGEST \
  --delete-tags
```

---

## 9. Troubleshooting

### Bot não rodou hoje

1. Scheduler está habilitado?
   ```bash
   gcloud scheduler jobs describe ${SCHEDULER} --location=${REGION} --format="value(state)"
   ```
   Se `PAUSED`, retomar.

2. Última tentativa do scheduler:
   ```bash
   gcloud scheduler jobs describe ${SCHEDULER} --location=${REGION} --format="value(lastAttemptTime,status)"
   ```

3. Última execução do job:
   ```bash
   gcloud run jobs executions list --job=${JOB} --region=${REGION} --limit=3
   ```

### Job está falhando

```bash
# Ver logs do erro
gcloud logging read "resource.type=cloud_run_job AND severity>=ERROR" --limit=10 \
  --format="value(textPayload)" --order="desc"
```

Causas comuns:
- **Binance 451** — IP geo-blocked. Confirme que o job está em
  `southamerica-east1`, não em `us-*`.
- **Permission denied** em GCS / Secret Manager — service account perdeu permissão.
  Reaplicar Terraform (`terraform apply`) restaura.
- **State corrupted** — JSON inválido no bucket. Resete (seção 6).

### Telegram não chega

1. Bot tá ativo? Manda `/start` pelo Telegram.
2. Test manual (seção 7).
3. Se test manual funciona mas o bot não envia: verifique se realmente houve
   evento (entry/exit/stop). Bot só notifica em mudanças.

### Estado parece errado

Compare com run local:

```bash
SARDBOT_STORAGE=local:data/paper uv run sardbot status
```

(Local usa cache OHLCV separado, então o estado pode divergir levemente.)

---

## 10. Emergências

### "Quero parar o bot AGORA"

```bash
gcloud scheduler jobs pause ${SCHEDULER} --location=${REGION}
```

Próximo cron não dispara. Estado preservado.

### "O bot está em posição mas mercado tá feio, quero forçar saída"

Não tem botão de pânico embutido (proposital — você não deve estressar e sair
manualmente em paper trading; o ponto é simular comportamento real).

Se mesmo assim quiser, edite o estado:

```bash
gcloud storage cp gs://${BUCKET}/state.json /tmp/state.json
# Edite /tmp/state.json: position → todos os campos null/false/0
# E `last_processed_bar` → null pra forçar reprocessamento
gcloud storage cp /tmp/state.json gs://${BUCKET}/state.json
```

### "Kill switch acionado, e agora?"

Você recebeu um Telegram tipo `🚨 KILL SWITCH ... drawdown -25%`. O bot
**continua rodando** mas não entra em novas posições. Opções:

1. **Ignorar e deixar correr** — kill switch só impede *novas* entradas se
   estava flat; se está em posição, o stop-loss continua valendo.
2. **Investigar**: olhar trades recentes, comparar com walk-forward histórico
   (você esperava ~1/3 das janelas com drawdown). Se está dentro do esperado,
   é só ruído estatístico.
3. **Resetar** se você determinou que algo está mecanicamente errado
   (seção 6).

Atualmente o kill switch **não para o scheduler** — o bot continua rodando todo
dia, só não toma novas posições enquanto estiver no estado de kill switch.
Reset manual ou fix no código pra "destravar".

---

## 11. Destruir tudo

Se quiser desfazer o deploy completo:

```bash
cd terraform
terraform destroy
```

Vai destruir todos os recursos, incluindo o bucket. **Backup primeiro** se
quiser preservar histórico de trades:

```bash
gcloud storage cp -r gs://${BUCKET} /tmp/sardbot-final-backup
```

---

## 12. Referência rápida de URLs

- **Cloud Run Jobs**: https://console.cloud.google.com/run/jobs?project=${PROJECT_ID}
- **Cloud Scheduler**: https://console.cloud.google.com/cloudscheduler?project=${PROJECT_ID}
- **Storage bucket**: https://console.cloud.google.com/storage/browser/${BUCKET}?project=${PROJECT_ID}
- **Logs**: https://console.cloud.google.com/logs/query?project=${PROJECT_ID}
- **Secrets**: https://console.cloud.google.com/security/secret-manager?project=${PROJECT_ID}
- **Billing**: https://console.cloud.google.com/billing
