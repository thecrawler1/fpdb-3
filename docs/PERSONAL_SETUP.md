# Personalizações do FPDB

Este fork mantém as personalizações na branch `personal`, baseada inicialmente
na versão upstream **v3.9.1**.

A integração de 9 de outubro de 2026 incorpora a `development` até o commit
`84213a3e6fa97ff0f0994ae593e08cb4262ef05a` (3 de outubro). Ela inclui Study Explorer,
Research Browser, filtros avançados, análises de sessões, Session Guard, os novos
HUDs e compartilhamento/revisão de mãos, preservando nossos sons. A aplicação
ainda informa `3.9.1`, pois o upstream não publicou uma nova versão; a referência
Git acima identifica precisamente o conjunto de funcionalidades incorporado.

## Alterações

- Efeitos sonoros no hand replayer, com opção **Sound** para ativar/silenciar.
- Preferência de som persistente; volume local fixo em 50%, sem slider.
- Efeitos carregados da instalação local do PokerStars: check, fold, aposta,
  raise, distribuição de cartas, pilha de fichas para all-in e entrega do pote.
- Balanceamento de volume, preservando o timbre e o áudio estéreo.
- Sons ao avançar manualmente. Voltar e saltar na linha do
  tempo não reproduz uma sequência de efeitos; fechar o replayer interrompe o áudio.
- Comando de abertura, importador de mãos e atalho Linux reproduzíveis.
- Controles manuais por ícones, tipografia ampliada e opção de valores em BB.
- Fichas por denominação e potes físicos separados das apostas em andamento;
  veja [REPLAYER_MANUAL_CONTROLS.md](REPLAYER_MANUAL_CONTROLS.md).
- Apostas ancoradas ao dono, fichas maiores com denominações impressas e cartas
  completas da instalação local; veja [REPLAYER_POKERSTARS_CARDS.md](REPLAYER_POKERSTARS_CARDS.md).
- Faixa de decisão do Hero no topo, mesa e comandos embaixo; SPR por street
  a partir do stack efetivo, pot odds, sizing, MDF puro e FE mínima;
  veja [REPLAYER_DECISION_STRIP.md](REPLAYER_DECISION_STRIP.md).

## Instalação Linux

Pré-requisitos: Git, **`uv` 0.12.7**, compilador C, CMake e `ffmpeg`. Python 3.13 é a versão
usada nesta instalação; `uv` pode baixar o interpretador automaticamente.

```bash
git clone https://github.com/thecrawler1/fpdb-3.git
```

Dentro do diretório do clone:

```bash
git switch personal
uv sync --python 3.13 --extra linux --frozen
```

O ambiente `.venv` pertence a este clone. Se mover o clone, recrie o ambiente e
instale novamente os launchers.

Para executar os testes, inclua as dependências de desenvolvimento:

```bash
uv sync --python 3.13 --extra linux --extra test --frozen
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -m qt
```

A CI do fork também executa nos pushes e pull requests para `personal`.

### Validação da integração

A integração foi validada no Linux com Python 3.13.16 e as dependências exatas
do `uv.lock` (incluindo PySide6 6.11.1):

- Suíte principal: **11.050 testes aprovados**, 37 ignorados e 200 subtestes aprovados.
- Suíte Qt/offscreen: **1.022 testes aprovados**, mais um teste marcado como
  falha esperada que também passou nesta execução.
- Ruff aprovado em `fpdb_3_legacy`, `fpdb`, `test`, `tests` e `tools`.
- Mypy aprovado nos arquivos adaptados de áudio, instalação e preferências do HUD.
- Migração e reconstrução dos cinco subsistemas numa cópia consistente de uma
  base PokerStars NLHE; todos os 68 painéis do pacote de estudos cash executados.
- Abertura do Study Explorer, Research Browser e dashboard, replay de mãos reais,
  carregamento dos sete efeitos de áudio e geração dos dados de compartilhamento
  e revisão preflop.
- Importação incremental validada, com reconhecimento de duplicatas e preservação
  dos IDs das mãos anteriores.

Os testes revelaram uma diferença de métricas de fontes nas preferências do HUD.
O fork corrige o dimensionamento dos botões para permitir uma janela estreita,
mantendo as ações no menu responsivo. Há também um teste de integração específico
para preservar os sons junto dos novos botões de compartilhamento e solver.

O fork também corrige o menu de contexto dos visualizadores de mãos cash e de
torneios: `QContextMenuEvent.globalPos()` substitui a chamada incompatível com
esse evento do Qt. Dois testes usam eventos reais para verificar o menu.

O PreflopAdvisor é um aplicativo externo: a integração e os dados de revisão são
testados aqui; abrir uma análise de solver requer esse aplicativo instalado.

### Atualizar um banco existente

Feche a aplicação e mantenha um backup consistente do banco SQLite e da
configuração antes de executar a versão integrada. A conexão adiciona as novas
tabelas e colunas. Para habilitar os estudos sobre mãos já importadas:

