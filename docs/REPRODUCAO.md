# Reprodução sem contas corporativas

Ambiente local de referência: Windows x86-64, Python 3.12.14 e PostgreSQL 18.6.
Sem credenciais Conta Azul, Notion, Slack ou Power BI. Fakes não usam sockets e a
demo bloqueia requests real por guarda adicional.

## Instalação nova

Na raiz, com Python 3.12 no PATH:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip check
```

O lockfile foi gerado pelo ambiente instalado. Downloads de dependências exigem
rede; execução da demonstração não consulta APIs externas.

## Testes sem banco

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/run_tests.py
```

Casos PostgreSQL são informados como ignorados; isso não equivale à suíte completa.
O modo --require-postgresql retorna falha se houver casos ignorados.

## Suíte completa e demonstração

Obtenha os binários portáteis Windows pela [página do PostgreSQL](https://www.postgresql.org/download/windows/)
e pelo distribuidor [EDB](https://www.enterprisedb.com/download-postgresql-binaries).
Extraia o pacote completo em .local-test/runtime/, contendo pgsql/bin/initdb.exe,
pg_ctl.exe e postgres.exe. Não há download de PostgreSQL no script.

```powershell
$PgBin = (Resolve-Path '.local-test\runtime\pgsql\bin').Path
.\.venv\Scripts\python.exe -X utf8 scripts/validate_postgres.py --pg-bin "$PgBin" --demo
```

O script cria cluster novo, escuta em 127.0.0.1 com porta livre, usa auto_test com
trust somente em ambiente fictício e encerra o servidor no final. Não instala
serviço Windows. Cada caso de integração cria/apaga banco exclusivo.

O runner remove variáveis de integrações herdadas antes de iniciar os testes.
Os testes não leem contas corporativas. A demo ainda usa uma guarda que impede
HTTP real e injeta navegador e serviços fictícios.

Artefatos locais, não versionados:

```text
data/demo/inadimplencia.xlsx
data/demo/latest_run.json
.local-test/last_validation.json
.local-test/automacao_pg_*/tests.log
.local-test/automacao_pg_*/demo.log
```

A amostra tem três clientes, dois deles homônimos, dois recebíveis vencidos,
saldo de 130.00 e uma página Notion inicial com campos manuais. Gera três
intenções e simula sua entrega. A RPA usa driver fake e retorna requested,
completion_verified=False. Não há navegador autenticado, mensagem Slack ou API real.

O JSON local do pipeline registra local_complete e queued_not_sent porque é
publicado antes da entrega separada; o stdout final da demo inclui notion_fake
e powerbi_fake. A demo não altera esse manifesto para simular uma atomicidade
entre sistemas que não existe.

O Excel tem abas Recebiveis, Clientes e Controle_Manual. Dinheiro é exportado como
texto decimal e documentos/UUIDs permanecem texto. A ausência de recebíveis mantém
as colunas de cabeçalho. A demo não distribui planilhas ou macros empresariais.

## Demo em outro banco fictício local já criado

```powershell
$env:AUTO_DEMO_DATABASE_URL = 'postgresql+psycopg2://USUARIO_LOCAL@127.0.0.1:PORTA/automacao_demo'
.\.venv\Scripts\python.exe -X utf8 scripts/run_demo.py
```

Somente automacao_demo ou automacao_demo_* em host local, sem parâmetros de query.
Esse comando inicializa e grava dados fictícios no banco escolhido; não usar
banco que contenha dados a preservar. Contas e criação do banco são explícitas.

## Comandos de adaptação para conta própria autorizada

Não são necessários para a demo e não foram executados com contas reais.
Configurar .env local pelo .env.example, provisionar token sob sua autorização e
adaptar o data source conforme [CONTRATO_DADOS.md](CONTRATO_DADOS.md).

```powershell
.\.venv\Scripts\python.exe src/cli.py init
.\.venv\Scripts\python.exe src/cli.py collect --allow-live --start 2026-01-01 --reference 2026-01-31
.\.venv\Scripts\python.exe src/cli.py sync --allow-live
.\.venv\Scripts\python.exe src/cli.py refresh --allow-live
.\.venv\Scripts\python.exe src/cli.py watch --allow-live
```

collect lê fontes, publica no banco/arquivos e enfileira Notion sem enviar escritas
ao Notion. Ele usa OAuth e leitura externa apenas após --allow-live.
sync é outra ação explícita. refresh/watch são independentes da extração.
O observador usa WATCH_FILE_1/2 e intervalos configurados em .env.example.

Os arquivos de entrada antigos continuam como wrappers para esses mesmos comandos:
ContaAzul.py/inadimplencia.py direcionam collect, observador_excel.py direciona
watch e RPA_Gestao_Financeira.py direciona refresh. Exigem os mesmos argumentos.
Importá-los não executa integrações. Não há subprocesso python implícito.

## GitHub Actions

O workflow preparado usa Ubuntu 24.04, Python 3.12 e PostgreSQL 18 descartável,
dependências fixadas e testes sem contas corporativas. Executa em propostas e
pushes para main, com permissão de leitura e ações fixadas por commit.
Não faz deploy, não configura proteção de branch e não usa secrets corporativos.
A primeira execução remota depende de autorização para publicar esta entrega.
