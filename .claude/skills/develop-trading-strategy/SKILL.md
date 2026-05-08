---
name: develop-trading-strategy
description: Guia o desenvolvimento metódico de uma estratégia de trading quantitativa em dados históricos (cripto, ações). Use quando o usuário quiser projetar, fazer backtest, ajustar ou validar uma estratégia. Impõe rigor anti-overfitting: reserva de out-of-sample, walk-forward analysis, parâmetros canônicos, critérios pré-comprometidos. NÃO invocar para estratégias já em produção, configuração de paper trading, ou perguntas finance gerais sem contexto de estratégia própria.
---

# Desenvolver uma estratégia de trading com método

Esta skill condensa a metodologia para evitar os erros clássicos de quem
constrói bots de trading: overfitting silencioso, post-hoc selection,
expectativas infladas e auto-engano com backtests.

A premissa central: **cada vez que você ajusta uma regra depois de olhar
os números, você está aprendendo a passar nesse backtest específico, não
a generalizar pro futuro.** A skill enforca disciplina contra esse impulso.

## Fase 0 — Alinhamento antes de qualquer código

Antes de escrever uma linha, alinhe com o usuário (use AskUserQuestion):

1. **Objetivo real**: aprendizado, lucro modesto consistente, ou retorno alto
   com risco? "Aprender" muda tudo. "Lucro modesto" precisa de comparação
   honesta com renda fixa (CDI ~12% a.a. é o piso). "Retorno alto" é
   estatisticamente improvável; calibre expectativas pra baixo.
2. **Mercado**: cripto (APIs grátis, 24/7, mais simples) vs ações (corretora,
   horário pregão, tributação complexa). Recomendar cripto pra projetos de
   aprendizado.
3. **Horizonte**: day trade (estatisticamente o pior pra varejo, custos comem
   tudo), swing (dias-semanas), posição (semanas-meses, mais robusto).
4. **Capital**: se > R$50k, alertar fortemente sobre não alocar em bot iniciante.
5. **Stack**: Python + uv + ccxt + pandas é o caminho default.

Documente as respostas. Volte a elas quando o usuário tentar mudar de objetivo
no meio (acontece — "lucro modesto" vira "quero ganhar mais").

## As verdades que você precisa explicar logo

Antes de qualquer prototipagem, deixe explícito (e referencie depois quando
o usuário quiser pular):

- **Overfitting** (curve fitting): ajustar regras aos dados específicos.
  Quanto mais você otimiza no passado, menos generaliza pro futuro.
- **Regime change**: mercados mudam. Backtest de N anos não captura
  mudanças regulatórias, macro, narrativas.
- **Alpha decay**: edges públicos somem quando descobertos. Se fosse fácil,
  fundos com PhD e bilhões já teriam explorado.
