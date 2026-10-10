# Revisão visual do piloto do replayer

## Método

Dois agentes em contextos separados: um implementador e um avaliador somente de
leitura. A direção e os critérios ficaram fixos em
[REPLAYER_DESIGN_PILOT.md](REPLAYER_DESIGN_PILOT.md). O avaliador examinou capturas
reais do Qt, as capturas anteriores e as referências públicas.

Este registro não representa uma avaliação calibrada contra preferências do
usuário, nem uma nota universal de qualidade. A revisão visual e os testes
funcionais têm papéis distintos.

## Rodada 1

**Veredito:** melhora significativa, mas precisava de uma correção de orientação.

Melhorias observadas:

- Cartas com ranks e naipes explícitos e quatro cores.
- Separação entre nome, stack e ação nos assentos.
- Superfícies neutras e bordas discretas.
- Controles agrupados; compartilhamento e solver fora do transporte de replay.

Problemas prioritários identificados nas capturas:

1. O início do flop dizia “Start of hand”; o resultado não indicava conclusão.
2. Identidade de Hero e destaque da ação atual eram visualmente ambíguos.
3. Histórico sem orientação de street/passo; ausente e inacessível no modo compacto.

Refinamentos adicionais: texto de ações pequeno e cabeçalho de contexto denso.

## Correções da rodada 1

- Status explícito para cartas distribuídas e mão concluída.
- Hero identificado por estrela; ênfase de actor somente em frames de ações reais.
- Histórico com streets, seleção atual e índices exatos de replay.
- Clique no histórico lateral para navegar ao passo e pausar a reprodução.
- Botão **Actions** e atalho **A** para o histórico completo em qualquer largura.
- Texto de ações mais legível e dados do cabeçalho separados por hierarquia.
- Remoção da duplicação visual de blinds causada por flags herdadas em frames de
  início de street, sem alterar o modelo de mão.

## Rodada 2

**Veredito do avaliador:** pronto para entrega do recorte visual do replayer;
nenhum bloqueio visual de alta severidade demonstrado nas imagens fornecidas.

Resoluções confirmadas visualmente:

- “Flop dealt” corresponde ao board mostrado.
- Resultado marcado como COMPLETE, com o recebimento do pote identificado.
- Histórico lateral mostra a street e o passo atual selecionado.
- O modo compacto tem acesso explícito ao histórico.
- Cabeçalho, controles e assentos permanecem legíveis nas capturas 1280×720 e
  1600×900.

Limitações da evidência:

- Capturas estáticas não provam teclado, seek, sons ou integridade dos valores.
- A segunda rodada mostrou frames de distribuição e resultado, não um frame
  intermediário de ação; a ênfase do actor também precisa de teste/captura específica.
- Uma imagem do histórico aberto foi composta de grabs reais separados porque
  o plugin offscreen não captura a composição de janelas do desktop.

Refinamentos opcionais, sem bloquear este piloto:

- Simplificar a marca decorativa nos versos das cartas sobrepostas.
- Harmonizar ainda mais as linhas do histórico lateral e da janela de Actions.
- Identificar as ações anteriores persistentes nos assentos como contexto histórico.

## Verificação direcionada

Na entrega da segunda rodada, 54 testes direcionados passaram: geometria,
variantes, estados, áudio, controles, status, seleção de histórico e seek.
Os testes mantêm IDs, estados e cálculos do backend como fonte da apresentação.
Correções e verificações finais adicionais serão registradas no commit de QA.

## Reprodução

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python tools/capture_replayer_review.py --out /tmp/replayer-review
```

As capturas usam uma mão pública de teste, sem conectar ao banco pessoal.
