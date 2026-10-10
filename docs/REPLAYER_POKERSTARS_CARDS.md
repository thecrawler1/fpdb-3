# Cartas PokerStars e apostas por assento

## Refinamento de 10 de outubro de 2026

Esta etapa responde ao pedido de cartas com pips e figuras completas, fichas
mais legíveis e identificação inequívoca do dono de cada aposta.

- A geometria das apostas parte do assento efetivamente desenhado, incluindo
  os ajustes de posição em janelas estreitas.
- Uma ligação pontilhada discreta associa cada aposta à placa ou às cartas
  do dono, mesmo quando o grupo precisa desviar de uma região ocupada.
- A aposta do assento inferior fica ao lado das suas cartas, preservando a
  faixa central para o pote e para o jogador de cima.
- As apostas evitam cartas, placas, board visível, dealer do dono e grupos de
  fichas já desenhados. O total do pote pré-flop reserva espaço abaixo da aposta
  do assento superior.
- Fichas de 32 px, com bordas segmentadas, profundidade e denominação impressa.
  A decomposição continua exata; os valores impressos são unidades canônicas,
  enquanto o rótulo do total acompanha o modo monetário ou BB.
- Volume local fixo em **50%**, substituindo os 100% da etapa anterior, com
  o controle **Sound** para ativar/silenciar.

## Faces completas

O deck **colour** agora usa as faces originais do cliente PokerStars configurado
em `site_path`, lidas diretamente de
`Gx/table-view/cards/default/1440/cache/<rank><suit>.png`.
Isso inclui todos os pips das cartas numéricas e as figuras de J, Q e K.
A suavização de imagem e a sombra discreta integram as faces à mesa, preservando
as dimensões externas das cartas, a sobreposição e o verso do FPDB.

Quando uma face local não está disponível, o replayer usa o deck SVG `white`
existente no projeto (Nicu Buculei/Open Clip Art Library, domínio público indicado
nos metadados dos SVGs). Os arquivos originais do cliente são somente lidos e
não são distribuídos no fork. As imagens abaixo são capturas da interface,
com uma mão pública de teste.

## Verificação

- **149 testes direcionados aprovados**, incluindo layout, BB, fichas exatas,
  fold, variantes, controles, áudio, equidade, compartilhamento e solver review.
- Ruff aprovado nos arquivos alterados; mypy aprovado nos módulos de cartas,
  fichas e áudio.
- As **52 faces locais** coincidem com as imagens originais do PokerStars.
- As **52 faces SVG de fallback** foram renderizadas: não vazias e distintas.
- Sete efeitos reais carregados com volume Qt `0.5`; transições de **25 mãos
  reais** e comportamento de avanço/reversão/salto/fechamento verificados.
- Capturas Qt/offscreen em 1280×720, 1600×900 e 1260×1380, incluindo fold,
  resultado, valores em BB e o cenário conservado de main pot 240 + side pot 40.

As capturas não acessam o banco pessoal. Para reproduzir com faces locais:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python tools/capture_replayer_review.py \
  --out /tmp/replayer-pokerstars \
  --pokerstars-path "/caminho/absoluto/para/PokerStars" \
  --side-pots --polish-cases
```

Acrescente `--big-blinds` para verificar a apresentação em BB. Sem
`--pokerstars-path`, a configuração pública de exemplo usa as faces SVG.

![Aposta do Hero junto às próprias cartas](images/replayer-pokerstars/actor-1280.png)

![Board com pips e figuras completos](images/replayer-pokerstars/flop-1600.png)

![Main pot e side pot conservados](images/replayer-pokerstars/side-pots-1280.png)
