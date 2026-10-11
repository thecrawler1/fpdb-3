# Filtros de análise e Study Explorer

## Problemas encontrados nas telas

- Grupos de filtros expandiam verticalmente para ocupar toda a lateral, gerando
  caixas e espaços muito maiores que o conteúdo.
- Títulos com emojis, caixa alta e verde competiam com as seleções do usuário.
- Labels e linhas herdavam fundos sólidos, produzindo retângulos dentro de outros
  retângulos; ícones da sala eram duplicados em Hero e Sites.
- Datas exibiam limites técnicos como `1/1/70` e `1/1/00`, além de botões separados
  Cal/Reset e indicadores de spin sem uma finalidade clara.
- Study Explorer dividia a altura entre contexto, categorias e conteúdo de forma
  que os estudos e controles ficavam cortados. A lista e o detalhe eram dois
  blocos de texto, e tooltips extensos cobriam o painel selecionado.

## Revisão aplicada

### Filtros compartilhados

`Filters.py` agora usa seções alinhadas ao topo, com altura natural e política
vertical Maximum. Isso vale para estatísticas cash, torneios, gráficos e outras
telas que usam o componente. As seções têm headings discretos e corpos sem
caixas preenchidas; controles permanecem com limites visuais e foco claro.

Hero e Sites usam identificação textual, sem repetir logos decorativos. Campos
de mínimo de mãos e número de jogadores recebem labels próprios, alinhados a
inputs numéricos simples. O espaço entre seções segue uma escala compacta.

### Datas

- **All history** preserva os limites de consulta originais, sem expor os anos
  técnicos 1970/2100 na apresentação normal.
- Presets **Today**, **Last 7 days** e **This month** usam datas locais da interface.
- **Custom dates** mostra From/To com ano completo, formato `dd MMM yyyy` e
  calendário integrado, sem os botões Cal/Reset.
- Entrar em Custom a partir de All history começa no mês corrente; datas
  definidas programaticamente continuam sincronizadas com a apresentação.
- Fuso, `day_start` e conversão de limites SQL existentes não foram modificados.

### Study Explorer

- Header e busca permanecem separados do bloco compacto de contexto.
- Categorias e catálogo ficam na coluna esquerda; a direita apresenta o estudo,
  descrição, mínimo de decisões e os painéis como uma lista legível.
- Entradas do catálogo possuem título e metadados em duas linhas. Descrições
  completas ficam no detalhe, sem tooltips grandes cobrindo a tela.
- Selecionar novamente uma categoria remove o recorte.
- A ação principal **Open study** é destacada, e favoritos são ações secundárias.
- Em janelas estreitas, categorias ficam na zona Filters; Studies usa a altura
  para a lista, e Detail mantém a seleção e a navegação existentes.
- Scrollbars e divisores foram simplificados para evitar trilhos largos e marcas
  decorativas chamando mais atenção que os dados.

## Capturas reproduzíveis

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m tools.capture_analysis_design --out /tmp/opencode/analysis-design
```

O script usa um banco temporário, mãos públicas, gráfico sintético e histórico de
estudos temporário. Captura filtros cash, torneios, datas personalizadas e Study
Explorer nas apresentações ampla e estreita.

## Validação

Testes Qt verificam geometria das seções, ausência de scroll horizontal em uma
lateral de 340 px, presets/datas programáticas, ano completo, remoção de categoria,
conteúdo inline e preservação das zonas/navegação em janelas pequenas. Também
foram executados os testes de filtros legados, callbacks, resultados, temas e replay.
