# Falha de encerramento dos testes Qt na CI

**Estado:** aberto; investigação pausada a pedido do usuário para priorizar o redesign.

**Registro:** 10 de outubro de 2026.

## Resumo

A integração da branch `development` foi aplicada à `personal`, com testes locais,
validação de migração numa cópia do banco e atualização da instalação. Na CI do
fork, a suíte principal executa seus testes com sucesso, mas o processo falha
durante o encerramento nativo do Qt. Isso torna o job vermelho mesmo quando as
asserções passaram.

A causa exata **não foi confirmada**. Em particular, não foi demonstrado que a
origem é o backend de áudio. Mudanças nesse carregamento foram tentadas, mas não
eliminaram a falha em todos os runners.

## Referências para reprodução

- Fork: <https://github.com/thecrawler1/fpdb-3>
- Base upstream: `84213a3e6fa97ff0f0994ae593e08cb4262ef05a`.
- Commit publicado na execução mais recente: `47ecc5a967424ee6e9a15dfdc6e19379108433ff`.
- Primeira execução: <https://github.com/thecrawler1/fpdb-3/actions/runs/38020073223>
- Execução seguinte: <https://github.com/thecrawler1/fpdb-3/actions/runs/38020954985>
- Execução mais recente: <https://github.com/thecrawler1/fpdb-3/actions/runs/38021770345>

Comando da suíte sem interface nos jobs de teste:

```bash
python -m pytest -p no:pytest-qt -m "not qt and not perf" --tb=short
```

Ambiente dos jobs afetados: Python 3.11, PySide6/Qt e demais dependências instaladas
pelo workflow `.github/workflows/ci.yml`. A instalação local usa Python 3.13.16,
PySide6 6.11.1 e as dependências do `uv.lock`, com `uv` 0.12.7.

## Evidências confirmadas

### Linux na CI

O log da execução `38021770345`, job `114124103897`, registra:

```text
11050 passed, 37 skipped, 1037 deselected, 200 subtests passed
QObject: shared QObject was deleted directly. The program is malformed and may crash.
Segmentation fault (core dumped)
```

Esse job acabou marcado como cancelado na API; o log contém a falha nativa acima.
Portanto, não é correto atribuir seu estado apenas a uma asserção de teste.

### macOS na CI

Na mesma execução, job `114124103958`:

```text
11052 passed, 35 skipped, 1037 deselected, 200 subtests passed
QObject: shared QObject was deleted directly. The program is malformed and may crash.
libc++abi: Pure virtual function called!
Abort trap: 6
Process completed with exit code 134.
```

### Outros resultados da mesma execução

- Quality: aprovado, incluindo Ruff, mypy e Pyright.
- Builds PyInstaller Linux/Windows: aprovados.
- Builds PyOxidizer Linux/Windows/macOS: aprovados.
- Motor de equidade nativo Linux/macOS: aprovado.
- Integração com bancos: aprovada.
- Compilação do interposer SwC nos três sistemas: aprovada.
- Coverage: falhou; o motivo específico desse job não foi analisado separadamente.
- Job de testes Windows: marcado como cancelado na API; esta documentação não
  atribui uma causa nativa específica sem análise do seu log final.
- A verificação de versão de configuração foi ignorada por ser exclusiva de PRs.

A CI como um todo **não está verde**.

### Validação local

- Python 3.13: 11.050 testes principais aprovados, com saída normal do processo,
  inclusive em uma execução sem o plugin `pytest-qt`.
- Suíte Qt/offscreen: 1.022 testes aprovados numa execução completa, mais um teste
  de falha esperada que passou. As correções posteriores de menu foram verificadas
  por testes direcionados adicionais.
- Migração e reconstrução dos cinco subsistemas analíticos: verificadas em uma
  cópia consistente de uma base PokerStars, antes de atualizar o banco em uso.
- Os 68 painéis de estudo NLHE cash executaram sobre os dados migrados.
- Importação incremental, replayer, áudio e geração de dados de compartilhamento
  e revisão preflop foram verificados localmente.

Esses resultados não provam que o encerramento está correto em Python 3.11 ou em
todos os sistemas operacionais.

## Tentativas já realizadas

1. Correções de tipagem dos controles de áudio: quality passou na execução seguinte.
2. O teste de conversão passou a verificar `prepare_sounds()` diretamente,
   sem instanciar o controlador Qt num teste sem interface.
3. A importação de `QtMultimedia` foi adiada até existirem efeitos preparados.
4. Reexecução da suíte local com Python 3.13 e `-p no:pytest-qt`: aprovada,
   mas a execução remota continuou apresentando a falha ao encerrar.
5. Foi preparado um ambiente local Python 3.11 para reproduzir o comportamento.
   Sua execução completa foi interrompida pelo usuário antes da conclusão.
6. Foi experimentado um controlador de áudio sem herança de `QObject`, com os
   efeitos pertencendo diretamente ao widget. Três testes Qt direcionados e as
   verificações de tipo/lint passaram, mas a suíte Python 3.11 não foi concluída.
   Essa alteração experimental não foi publicada e foi retirada do diretório de
   trabalho ao pausar a investigação, preservando o código do commit publicado.

## Hipóteses a investigar

- Ordem de destruição de objetos Qt/Shiboken na finalização do interpretador.
- Objetos ou wrappers Qt mantidos globalmente por testes, mocks ou fixtures.
- Diferenças de coleta/finalização entre Python 3.11 e Python 3.13.
- Interação entre a coleta dos testes gráficos, o plugin desativado e objetos Qt
  criados em testes não marcados como `qt`.

Nenhuma dessas hipóteses deve ser tratada como causa confirmada.

## Próximos passos quando a investigação for retomada

1. Reproduzir localmente com Python 3.11 e dependências equivalentes às do runner.
2. Reduzir o conjunto de testes até obter um caso mínimo que preserve a falha no
   encerramento; comparar também com o upstream sem personalizações.
3. Obter uma pilha nativa no momento da destruição que provoca SIGSEGV/SIGABRT.
4. Verificar propriedade, referências e descarte dos objetos envolvidos.
5. Corrigir o ciclo de vida e executar o caso mínimo e a suíte apropriada.
6. Só considerar resolvido quando os processos terminarem com código zero e os
   jobs correspondentes passarem. Não mascarar a falha com `os._exit`, ignorar o
   código de saída ou remover os testes que a revelam.