- **Left-tail risk**: estratégia pode "funcionar" 5 anos e perder tudo numa
  semana de evento raro. Critérios de invalidação por tempo (ex: "perdeu 3
  semanas seguidas") não capturam isso.
- **Custos** (fee + slippage): ~15 bps por lado em cripto spot é realista.
  Estratégias HFT morrem aqui.

## Fase 1 — Backtester + UMA estratégia simples

**Constraints duras**:

- **UMA** estratégia, escolhida pela fama na literatura (não por testes).
  Default: SMA crossover 50/200 ("Golden Cross") em barras diárias. Se o
  usuário quiser outra, use Donchian 20/10, mean reversion RSI-2, ou momentum
  12-1 — todas canônicas, parâmetros fixos.
- **Backtester custom** (~200 linhas), não biblioteca. Usuário precisa *ver*
  taxas, fills, equity. Black box destrói o aprendizado.
- **Convenção crítica de execução**: signal em t → fill no open de t+1.
  Hard-coded com teste unitário. Look-ahead bias é o bug invisível mais comum.
- **OOS reservado**: últimos 20% dos dados são intocáveis durante todo
  desenvolvimento. Isso é configurado em `config/default.yaml` no início e
  defendido até o teste final.
- **Comparação obrigatória** contra benchmarks: buy-and-hold + DCA. Se sua
  estratégia não bate "fazer nada", ela não vale a pena.

**Métricas obrigatórias** (não só "retorno total"):

- CAGR (retorno anualizado composto)
- Max drawdown (pior queda do pico ao fundo)
- Sharpe ratio (retorno por unidade de risco)
- Win rate, número de trades
- **Mediana** dos retornos por janela (não só média — média esconde tail events)

**Sanity test crítico** (sempre rodar): zero-cost buy-and-hold deve produzir
retorno = preço final / preço inicial (sem fees). Se falhar, há bug no engine.

## Fase 1.5 — Walk-forward analysis

Backtest único de N anos é uma média que esconde tudo. Walk-forward divide
em janelas rolantes (ex: 6 meses) e calcula métricas por janela.

**O que reportar**:

- Por janela: retorno, max DD intra-janela, número de trades, ganhadores
- Agregado: % janelas positivas, **mediana** (mais honesta que média),
  desvio padrão, pior janela, pior max DD

**O que procurar**:

- **Diferença grande entre média e mediana** = retorno dominado por tail
  events (ex: um único bull run). Isso é o sinal mais importante.
  Verbalize: "a média de +35% é dominada pela janela X com +332%; sem ela
  cai pra +5%".
- **% positivo abaixo de 50%** = pior que jogar dado.
- **Pior janela > -25%** = perda emocionalmente insuportável ao vivo.

## Fase 2 — Ajustes principiados (NÃO tunados)

Quando o usuário pedir "ajustar pra melhorar", **alerte que isso é
overfitting** e ofereça apenas ajustes **principiados** — vindos da
literatura, não dos números observados.

**Distinção crítica**:

- **Principiado**: "trend-following clássico usa filtro 200-SMA (Faber 2007)
  e stop ATR de 2N (Turtles, anos 80)". Eu sei disso *antes* de ver os
  dados. Parâmetros fixos por convenção histórica.
- **Tunado** (proibido): "vou testar 5 valores de stop e ficar com o melhor".
  Multiplica overfitting.

**Adições principiadas que valem**:

- **Filtro de tendência** (Faber): só long se close > SMA(200). Reduz
  trades em mercado lateral.
- **Stop-loss ATR** (Turtle 2N): exit se preço cai 2 × ATR(14) abaixo da
  entrada. Cap em perda individual.
- **Volatility targeting**: padroniza risco entre regimes.
- **Diversificação multi-ativo**: mesma estratégia em N coins/ações
  correlacionadas é alavanca real, não data mining. Mas o ganho é menor que
  parece em ativos altamente correlatos (cripto).

**Após cada adição, RODE walk-forward novamente** e mostre o resultado com
o aviso: "número in-sample melhorou, mas isso não prova nada — o teste real
é OOS".

## Fase 2.5 — Anti-padrões a empurrar de volta

Reconheça e empurre de volta firmemente:

### "Vamos testar mais estratégias pra achar uma que renda mais"
Multiple comparisons problem. Quanto mais variantes você testa no mesmo
período, maior a chance de uma "vencer" por sorte. Resposta: ou (a) commit
*antes* a um critério de seleção e aceitar o resultado, ou (b) parar de
testar e ir pra paper trading.

### "Vamos testar no período pós-bull pra remover o outlier"
Post-hoc selection. É overfitting fraco — você está fatiando o tempo
depois de ver os números. **Pode** ser feito como sensitivity analysis,
*nunca* como "esse é o resultado verdadeiro".

### "Vamos testar moedas menos conhecidas pra aumentar retorno"
Mesma armadilha, dimensão diferente. Reporte a *distribuição* dos resultados,
não escolha um vencedor. Em cripto, altcoins menores tipicamente têm:
mediana negativa, % positivo ~30%, ocasionais +400% windows. Loteria.

### "A estratégia X teve +1500% in-sample"
Quase sempre dominado por uma única mania histórica (ADA-2021, MATIC-2021,
DOGE-2024). Mostre a mediana pós-bull lado a lado e o usuário entende.

### "Vamos otimizar os parâmetros 50/200"
Não. Use os famosos. Otimização de hyperparam só com walk-forward formal,
e mesmo assim com cuidado.

## Fase 3 — Avaliação OOS (uma única vez)

**Antes** de rodar o OOS, force o usuário a pré-comprometer com critérios
de aceite específicos:

- Mínimo de %positivo (ex: ≥ 50%)
- Mediana > 0%
- Pior janela ≥ X% (ex: -15%)
- Pior max DD ≥ Y% (ex: -25%)
- Bate buy-and-hold em alguma métrica de risco-ajustado (Sharpe)

Critérios escritos *antes* de ver os números. Sem isso, qualquer resultado
vira "ok" via racionalização.

Rodar UMA vez. Se passar → paper trading. Se falhar → voltar pra Fase 2 ou
desistir. Não "rodar de novo com pequeno ajuste" — isso destrói o OOS.

## Fase 4 — Paper trading (Fase 3 do projeto)

Loop em tempo real contra exchange testnet ou simulador local. 3-6 meses
mínimo. Coleta evidência *real*, não mais backtest. Kill switch automático
se drawdown ao vivo passar do pior visto in-sample.

## Fase 5 — Live com capital pequeno

Só após paper trading positivo. Capital baixo, kill switch agressivo,
revisão semanal nos primeiros 3 meses.

## Reportar com honestidade brutal

Sempre incluir:

- **Calibração de expectativa**: "10-18% CAGR com max DD de 20%" é bom de
  verdade, *acima* de CDI. Não é "ficar rico".
- **O que o teste NÃO prova**: OOS passar não garante futuro. Walk-forward
  com 7 janelas tem variance alta. Backtest sempre supõe execução perfeita.
- **Trade-offs explícitos**: estratégia troca retorno por menor drawdown. O
  usuário precisa aceitar isso emocionalmente *antes* de operar — senão vai
  desligar o bot na primeira janela negativa e racionalizar.

## Linguagem e jargão

Sempre explicar termos quando aparecerem pela primeira vez (SMA, EMA, ATR,
bps, drawdown, Sharpe, CAGR, walk-forward, OOS, look-ahead bias, etc.).
Usuário típico desse projeto é programador iniciante em finanças.

## Rejeitar

- Day trading / HFT (custos matam, varejo perde quase sempre)
- ML / LSTM / RL antes de ter o pipeline básico funcionando
- Estratégias inventadas pelo usuário sem precedente na literatura (alta
  chance de overfit)
- "Vamos otimizar isso, daquilo, e aquilo outro" — caminho clássico pro
  buraco
- Operar capital significativo (>R$50k) em bot iniciante

## Estrutura de arquivos canônica

```
src/<projeto>/
├── data/loader.py          # ccxt fetcher com cache parquet
├── data/splits.py          # in-sample / out-of-sample
├── strategies/base.py      # Strategy ABC: generate_signals(df) -> Series
├── strategies/<strategy>.py
├── strategies/benchmarks.py
├── indicators/             # ATR, SMA, etc.
├── engine/backtester.py    # bar-by-bar loop, fees, fills, stop-loss
├── engine/walkforward.py   # rolling windows
├── engine/portfolio.py     # multi-asset (Phase 2+)
├── engine/dca.py           # benchmark DCA não cabe no Strategy
├── engine/costs.py         # CostModel
├── metrics/performance.py  # CAGR, Sharpe, max_dd, win_rate
├── reporting/compare.py
├── reporting/tearsheet.py
└── cli.py
config/default.yaml
data/raw/                   # parquet caches, gitignored
tests/
```
