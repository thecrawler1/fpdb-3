# Responsividade de Results

## Ponto de partida

Os logs locais da aplicação indicavam **5,5–6,3 s até a primeira pintura**
de Results, com a maior parte do tempo em importação de módulos e construção
da tela. Esse é o baseline observado antes desta rodada. Ainda não foram
fornecidas medições equivalentes do carregamento completo com o banco pessoal;
o benchmark usa banco temporário e mãos públicas.

## Limite de 500 ms com importação automática real

O teste isolado anterior deixava a pasta monitorada vazia. Isso omitia o trabalho
que concorria com Results na aplicação: a primeira importação automática relê
históricos recentes, mesmo quando todas as mãos já estão no banco.

O modo `launcher` executa `legacy_launcher.main()` e o bloco `__main__` real,
com navegação, tema, logging, importador e travas reais em diretório temporário.
`--monitored-hands 2000` cria 2.000 mãos públicas cujos IDs já constam no banco.
O clique ocorre assim que a navegação habilita, sem esperar a página preparada.
`--click-during-import` descarta essa página e constrói outra enquanto o worker
ainda está ativo. O benchmark aguarda a pintura da tabela e das quatro curvas.

Medições X11/xcb, sem cProfile:

| Cenário | Pinturas concluídas | Confirmação |
| --- | ---: | ---: |
| Replay de 2.000 duplicatas, antes da correção | 16,490 s | — |
| Primeira abertura após priorização, perfil anonimizado | 0,421 s | 0,423 s |
| Nova página durante o replay, perfil anonimizado | 0,436 s | 0,439 s |

As últimas duas medições preservaram as opções visuais do perfil e o ambiente
desktop, usando dados públicos. Cada replay terminou com 2.000 duplicatas,
zero inserções/erros e 2.000 linhas no banco. O prazo **<500 ms** é uma asserção
obrigatória nos testes sem profiling, sem xfail ou relaxamento do limite.

Correções que tornam esse cenário responsivo:

- Results tem prioridade na inicialização; replay começa depois de os dados
  estarem prontos, com 50 ms para a próxima pintura. Falhas têm um backstop.
- A GUI registra diretórios; descoberta/leitura ocorrem no worker.
- Parser, limpeza, preparação, estatísticas e inserção cedem execução a cada
  oito itens: 1 ms normalmente, 5 ms enquanto uma carga interativa está pendente.
  Não há cancelamento parcial nem commits intermediários adicionados.
- Prioridade é liberada em conclusão, erro, datas inválidas e fechamento.
- Logging desabilitado não percorre a pilha nem formata mãos inteiras.
- Start/Stop manual consome a solicitação de início automático pendente.

```bash
.venv/bin/python tools/benchmark_results_loading.py \
  --mode launcher --hands 2000 --monitored-hands 2000 --platform xcb
.venv/bin/python tools/benchmark_results_loading.py \
  --mode launcher --hands 2000 --monitored-hands 2000 --platform xcb \
  --click-during-import
```

`--config-template` clona e anonimiza opções do perfil, redirecionando banco e
todos os caminhos para o fixture. `--desktop-settings` preserva configurações
Qt/fontconfig; `--desktop-env-pid` pode espelhar o ambiente do processo existente.
O perfil original e o banco pessoal não são usados como destino de escrita.

## Diagnóstico isolado e acesso preparado

`tools/benchmark_results_loading.py` usa um processo novo, o tema real da aplicação
e uma mão pública replicada em `Hands`/`HandsPlayers`. Mede do clique até a pintura
da tabela e das curvas, separando importação, construção, Hero, consulta, parsing,
agrupamento e desenho. A preparação do banco de teste fica fora desse intervalo.

- Abertura fria, tema completo, 5.000 mãos, X11/xcb: **0,419 s** até as duas
  pinturas e **0,422 s** até confirmação de tabela e gráfico prontos.
- Página pré-carregada, tema completo, 5.000 mãos, X11/xcb: **0,033 s** até as duas
  pinturas e **0,051 s** até confirmação estável. Preparação prévia: **0,381 s**.
- As duas medições são referências locais com o mesmo tema/plataforma e dados
  públicos, não uma medição do banco pessoal do usuário.

Agora a aplicação agenda Results após a primeira pintura e o perfil estar pronto,
prepara a página oculta e reutiliza a mesma instância ao clicar. O clique não
repete consulta nem montagem se o snapshot continua atual. Novas mãos invalidam
os dados; mudar banco/perfil ou fechar a aba descarta a instância antiga.

```bash
.venv/bin/python tools/benchmark_results_loading.py --mode cold --hands 5000
.venv/bin/python tools/benchmark_results_loading.py --mode preloaded --hands 5000 --platform xcb
```

`--profile` acrescenta cProfile; `--theme none` permite comparar sem o tema.
O log da aplicação registra `[PERF] Results ready` com as etapas em segundos,
`[PERF] Results stages` separando CPU, tarefa e entrega na GUI, e
`[PERF] Results access` com a espera ao acessar a página. Esses registros incluem
o caminho real que não estava sendo medido pelo profiler da página de loading.

## Abertura e preparação