```bash
.venv/bin/python tools/analytics_rebuild.py --config ~/.fpdb/HUD_config.xml --all
.venv/bin/python tools/analytics_rebuild.py --config ~/.fpdb/HUD_config.xml --status
```

Os cinco subsistemas devem indicar `current`. A operação também está disponível
em **Database → Rebuild Analytics Data**. Ela deriva os novos dados a partir das
mãos armazenadas, preservando seus IDs. Não use `--recreate-tables` ao atualizar
um banco existente.

### Configurar o PokerStars

Abra a aplicação uma vez para criar a configuração:

```bash
.venv/bin/fpdb_3_legacy
```

Em `~/.fpdb/HUD_config.xml`, configure o site `PokerStars` (ou use as preferências
de sites na interface):

- `screen_name`: seu nome de jogador.
- `HH_path`: a pasta dos históricos, usando o caminho Linux dentro do prefixo Wine.
- `site_path`: a pasta onde o PokerStars está instalado, usando o caminho Linux.

Exemplo genérico de prefixo Wine:

```text
site_path: ~/.local/share/wineprefixes/pokerstars/drive_c/Program Files (x86)/PokerStars/
HH_path:   ~/.local/share/wineprefixes/pokerstars/drive_c/users/SEU_USUARIO/AppData/Local/PokerStars/HandHistory/SEU_JOGADOR/
```

Substitua `~` pelo caminho absoluto de sua home nos atributos XML. A configuração
real e os dados pessoais ficam fora deste repositório.

Os efeitos são lidos de `site_path/Gx/table-view/audio/`. O `ffmpeg` prepara cópias
PCM no cache `~/.cache/fpdb/replayer-pokerstars-v2/` (ou em `$XDG_CACHE_HOME`).
O primeiro carregamento prepara os arquivos; os seguintes reutilizam o cache.
Mudanças nos arquivos do PokerStars geram novas entradas automaticamente.
Se a instalação ou o áudio não estiver disponível, o replayer continua funcionando
sem os efeitos. Os arquivos originais do PokerStars não são alterados.

Com o deck **colour**, o replayer lê as faces completas de
`site_path/Gx/table-view/cards/default/1440/cache/`, mantendo o verso discreto
do FPDB. Se uma face local estiver indisponível, usa o deck SVG `white` já
distribuído no projeto. Nenhuma carta proprietária é incluída no fork.

### Instalar os comandos e o atalho

```bash
.venv/bin/python tools/install_personal_launchers.py
```

Isso instala:

- `~/.local/bin/fpdb`: abre este clone via X11/XWayland.
- `~/.local/bin/fpdb-import-pokerstars`: importa a pasta definida em `HH_path`.
- `~/.local/share/applications/fpdb.desktop`: atalho **FPDB 3**.

Launchers existentes com conteúdo diferente recebem um backup `.bak.TIMESTAMP`.
O instalador aceita `--config`, `--bin-dir` e `--applications-dir` para outros caminhos.
Inclua `~/.local/bin` no `PATH` para usar os comandos diretamente.

```bash
fpdb
fpdb-import-pokerstars
```

Usamos a instalação pelo código-fonte porque o pacote PyInstaller v3.9.1 apresentou
SIGSEGV neste Arch/Omarchy ao processar eventos de teclado. O core mostrou
`libxkbcommon` do pacote junto com `libxkbcommon-x11` do sistema; a incompatibilidade
entre essas bibliotecas é a causa provável. A instalação pelo código-fonte funcionou
na sessão validada pelo usuário.

## Acompanhar o projeto original

O remoto `origin` aponta para o fork; `upstream`, para o projeto original:

```bash
git remote add upstream https://github.com/jejellyroll-fr/fpdb-3.git
git fetch upstream --tags
```

Execute `remote add` apenas se `upstream` ainda não existir. Mantenha o diretório
de trabalho limpo antes de atualizar. Para adotar uma nova versão publicada:

```bash
git switch personal
git branch backup/personal-before-update
git merge vNOVA_VERSAO
```

Substitua `vNOVA_VERSAO` pela tag desejada e escolha outro nome de backup nas
atualizações seguintes. Resolva eventuais conflitos, atualize as dependências,
teste o replayer e então publique:

```bash
git push origin personal
```

Prefira merge para preservar os commits já publicados. A branch `development`
do upstream pode conter alterações posteriores à última versão publicada.

## Backup e dados locais

O Git registra código, testes e instruções de instalação. Mantenha um backup
separado de `~/.fpdb/` (configuração e banco), dos históricos do PokerStars e das
preferências de áudio em `~/.config/fpdb/replayer.conf`.

As preferências ficam no local escolhido pelo `QSettings`; no Linux o caminho
usual acima respeita `$XDG_CONFIG_HOME`. Os sons do PokerStars são carregados da
instalação local e não fazem parte do fork. O cache pode ser recriado.
