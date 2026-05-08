# sardbot

Bot de trading em cripto, com rigor metodológico contra overfitting. Estado
atual: estratégia `donchian_breakout + SMA200 filter + 2×ATR stop`, validada
em walk-forward + OOS, em paper trading no Google Cloud.

## Documentação

- **[DEPLOY.md](DEPLOY.md)** — primeiro deploy (uma vez só)
- **[OPERATIONS.md](OPERATIONS.md)** — operação no dia a dia (consulta frequente)
- **[data/README.md](data/README.md)** — convenção de in-sample / out-of-sample
- **[.claude/skills/develop-trading-strategy/SKILL.md](.claude/skills/develop-trading-strategy/SKILL.md)**
  — metodologia condensada pra desenvolver novas estratégias

## Quickstart local

```bash
uv sync
uv run pytest                                   # 53 testes
uv run sardbot fetch                            # baixar OHLCV BTC/USDT
uv run sardbot backtest                         # backtest in-sample
uv run sardbot walkforward                      # análise de janelas
SARDBOT_STORAGE=local:data/paper \
  uv run sardbot paper-trade                    # simular um run de paper trade
SARDBOT_STORAGE=local:data/paper \
  uv run sardbot status                         # ver estado paper-trade
```

## Princípios

1. **Custo realista**: taxas (10 bps) + slippage (5 bps) descontados.
2. **Sem look-ahead**: sinal em t executa em t+1. Testado.
3. **Out-of-sample reservado**: últimos 20% intocados durante desenvolvimento.
4. **Comparação contra benchmarks**: todo backtest mostra B&H e DCA junto.
5. **Parâmetros canônicos**: nada de grid search. Donchian 20/10, SMA200, 2×ATR.
6. **Ajustes só principiados**: vindos da literatura, não dos números.
7. **Walk-forward antes de OOS**: estabilidade entre janelas conta mais que
   média de 7 anos.

## Estrutura do código

```
src/sardbot/
├── data/               # download e cache de OHLCV (ccxt)
├── strategies/         # Strategy ABC + sma_crossover + donchian + benchmarks
├── indicators/         # ATR
├── engine/             # backtester, costs, dca, walkforward, portfolio
├── metrics/            # CAGR, Sharpe, max DD, win rate
├── reporting/          # compare, tearsheet
├── risk/               # position sizing
├── paper/              # state, storage (local + GCS), notifier (Telegram), trader
└── cli.py              # `sardbot {fetch,backtest,walkforward,paper-trade,status}`
```

## Status atual (paper trading)

- Strategy: `donchian_breakout` (20/10) + filtro SMA(200) + stop 2×ATR(14)
- Symbol: BTC/USDT (Binance)
- Capital fictício: $10.000
- Frequency: 1 candle/dia (00:05 UTC)
- Hosting:
  - **Cloud Run Job** `sardbot-paper-trade` (executa estratégia 1x/dia)
  - **Cloud Run Service** `sardbot-webhook` (responde comandos do Telegram)
- Região: `southamerica-east1` (necessário pra acessar Binance — IPs US são bloqueados)
- Notificações: Telegram bot (one-way)
- Comandos via Telegram: `/status`, `/equity`, `/trades`, `/why`, `/help`
- Kill switch: drawdown ≤ -25% em relação ao pico
