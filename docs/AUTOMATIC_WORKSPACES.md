# Carregamento automático, subtabs e gráficos financeiros

## Ponto de partida

As alterações pendentes de UX/análise foram comitadas antes desta rodada:
`7d818ea4` — `feat: refine analysis workspaces and streamline hand review`.

## Interface

- Study Explorer: seletores de situações com texto de 16 px, peso 600 e alvos de
  aproximadamente 74 px ou mais, em vez das opções minúsculas anteriores.
- Pesquisa/estudos: captions, inputs e tabelas com piso de leitura de 15 px;
  ticks dos gráficos também recebem fonte legível.
- Research Browser: **Filters / Results / Hands** são subtabs sempre visíveis,
  com uma área inteira para cada fluxo, em todas as larguras.
- Study Dashboard: **Filters / Panels / Hands** são subtabs. Painéis com gráfico
  também oferecem **Chart / Data**, sem comprimir a tabela e o gráfico juntos.
- A janela principal mantém o título e o arraste, mas não exibe mais os três
  botões próprios de minimizar/maximizar/fechar. O menu de saída permanece.
- O replayer oferece **Close**, com atalho Esc, no conjunto de controles.
- `Mains Jouées` era francês para “mãos jogadas”. O dashboard agora usa rótulos
  traduzíveis como **Hands played**, **Net profit** e **Aggression (AF)**.

## Dados ao acessar uma tela

`automatic_loading.py` agenda uma carga no primeiro acesso, depois da criação dos
controles. Estatísticas cash/torneios, gráficos, sessões, Hand Viewer, Research
Browser, Biggest Differences e resultados passam a abrir com a consulta em
andamento, sem depender de um primeiro clique no botão de refresh.

As telas já carregadas mantêm o estado ao trocar de aba. Depois de uma importação
com novas mãos, a tela visível recarrega; as demais são invalidadas e carregam ao
serem acessadas. Uma população de mãos enviada por Resultados não é substituída
por todas as mãos do banco quando a aba é mostrada.

## Auto-import do PokerStars

Foi reproduzida a diferença de ambientes que explicava o código 1 do HUD:

- FPDB: executado com `.venv/bin/python` e dependências instaladas.
- HUD no launcher POSIX antigo: script com shebang `#!/usr/bin/env python`, que
  encontrava `/usr/bin/python`, sem PySide6 neste computador.

O launcher agora usa `hud_main_command`, isto é, o interpretador da aplicação e
o caminho absoluto do script, com opções separadas corretamente. A inicialização
pela `.venv` foi conferida pelo comando `HUD_main.pyw --help`.

Também foi corrigida a descoberta inicial de arquivos no Importer: arquivos
novos podiam ser adiados, ou marcados como consumidos por terem mais de um minuto,
sem importar o conteúdo existente. Agora entram no primeiro ciclo. Um teste real
com histórico público validou importar uma mão, importar outra anexada e manter
o total sem duplicar no terceiro ciclo.

O FPDB inicia um único auto-importer em segundo plano após carregar o perfil,
com intervalo padrão de **120 segundos**. A aba HUD mostra esse mesmo serviço e
permite parar/ajustar o intervalo. Falha na inicialização do HUD não impede o
timer nem a importação dos arquivos. O serviço é encerrado pelo fluxo de shutdown
existente da aplicação.

## Cores clássicas

Os gráficos usam tokens separados das cores mais suaves dos controles:

| Série | Modo escuro |
|---|---|
| Profit | `#39d98a` — verde |
| All-in EV | `#fbbf3a` — amarelo/laranja |
| Showdown | `#45a6ff` — azul |
| Non-showdown | `#ff647c` — vermelho |

O token `graph_hands`, usado pelo gráfico legado para a curva de profit, deixou
de apontar para cinza. Gráficos de cash, torneios, resultados e dashboard usam a
paleta compartilhada; comparações de pesquisa também têm cores mais vivas.
As curvas financeiras continuam contínuas e seus valores não foram alterados.

## Conferência

- Testes de carregamento por acesso, invalidação, subtabs e gráfico carregado
  automaticamente com profit verde.
- Teste de importação incremental real com arquivo público, sem HUD e banco
  temporário; teste de timer ativo mesmo quando lançar o HUD falha.
- Regressões de pesquisa, estudos, diferenças, resultados, replayer, gráficos,
  localidades e subprocessos executadas.

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m tools.capture_automatic_workspaces --out /tmp/opencode/automatic-workspaces
```

Todas as capturas usam dados públicos e bancos temporários.
