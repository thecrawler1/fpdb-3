# Sistema de cores: leitura confortável em uma aplicação de análise

## Diagnóstico

O problema não era apenas o hexadecimal do branco das cartas. Pequenas ilhas de
`#ffffff`, repetidas em uma tabela escura, tinham contraste de **16,60:1 contra
o fundo da tabela** e competiam com os dados. Paralelamente, qt_material, estilos
locais, cores financeiras e widgets pintados usavam paletas diferentes. Alguns
hovers combinavam verde claro com texto branco; selects mantinham um verde-lima
fora do sistema. Isso criava saltos de luminosidade e hierarquia inconsistente.

Contraste entre **letra e cartão** precisa ser alto. Contraste entre **cartão e
tabela** não precisa ser igualmente alto: o retângulo arredondado é uma superfície
decorativa, e valor/naipe já identificam a carta.

## Fundamentação e limites

1. **Oklab/OKLCH, D65, sRGB.** A luminosidade perceptual, o croma e o matiz são
   controlados separadamente. HSV/HSL não têm luminosidade perceptual uniforme:
   cores com o mesmo “value” podem parecer muito diferentes. Superfícies e textos
   usam um eixo neutro de croma baixo; cores semânticas têm luminosidade semelhante.
   A conversão para sRGB reduz croma quando necessário, em vez de simplesmente
   cortar canais e alterar matiz. Qt recebe hexadecimais sRGB de 8 bits.
2. **Contraste de luminância.** WCAG 2.2 é usado como critério verificável: ≥4,5:1
   para texto normal; a meta dos textos principais e dos pequenos caracteres de
   cartas é ≥7:1. Indicadores de foco, campos e curvas são avaliados contra seus
   fundos; ≥3:1 é a referência para informação não textual significativa.
3. **Contexto visual.** Adaptação à luminosidade, contraste simultâneo, área e
   repetição alteram a saliência. Um cartão branco pode ser fácil de distinguir
   e, ainda assim, dominar indevidamente uma tela escura. A solução reduz a
   luminosidade da superfície e conserva contraste dos caracteres — não deixa
   tudo com baixo contraste.
4. **Redundância.** Naipe continua identificável por símbolo, lucro/prejuízo por
   sinal/formatação. Gráficos têm legendas e controles identificados por nome;
   as curvas usam linhas contínuas por preferência do usuário. Cor não é a única
   informação disponível, mas curvas sobrepostas podem exigir seleção pelas
   respectivas opções para leitura com diferenças de visão de cores.
5. **Conforto não tem um hexadecimal universal.** Iluminação ambiente, monitor,
   tamanho da fonte e características visuais do leitor importam. A revisão de
   estudos de polaridade não demonstra que dark mode seja sempre mais legível.
   Por isso também existe uma paleta clara coerente, com cores semânticas mais
   escuras. Os números abaixo são medidas de cores especificadas, não de brilho
   físico do monitor nem uma certificação de todas as telas da aplicação.

## Paleta escura escolhida

| Papel | Cor | Critério |
|---|---|---|
| Janela/navegação | `#13181d` | Grafite, sem preto absoluto |
| Conteúdo/tabela | `#1a1f24` | Primeiro nível de superfície |
| Painel/campo/cabeçalho | `#23282d` | Elevação discreta |
| Hover | `#2d3238` | Mudança de luminosidade gradual |
| Texto principal | `#ced5dc` | Claro, sem branco puro |
| Texto secundário | `#a2a8af` | Hierarquia com leitura preservada |
| Seleção | `#2a3a31` | Verde de croma baixo |
| Acento | `#83caa4` | Menta com saturação contida |
| Positivo | `#89d0aa` | Verde com contraste de luminância |
| Negativo | `#f8a4a3` | Coral claro, evitando vermelho escuro sobre preto |
| Informação/showdown | `#8cc4f4` | Azul equilibrado com as outras séries |
| Aviso/EV | `#e3be80` | Âmbar suave |
| Superfície da carta | `#363b41` | Intermediária, integrada à tabela |
| Copas | `#f9c1bf` | Coral suave, símbolo ♥ |
| Ouros | `#aed6f9` | Azul suave, símbolo ♦ |
| Paus | `#addfc3` | Verde suave, símbolo ♣ |
| Espadas | `#d2d8df` | Neutro claro, símbolo ♠ |

