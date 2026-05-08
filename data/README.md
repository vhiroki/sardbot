# Dados

`raw/` contém OHLCV (Open, High, Low, Close, Volume) baixado da exchange e
salvo em parquet. **Não é versionado** — pode ser regerado rodando
`uv run sardbot fetch`.

## Regra crítica: out-of-sample

Os últimos **20%** do dataset (últimos meses) são **out-of-sample (OOS)**. Eles
existem pra avaliar a estratégia *uma única vez*, no final, depois que ela
estiver finalizada.

**Não olhe para os resultados em OOS durante o desenvolvimento.** Se você
ajustar a estratégia depois de ver como ela performa em OOS, você
contaminou o teste — e perdeu sua única amostra independente.

A divisão é controlada por `backtest.oos_fraction` em `config/default.yaml`.