- `deferred_page.py`: o handler abre imediatamente uma página **Loading results…**
  e agenda a importação de `GuiResultsViewer` em segundo plano. A construção dos
  widgets ocorre na thread da interface após a importação; falhas oferecem Retry.
- `fpdb.pyw` passa o banco existente da aplicação (`db=self.db`) para Results.
  `prepare_results_database` descobre Heroes de forma assíncrona, usando uma
  conexão de worker e cursor próprios. Quando usada sem banco fornecido, a tela
  também cria seu banco em segundo plano.
- `GuiResultsViewer.py`: acima de **1.000 mãos**, parsing, filtros/agrupamento e
  curvas são preparados por workers. Seleções e unidades reutilizam curvas em
  cache, limitado a oito entradas, e pedidos idênticos em andamento são
  deduplicados. Novos dados invalidam o cache.
- `period_results.py` mantém valores monetários, totais e acumulação das curvas
  em `Decimal`; converte os pontos para float somente para desenhar. O Total usa
  todas as mãos filtradas, com taxas BB normalizadas pelo blind de cada mão.

## Concorrência e fechamento

`background_tasks.py` limita os workers de preparação a **duas tarefas em execução**,
com capacidade compartilhada entre as instâncias de `TaskWorker`.
Preparações de linhas/tabela substituídas são canceladas; gerações de consulta,
dados, agrupamento e curva rejeitam respostas obsoletas. Enquanto resultados
anteriores aparecem durante uma atualização, exportação e abertura de mãos
ficam desabilitadas até os dados atuais estarem prontos.

`cooperative_work.py` fornece checkpoints de cancelamento e pausas de 1 ms para
ceder o GIL durante parsing, agrupamento e curvas, a cada 2.048 mãos. Fechar a aba
cancela tarefas e retém os workers até terminarem, sem esperar na thread da
interface. Importações já iniciadas podem terminar em segundo plano, mas não
constroem a página fechada. Bancos próprios são desconectados após os workers;
o banco emprestado continua sob responsabilidade da aplicação. Na saída da
aplicação, os workers retidos são aguardados.

## Desenho do gráfico

O `ProfitGraphWidget` compartilhado em
`ring_stats/views/dashboard_view.py` usa clipping à área visível e downsampling
automático **peak**. A redução afeta somente o desenho, preservando os dados
originais completos para cálculos e navegação. Os totais e a população de mãos
não são calculados a partir dos pontos reduzidos.

## Regressões

- `test_results_cold_loading.py`: processo novo com tema real, tabela e curvas
  efetivamente pintadas; iniciador real com replay de 2.000 duplicatas deve abrir
  em **<500 ms**, inclusive com uma nova página durante o replay. Página preparada
  de 5.000 mãos mantém o teste isolado **<250 ms** sem consulta extra.
- `test_results_startup_priority.py`: readiness, falha, backstop e decisão manual
  do usuário controlam o início automático, uma única vez.
- `test_results_priority_lifetime.py`: prioridade não vaza entre páginas,
  erros, edições de datas, retry e fechamento.
- `test_autoimport_cooperation.py` / `test_import_parser_cooperation.py`:
  descoberta no worker, parser cooperativo, duplicatas, offsets, commit único e
  entrega de IDs ao HUD depois do commit.
- `test_results_preload.py`: pré-carregamento oculto, reutilização da página,
  invalidação após importação, fechamento/reabertura e troca de perfil/banco.
- `test_results_first_load.py`: abertura automática com uma mão pública importada,
  banco da aplicação ou banco próprio, sem clicar em Refresh. Confere a reutilização
  da conexão de worker após descobrir o Hero, inclusive quando a preparação falha.
  A fachada temporária não é proprietária da conexão: suas referências são removidas
  antes da destruição, evitando fechar uma conexão devolvida ao pool.
- `test_deferred_page.py`: importação simulada de **0,6 s**, página de loading,
  construção na thread GUI, Retry, fechamento não bloqueante e handler real
  reutilizando o banco da aplicação.
- `test_results_responsiveness.py`: setup de banco com atraso de **0,6 s** e
  **100.000 mãos sintéticas**. Timer de heartbeat de 10 ms exige gaps **<250 ms**;
  abertura, entrega das linhas e seleção do Total também devem ficar abaixo de
  250 ms. Confere lucro total de 10.000.000 centavos e ponto final original de
  US$ 100.000.
- `test_results_async_state.py`: conclusão fora de ordem, status e ações durante
  atualização, redescoberta assíncrona de Hero, deduplicação de curvas e rejeição
  de respostas/erros obsoletos.

Execute na raiz do repositório; `-m qt` inclui os testes Qt excluídos por padrão:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -m qt \
  tests/qt/test_deferred_page.py \
  tests/qt/test_results_first_load.py \
  tests/qt/test_results_cold_loading.py \
  tests/qt/test_results_startup_priority.py \
  tests/qt/test_results_priority_lifetime.py \
  tests/qt/test_results_preload.py \
  tests/qt/test_results_responsiveness.py \
  tests/qt/test_results_async_state.py \
  tests/qt/test_background_tasks.py
```
