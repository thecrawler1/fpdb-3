# Dez melhorias prioritárias de resultados e revisão de mãos

O levantamento encontrou problemas concretos nos fluxos usados diariamente:
datas personalizadas sem atualização automática, descarte do último resultado
durante recargas, cópia vazia de cartas, redimensionamento que sobrescrevia a
largura escolhida e um cache de mãos que crescia a cada página visitada.

## Implementações

| # | Melhoria | Funcionamento |
|---|---|---|
| 1 | Datas personalizadas automáticas | Atualização após 300 ms sem edição; intervalos invertidos não consultam o banco. As datas ficam em uma linha própria. |
| 2 | Recarga resiliente de resultados | Mantém o último resultado legível durante recarga/falha; informa que é anterior e ignora respostas obsoletas. Ações de exportar/abrir mãos aguardam um resultado atual. |
| 3 | Exportação CSV | Exporta todos os períodos filtrados, na ordem das linhas da tabela, mais Total. Datas ISO, números decimais sem formatação de moeda/localidade e UTF-8 com BOM. A gravação usa `QSaveFile`. |
| 4 | Cópia de tabelas | Ctrl+C copia a seleção; menu do cabeçalho também copia a tabela exibida com cabeçalhos. Respeita colunas visíveis, ordem visual, ordenação das linhas e cartas como texto. Editores de células conservam sua própria seleção de texto. |
| 5 | Layout persistente | Arraste/reordene cabeçalhos e redimensione colunas interativas. Ordem e largura persistem entre páginas e aberturas; Reset columns restaura o padrão. A linha Total acompanha a ordem dos resultados. |
| 6 | Paginação direta | Digite a página e confirme com Enter. Escolha 25, 50, 100 ou 250 mãos por página; a preferência é salva e a mão selecionada permanece no novo bloco quando possível. |
| 7 | Busca global por ID | Pesquisa ID interno ou ID da sala, inclusive em páginas ainda não visitadas, dentro da população carregada pelos filtros. Aceita ID parcial e prefixo `#`; limpar restaura a lista. Usa metadados leves. |
| 8 | Cache limitado | Cache LRU de até `max(300, 3 × tamanho da página)` mãos reconstruídas. Páginas recentes são reaproveitadas; a lista completa de IDs continua disponível para ordenação e replay. |
| 9 | Carregamento cancelável e consistente | Novas linhas são preparadas antes de substituir a página. Cancelar navegação/ordenação mantém dados, seleção e ordem anteriores; erros isolados são registrados e contados na tela. Cargas rápidas não exibem um diálogo instantâneo. |
| 10 | Valores monetários independentes do texto formatado | Valores numéricos, cores e moeda usam os números originais; uma string como `1.234,50` não é reinterpretada com `float()`. Os cálculos financeiros existentes permanecem iguais. |

## Uso rápido

- **Resultados → Custom:** altere From/To; a consulta aplica automaticamente.
- **Resultados → Export CSV:** exporte o recorte carregado e filtrado.
- **Tabela → Ctrl+C:** copie as linhas/células selecionadas.
- **Cabeçalho → clique direito:** copiar tabela completa, escolher/resetar colunas.
- **Hand Viewer → Find hand ID:** procure uma mão na lista carregada.
- **Hand Viewer → Page:** digite o destino e pressione Enter.
- **Hand Viewer → Hands per page:** ajuste a quantidade exibida.

Os estilos aprovados e as curvas contínuas dos gráficos foram preservados.

## Rodada focada em design e UX

Após o feedback de que a primeira rodada estava mais voltada a funcionalidades,
a revisão passou a priorizar hierarquia, descoberta e feedback da interface:

| # | Mudança de design/UX | Benefício |
|---|---|---|
| 1 | Títulos e descrições nas telas | Explicita o propósito de Resultados e Mãos. |
| 2 | Ações separadas dos controles de análise | Atualizar/exportar/colunas não competem com Hero, agrupamento e datas. |
| 3 | Dia/Semana/Mês/Ano em seletor segmentado | Opções visíveis, com estado selecionado claro e um clique por escolha. |
| 4 | $/BB em seletor segmentado | Unidade do gráfico identificável sem abrir um dropdown. |
| 5 | Filtros ativos como chips removíveis | O recorte permanece visível mesmo quando o painel está fechado; limpar fica próximo do contexto. |
| 6 | Cabeçalho contextual do gráfico e botão All periods | Diferencia um período selecionado do total filtrado, sem depender de descobrir o clique na linha Total. |
| 7 | Rodapé da mão selecionada | ID da sala, cartas, posição e Net ficam próximos da ação Replay. |
| 8 | Estados vazios com recuperação inline | Importar, ampliar datas, limpar filtros ou limpar busca sem interromper com popups. |
| 9 | Linguagem e agrupamentos mais claros | Hand features no topo da lateral, nomes completos em vez de AI/SD/RIT e jogos como Hold'em/Omaha em vez do código interno `hold`. |
| 10 | Feedback e legibilidade | Datas inválidas com borda de erro, Retry junto ao status, ações indisponíveis atenuadas, ajuda nos cabeçalhos e escala monetária sem milidólares. |

Os rótulos do gráfico não se repetem dentro e fora do canvas; legendas ocupam
uma linha própria. Selecionar outro período ou unidade ajusta o enquadramento
para os novos dados. Valores e cálculos financeiros continuam sendo os mesmos.

**153 testes direcionados aprovados** na rodada visual, incluindo sincronização
dos seletores, filtros removíveis, recuperação de estados vazios, navegação para
importação, contexto da seleção e escala de valores pequenos. Capturas Qt foram
conferidas com a paleta aprovada e dados públicos/sintéticos.

## Verificação

- **145 testes direcionados aprovados**, incluindo datas, falhas/recuperação,
  CSV e totais exatos, clipboard, preferências, busca entre páginas, cache,
  cancelamento, localidades, temas, ranges, torneios e integração do replayer.
- Ruff, mypy dos módulos utilitários afetados e `git diff --check` aprovados.
- Testes Qt e capturas usam preferências de coluna isoladas, sem gravar o perfil
  de layout pessoal. Capturas e CSV usam exclusivamente dados públicos/sintéticos.

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m tools.capture_review_usability --out /tmp/opencode/review-usability
```

Saídas: `results-export.png`, `custom-dates.png`, `hands-pages.png`,
`hand-search.png`, `active-filters.png`, `empty-search.png`, `hand-filters.png`
e `public-results.csv`.
