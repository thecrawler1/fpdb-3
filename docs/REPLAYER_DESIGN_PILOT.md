# Replayer: piloto de implementação e revisão visual

## Direção fixa

Uma ferramenta de estudo premium e sóbria: fluxo de revisão do Holdem Manager,
com hierarquia visual, superfícies neutras e densidade do GTO Wizard.

Referências e proposta geral: [UI_MODERNIZATION_PLAN.md](UI_MODERNIZATION_PLAN.md).

Este piloto usa Qt Widgets e o modelo de replay existente. A decisão sobre QML
pode ser tomada depois; a primeira entrega não precisa de uma migração de framework.

## Critérios da revisão

1. **Hierarquia:** contexto da mão, actor, cartas/board, pote e controles reconhecíveis.
2. **Legibilidade:** ranks, stacks e ações claros; nomes longos tratados sem sobreposição.
3. **Composição:** boa área útil em 1280×720; controles agrupados por função.
4. **Consistência:** superfícies, tipografia, espaçamento, raios e estados coerentes.
5. **Baixo ruído:** destaque reservado à ação e à navegação; evitar bordas neon em tudo.
6. **Interação:** ações acessíveis por teclado; seleção, playback e sons preservados.
7. **Integridade:** mesmo modelo, valores, cartas, vencedores e suporte às variantes.

O avaliador deve apontar problemas com a captura/resolução e a região concreta.
Uma nota de beleza isolada não aprova a entrega. A revisão deve distinguir defeitos
observáveis de preferência estética e comparar com a versão anterior.

## Processo simples

1. Capturar a versão atual com uma mão de teste pública.
2. Um agente implementa o recorte, com as referências e os critérios acima.
3. Gerar novamente as capturas reais do Qt.
4. Outro agente, em contexto separado e com acesso somente de leitura, examina
   antes/depois e os critérios; retorna os problemas prioritários.
5. Corrigir os problemas relevantes e executar testes direcionados.
6. Registrar a revisão e publicar commits por subetapa.

Limite operacional inicial: duas rodadas de revisão para este recorte. Se não
houver progresso claro, registrar o ponto e pedir feedback do usuário. Esse limite
é uma escolha de escopo, não um número de rodadas validado por pesquisa.

A avaliação independente é uma revisão assistida por IA, ainda não calibrada
contra preferências humanas. A aprovação estética final pertence ao usuário.

## Capturas reproduzíveis

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python tools/capture_replayer_review.py --out /tmp/replayer-review
```

O script usa uma fixture pública com jogadores fictícios e não conecta ao banco
pessoal. Captura preflop compacto, ação do Hero, flop com área ampla e resultado compacto.
`manifest.json` registra dimensões pedidas/reais e estado de cada imagem.

## Commits do piloto

- Preparação: critérios e captura reproduzível.
- Implementação: layout e linguagem visual do replayer.
- Revisão: ajustes a partir das capturas e avaliação independente.
- Verificação: testes direcionados e registro do resultado, quando necessário.