As superfícies usam OKLCH com croma aproximadamente `0,012`, matiz `250°` e
níveis de luminosidade `0,205 → 0,235 → 0,275 → 0,315 → 0,350`. Acento menta:
`L=0,78`, `C=0,09`, `h=160°`. Letras dos naipes usam `L≈0,86`, `C≈0,065`.
Esses parâmetros são escolhas de design informadas pelos modelos, não constantes
fisiológicas nem recomendações científicas de uma tonalidade “perfeita”.

## Medidas após conversão e arredondamento para sRGB

| Par | Contraste |
|---|---:|
| Texto principal / tabela | **11,20:1** |
| Texto secundário / painel | **6,20:1** |
| Texto principal / seleção | **8,11:1** |
| Copas / carta | **7,21:1** |
| Ouros / carta | **7,42:1** |
| Paus / carta | **7,60:1** |
| Espadas / carta | **7,87:1** |
| Superfície da carta / tabela | **1,47:1** |

A luminância relativa da superfície da carta é `Y≈0,043`, contra `Y=1` do branco
sRGB. Isso descreve a cor, não uma medição de cd/m². O desenho mantém os mesmos
tamanhos, pesos e símbolos; seleção não modifica a cor do ícone da carta.

## Implementação

- `color_science.py`: transferência sRGB, luminância/contraste, Oklab, OKLCH,
  redução de croma e interpolação perceptual.
- `color_tokens.py`: única origem dos papéis semânticos escuros e claros.
- `design_system.py` / `ThemeManager.py`: paleta Qt completa, estados selecionados,
  controles, menus e migração de cores conhecidas de estilos antigos. A troca de
  paleta não reaplica a ampliação da fonte nem converte cores de domínio desconhecidas.
- `table_cards.py`: superfície intermediária e naipes claros no modo escuro;
  superfície clara moderada e naipes escuros no modo claro.
- Hand Viewer, resultados e navegação usam os mesmos tokens. Tintas financeiras
  são discretas, e a seleção tem precedência.
- Dashboard/resultados: curvas contínuas em verde, azul, coral e âmbar.
  Os cálculos e dados financeiros não foram alterados.
- Mapas de calor: interpolação em Oklab, com limite do endpoint para preservar
  contraste do rótulo. A escala inteira é remapeada até esse endpoint, conservando
  a ordem de intensidade em vez de achatar os valores mais altos.

## Verificação reproduzível

**132 testes direcionados aprovados**, cobrindo cores, temas, resultados,
filtros/ranges, torneios e integração do replayer. Ruff, mypy dos quatro módulos
de apresentação/cores e verificação do diff aprovados. Foram conferidas capturas
Qt dos modos escuro e claro, incluindo tabela densa, gráficos, menus e heatmap.

`tests/test_color_palette.py` verifica referências independentes, contraste em
estados normais/hover/seleção, foco/campos, cartas, curvas e ordenação dos mapas
de calor. Testes Qt verificam migração de estilos e troca claro/escuro idempotente.

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m tools.capture_color_review --out /tmp/opencode/color-review-dark
QT_QPA_PLATFORM=offscreen .venv/bin/python -m tools.capture_color_review --out /tmp/opencode/color-review-light --light
```

As capturas incluem tabela densa, resultados, select aberto e mapa de calor,
usando exclusivamente dados públicos/sintéticos.

## Fontes consultadas

- [Björn Ottosson — A perceptual color space for image processing](https://bottosson.github.io/posts/oklab/):
  derivação, propriedades e matrizes de Oklab.
- [W3C — CSS Color 4, Oklab/OKLCH](https://www.w3.org/TR/css-color-4/#ok-lab):
  modelos perceptuais, D65 e conversão entre espaços.
- [W3C — WCAG 2.2, contraste de texto](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html):
  fórmulas, limiares, antialiasing e limitações da avaliação por cor especificada.
- [W3C — contraste não textual](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html):
  componentes, foco, símbolos, gráficos e superfícies decorativas.
- [NN/g — Dark Mode vs. Light Mode: Which Is Better?](https://www.nngroup.com/articles/dark-mode/):
  revisão de estudos de polaridade, luz ambiente, tamanho da fonte e diferenças visuais.
