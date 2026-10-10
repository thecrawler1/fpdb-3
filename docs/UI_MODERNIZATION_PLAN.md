# Proposta de task: FPDB Modern Workspace

**Estado:** proposta de design e arquitetura; implementação ainda não iniciada.

**Objetivo:** experiência de gestão e revisão de mãos inspirada no Holdem Manager,
com acabamento visual e clareza de informação inspirados no GTO Wizard.

## 1. Referências

Referências públicas consultadas em 10 de outubro de 2026:

| Referência | O que aproveitar |
| --- | --- |
| [Holdem Manager 3](https://www.holdemmanager.com/hm3/) | Fluxo sessão → relatório → mãos → replay; tabelas densas; relatórios por situação; marcação e notas |
| [HM3: análise por situação](https://cdn.holdemmanager.com/img/features/Analysis1Full.png) | Relatório central, indicadores contextualizados e tabela ligada ao gráfico |
| [GTO Wizard](https://gtowizard.com/) | Superfícies escuras discretas, hierarquia tipográfica, filtros compactos, visual orientado a decisões |
| [GTO Wizard: reports](https://cdn.prod.website-files.com/68a98c9826dab9f7a78eef18/68dc2ad77b755fb7d4887c9a_Reports-Desktop-poster-00001.jpg) | Contexto no topo, seleção de estatística e detalhamento adjacente |
| [GTO Wizard: analyzer](https://cdn.prod.website-files.com/68a98c9826dab9f7a78eef18/68d506d9395a29f6e3414220_analyzer-2.0-default.avif) | Tabela de mãos com cartas compactas, filtros sob demanda e controles de baixo ruído visual |

Foram examinadas capturas públicas e a apresentação dos produtos. Isso não
equivale a uma auditoria de todas as telas das aplicações autenticadas. Para
refinar o replayer, capturas de uma tela específica que o usuário goste serão
uma referência adicional útil.

As referências orientam composição e interação; identidade, componentes, ícones
e assets do fork devem ser próprios. O visual de um solver não deve fazer um
resultado estatístico parecer uma avaliação GTO: Hero vs Field, resultado
realizado e all-in EV precisam continuar explicitamente identificados.

## 2. Diagnóstico da interface atual

Arquivos examinados:

- `fpdb_3_legacy/fpdb.pyw`: shell em `QMainWindow`, navegação por menus e `QTabWidget`.
- `fpdb_3_legacy/ThemeManager.py`: integração de paletas, qt_material e temas de popups.
- `fpdb_3_legacy/ring_stats/styles.py`: QSS para tabelas, gráficos e indicadores.
- `fpdb_3_legacy/GuiReplayer.py`: desenho customizado com `QPainter`, controles,
  estados de replay e layout na mesma classe.
- Capturas de demonstração em `docs/images/hand-replayer.png` e
  `docs/images/ring-player-stats.png`.

Pontos de melhoria:

- Hierarquia de navegação pouco evidente entre sessões, relatórios e estudo.
- Filtros longos consumindo uma parte desproporcional da área útil.
- Muitas bordas, cores de destaque e controles competindo entre si.
- Diferenças de tipografia, espaçamento e densidade entre páginas.
- Replayer com bastante área decorativa e informação contextual dispersa.
- Cartas e identificadores de jogadores precisam de uma linguagem visual unificada.
- Estilo, construção dos widgets, consulta e interação ainda se misturam em
  vários módulos, tornando melhorias globais trabalhosas.

Trocar somente as cores não resolve esses pontos. Precisamos de arquitetura de
informação, componentes reutilizáveis e decisões de layout.

## 3. Framework: decisão recomendada

**Continuar com Python + PySide6/Qt e modernizar a interface por etapas.**

| Caminho | Benefícios | Custo e trade-offs |
| --- | --- | --- |
| Qt Widgets + QSS/delegates/desenho customizado | Reutiliza tabelas, PyQtGraph, dialogs e integração existentes; pode entregar um visual moderno | Componentes, layouts e microinterações exigem trabalho explícito; QSS não é CSS de navegador |
| Qt Quick/QML + backend Python | Bom para interfaces customizadas, estados visuais e animação de cartas/fichas | Nova camada de apresentação; precisa de adapters, modelos, empacotamento e testes de recursos QML |
| React + Electron ou Tauri | Ecossistema amplo de design web e visualizações | Novo frontend, ponte com Python, comunicação/instalação e integração desktop/HUD; esforço significativamente maior |

**QML é parte do Qt**, não uma troca de framework nem uma necessidade de reescrever
o backend em C++. Um visual semelhante ao GTO Wizard é viável nos dois caminhos Qt.

### Estratégia incremental

1. Design system e shell usando Widgets, reaproveitando as páginas existentes.
2. Protótipo visual do replayer em Qt Quick/QML, com um adapter para os frames atuais.
3. Comparar esse protótipo com um replayer Widgets redesenhado: legibilidade,
   manutenção, comportamento HiDPI, fluidez e empacotamento.
4. Adotar QML no replayer se o ganho justificar a nova camada. Migrar outras
   superfícies apenas quando houver benefício claro.

`QQuickWidget` permite inserir uma cena QML num shell Widgets, mas tem uma passagem
extra de renderização e desativa o render loop threaded do Qt Quick. O protótipo
deve medir o resultado, em vez de presumir que QML será sempre mais rápido.
Widgets como PyQtGraph não são inseridos diretamente numa árvore QML; podem
continuar no shell Widgets durante a migração. Uma futura shell totalmente QML
exigiria adaptar esses componentes ou substituí-los.

Referências técnicas:

- [Qt Quick Controls](https://doc.qt.io/qt-6/qtquickcontrols-index.html)
- [Customização dos controles](https://doc.qt.io/qt-6/qtquickcontrols-customize.html)
- [QQuickWidget e integração com Widgets](https://doc.qt.io/qt-6/qquickwidget.html)

As páginas da documentação acompanham o Qt mais recente; qualquer componente
adotado deve ser verificado contra o Qt 6.11.1 usado no fork.

## 4. Direção visual proposta

### Linguagem visual

- Dark mode neutro, com superfícies distinguíveis por tons, não por grandes bordas.
- Um destaque principal verde suave; cores de ações e de resultados têm papéis separados.
- Hierarquia clara: título da página, contexto, indicador, informação secundária.
- Ícones consistentes, com legenda onde a ação não for óbvia.
- Tabelas compactas e legíveis, números alinhados e dígitos tabulares.
- Cartas vetoriais de quatro cores, com ranks legíveis mesmo em células pequenas.
- Estados vazios, carregamento e erro desenhados como parte da experiência.
- Animações curtas e opcionais, mantendo a revisão rápida por teclado.

Paleta inicial para discutir nos mockups, não especificação definitiva:

| Token | Cor inicial |
| --- | --- |
| background | `#101216` |
| surface | `#181B21` |
| surface-raised | `#22262E` |
| border-subtle | `#303640` |
| text-primary | `#EEF1F5` |
| text-secondary | `#A6AFBC` |
| accent | `#78D9A0` |
| profit | `#78D9A0` |
| loss | `#EF8188` |

Escala de espaçamento: 4/8/12/16/24/32. Raios moderados, fonte de interface
consistente e controles com estados normal, hover, pressed, disabled e focus.
As cores de ações devem ter uma legenda e seguir a mesma convenção na mesa,
timeline, tabelas e grades de ranges.

### Navegação

Sidebar permanente, recolhível:

```text
Visão geral
Sessões
Mãos
Estudos
Adversários
HUD
Importação
Configurações
```

Barra de contexto compacta: jogador, site, formato, stakes e período. Filtros
ativos aparecem como chips removíveis. Filtros avançados ficam num painel
recolhível, mantendo um resumo visível mesmo fechado.

### Replayer

```text
┌──────────────────────────────────────────────────────────────────┐
│ Contexto da mão · limites · data · BB/moeda · compartilhar · …    │
├────────────┬───────────────────────────────────┬─────────────────┤
│ Lista de   │ Mesa limpa, cartas e jogadores    │ Ações da mão    │
│ mãos /     │ Actor atual destacado             │ por street      │
│ sessão     │ Board · pote · stacks · apostas   │                 │
│ recolhível │                                   │ Contexto:       │
│            │                                   │ SPR / pot odds  │
├────────────┴───────────────────────────────────┴─────────────────┤
│ Preflop → Flop → Turn → River · timeline por ações               │
│ Início · anterior · play/pause · próxima · fim · velocidade · som │
└──────────────────────────────────────────────────────────────────┘
```

Prioridades:

- Mesa menos decorativa e melhor aproveitamento da área para cartas e ações.
- Seat cards com nome, posição, stack e ação atual bem separados.
- Hero e actor atual com destaque distinto.
- Pote e apostas com hierarquia clara; movimento de fichas e cartas quando animado.
- Timeline selecionável por ação, com streets identificadas.
- Sons existentes preservados, com mute e volume discretos.
- Toggle BB/moeda, quando a variante permitir, usando os valores reais existentes.
- Atalhos e navegação entre mãos; painel lateral recolhível em telas menores.
- Equidade/pot odds somente quando disponíveis, sem inventar valores para cartas desconhecidas.

## 5. Epic e tasks propostas

**Epic:** `Modernizar a experiência visual do FPDB: HM-style workflow + GTO-style UI`.

| Task | Entrega | Critério de conclusão |
| --- | --- | --- |
| UI-01 — Referências e mockups | Board anotado e mockups de Overview, Mãos e Replayer | Composição e hierarquia aprovadas pelo usuário antes de implementação |
| UI-02 — Design system | Tokens, botões, inputs, tabelas, cartas, chips de filtros e estados | Componentes consistentes numa galeria; estilos locais usam os tokens |
| UI-03 — Shell e navegação | Sidebar, barra de contexto e persistência da página selecionada | Acesso a todas as funcionalidades atuais; navegação previsível |
| UI-04 — Protótipo do replayer | Mesa e controles em Widgets/QML com adapter de frames | Comparação visual, de interação e de empacotamento; decisão registrada |
| UI-05 — Replayer final | Novo layout, timeline, controles e sons | Mesmas mãos/estados; forward, back, seek, Play e close corretos |
| UI-06 — Mãos e filtros | Tabela compacta, cartas, filtro avançado e preview | Seleção, paginação, filtros e abertura no replayer preservados |
| UI-07 — Overview e sessões | Métricas, gráficos e tabela integrados | Números reconciliados com o backend; detalhes abrindo as mãos corretas |
| UI-08 — Estudos e relatórios | Aplicação do sistema visual nas análises | Amostras, filtros, comparações e drill-down mantidos explícitos |
| UI-09 — Preferências e HUD | Organização de formulários e preview | Controles acessíveis; preferências e perfis persistentes |

UI-01 é o próximo passo recomendado. O primeiro recorte implementável é
**design system + shell + replayer**, depois de aprovar os três mockups.

## 6. Arquitetura de implementação

- Reutilizar o backend de importação, bancos, equidade, estudos e estatísticas.
- Separar os estados de replay e as consultas da construção/pintura dos widgets.
- Reutilizar `ReplayModel`, `ReplayFrame` e `ReplayPlayer` através de um presenter
  ou adapter, sem duplicar as regras do poker na camada visual.
- Fornecer dados a QML por propriedades/sinais e modelos Qt, caso QML seja escolhido.
- Manter consultas e cálculos pesados fora da thread de interface.
- Compartilhar tokens entre QSS, desenho customizado, PyQtGraph e componentes QML.
- Entregar mudanças em recortes pequenos, facilitando acompanhar o upstream.
- Se houver QML: incluir arquivos e recursos nos pacotes, testar imports, foco,
  teclado, HiDPI e o ambiente Linux/XWayland desta instalação.

## 7. Critérios de aceitação do primeiro recorte

- Mockups revisados para 1280×720 e 1920×1080, incluindo comportamento HiDPI.
- Navegação e controles principais acessíveis sem cortes ou sobreposição.
- Tabelas com alinhamento, ordenação numérica e seleção legíveis.
- Filtros ativos visíveis e mesma seleção preservada entre telas relacionadas.
- Replayer conserva cartas, stacks, pote, resultados, ações e os sete sons atuais.
- A revisão é utilizável por teclado e com animações desativadas.
- Valores, frequências e amostras continuam provenientes dos cálculos existentes.
- Contraste e foco visível verificados; informação não depende exclusivamente de cor.
- Capturas antes/depois com dados de demonstração, sem históricos privados no repositório.
- Testes direcionados às mudanças, sem bloquear a aprovação dos mockups na
  investigação separada documentada em [CI_QT_SHUTDOWN_ISSUE.md](CI_QT_SHUTDOWN_ISSUE.md).

## 8. Decisões ainda abertas

1. Preferência entre mesa minimalista e mesa com sensação física mais marcada.
2. Replayer integrado à página de mãos, destacável, ou ambos.
3. Densidade padrão das tabelas e possibilidade de modo compacto/confortável.
4. Paleta e deck a adotar depois de ver os mockups.
5. Implementação final do replayer em Widgets ou QML, após o protótipo.

A troca completa para uma interface web só deve ser reavaliada se o produto
passar a precisar de navegador, acesso remoto ou reutilização de um frontend
web. Para este aplicativo desktop, o Qt já atende à direção visual proposta.
