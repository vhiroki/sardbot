# Deploy do sardbot no Google Cloud

Setup completo: Cloud Run Job + Cloud Scheduler + Cloud Storage + Telegram bot.

**Custo esperado**: $0–3/mês durante paper trading (free tier cobre quase tudo).

## Pré-requisitos

1. Conta GCP com billing habilitada (mesmo que use só free tier).
2. `gcloud` CLI instalado e autenticado: `gcloud auth login`.
3. `terraform` instalado: `brew install terraform`.
4. Docker rodando localmente (Docker Desktop ou Colima).
5. Bot Telegram criado (passo abaixo).

## 1. Criar bot Telegram

1. No Telegram, abra um chat com [@BotFather](https://t.me/BotFather).
2. Digite `/newbot`, escolha um nome (ex: `meu sardbot`) e username (ex: `vhiroki_sardbot_bot`).
3. Salve o **token** que ele te devolver — formato `123456789:ABC...`.
4. Para descobrir seu **chat ID**:
   - Mande qualquer mensagem pro bot que você acabou de criar.
   - Acesse `https://api.telegram.org/bot<SEU_TOKEN>/getUpdates`.
   - Procure `"chat":{"id":NUMERO,...}` na resposta. Esse é o seu chat ID.

## 2. Criar projeto GCP e habilitar billing

```bash
# Criar projeto (escolha um ID único globalmente, ex: sardbot-vhiroki-prod)
gcloud projects create sardbot-vhiroki-prod
gcloud config set project sardbot-vhiroki-prod

# Linkar conta de billing (substitua o ID; veja com `gcloud billing accounts list`)
gcloud billing projects link sardbot-vhiroki-prod \
  --billing-account=XXXXXX-XXXXXX-XXXXXX
```

## 3. Provisionar infra com Terraform

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Edite terraform.tfvars e preencha com seu project_id

terraform init
terraform plan
terraform apply
```

Outputs incluirão:
- `bucket_name` — onde o estado vai morar
- `image_repo` — Artifact Registry pra push da imagem
- `manual_run_command` — comando pra rodar o job manualmente

## 4. Setar secrets do Telegram

Use o secret manager via gcloud (mais simples que Terraform pra valores sensíveis):

```bash
echo -n "SEU_BOT_TOKEN_AQUI" | gcloud secrets versions add sardbot-telegram-token --data-file=-
echo -n "SEU_CHAT_ID_AQUI"   | gcloud secrets versions add sardbot-telegram-chat  --data-file=-
```

## 5. Build e push da imagem Docker

```bash
# De volta pra raiz do repo
cd ..

# Configura docker pra autenticar no Artifact Registry
gcloud auth configure-docker us-central1-docker.pkg.dev

# Build
docker build --platform=linux/amd64 -t sardbot:latest .

# Tag pro Artifact Registry (substitua PROJECT_ID)
docker tag sardbot:latest us-central1-docker.pkg.dev/PROJECT_ID/sardbot/sardbot:latest

# Push
docker push us-central1-docker.pkg.dev/PROJECT_ID/sardbot/sardbot:latest
```

## 6. Atualizar o Cloud Run Job pra apontar pra nova imagem

Já feito automaticamente pelo Terraform — o job aponta pra tag `latest`.
Se você fizer um deploy novo:

```bash
docker build --platform=linux/amd64 -t sardbot:latest .
docker tag sardbot:latest us-central1-docker.pkg.dev/PROJECT_ID/sardbot/sardbot:latest
docker push us-central1-docker.pkg.dev/PROJECT_ID/sardbot/sardbot:latest

# Forçar nova revisão (Cloud Run cacheia)
gcloud run jobs update sardbot-paper-trade --region=us-central1 \
  --image=us-central1-docker.pkg.dev/PROJECT_ID/sardbot/sardbot:latest
```

## 7. Testar manualmente

```bash
# Roda o job uma vez (não espera o scheduler)
gcloud run jobs execute sardbot-paper-trade --region=us-central1
```

Você deve receber uma mensagem no Telegram se houver evento (entrada/saída/stop). Se for o primeiro run e o sinal estiver flat, o estado é só inicializado e nenhuma notificação é enviada.

## 8. Verificar estado

```bash
# Baixar e ver o state.json atual
gsutil cat gs://PROJECT_ID-sardbot-state/state.json | jq
```

## 9. Logs

```bash
# Logs da última execução
gcloud run jobs executions list --job=sardbot-paper-trade --region=us-central1 --limit=5
gcloud logging read "resource.type=cloud_run_job" --limit=50 --format=json
```

Ou pelo console: https://console.cloud.google.com/run/jobs

## 10. O scheduler é automático

Roda todo dia às 00:05 UTC (~21:05 horário de Brasília). Não precisa fazer nada após o deploy inicial.

## Operação contínua

- **Status**: `gsutil cat gs://PROJECT_ID-sardbot-state/state.json | jq`
- **Histórico**: `gsutil cp gs://PROJECT_ID-sardbot-state/trades.parquet /tmp && python -c "import pandas as pd; print(pd.read_parquet('/tmp/trades.parquet'))"`
- **Pausar**: `gcloud scheduler jobs pause sardbot-paper-trade-daily --location=us-central1`
- **Resumir**: `gcloud scheduler jobs resume sardbot-paper-trade-daily --location=us-central1`

## Reduzir custo a zero

Se o paper trading durar > free tier:

- Cloud Storage: < 1MB de uso, deve ficar grátis
- Cloud Run: 1 execução/dia é desprezível, deve ficar grátis
- Cloud Scheduler: 1 job, free tier permite 3
- Artifact Registry: 0.5GB grátis, basta uma imagem de ~200MB
- Logging: free quota cobre execução diária

Single point of cost: storage do Artifact Registry se você acumular versões. Limpe periodicamente:

```bash
gcloud artifacts docker images list us-central1-docker.pkg.dev/PROJECT_ID/sardbot
gcloud artifacts docker images delete <DIGEST> --delete-tags
```

## Destruir tudo

```bash
cd terraform
terraform destroy
```
