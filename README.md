# Automação Financeira BI — Conta Azul + Excel + Power BI + RPA

> 🔹 Sistema completo de automação financeira integrando Conta Azul, PostgreSQL, Excel, Notion, Power BI e RPA para controle de inadimplência, atualização automática de datasets e monitoramento financeiro operacional.

---

# Visão Geral

Este projeto foi desenvolvido para automatizar processos financeiros e operacionais relacionados à gestão de inadimplência, restituições e atualização de informações analíticas em tempo quase real.

A solução integra múltiplas ferramentas corporativas — principalmente Conta Azul, Excel, PostgreSQL, Notion e Power BI — permitindo centralização, automação e acompanhamento operacional do setor financeiro.

O principal objetivo foi reduzir processos manuais, melhorar o acompanhamento de clientes inadimplentes e garantir atualização contínua dos dashboards utilizados pela operação.

---

# Problema de Negócio

A operação financeira precisava acompanhar clientes inadimplentes e informações críticas de forma centralizada, porém enfrentava alguns desafios:

- Alta dependência de planilhas manuais;
- Falta de atualização automática dos dashboards;
- Necessidade de integrar dados automáticos e controles manuais;
- Necessidade de atualização constante das informações;
- Dificuldade de acompanhar mudanças em arquivos operacionais;
- Necessidade de baixo custo operacional;
- Necessidade de atualização quase instantânea.

Além disso, existia a necessidade de:

- Integrar a API do Conta Azul;
- Permitir alimentação manual de dados operacionais;
- Atualizar automaticamente os dashboards do Power BI;
- Garantir consistência entre informações automáticas e manuais;
- Automatizar notificações e monitoramento operacional.

---

# Arquitetura da Solução

```txt
Conta Azul API / Excel / Notion
                ↓
           Python ETL
                ↓
           PostgreSQL
                ↓
            Power BI
```

---

# Componentes Técnicos

## `conta_azul.py`

Script principal responsável pela integração com a API do Conta Azul.

A solução realiza autenticação OAuth2, coleta dados financeiros, trata recebíveis em atraso e estrutura informações para análise operacional e financeira.

### Principais responsabilidades:
- Renovar automaticamente tokens OAuth2;
- Buscar contas a receber em atraso;
- Buscar clientes ativos e inativos;
- Tratar e normalizar dados financeiros;
- Integrar dados financeiros com PostgreSQL;
- Atualizar informações no Notion;
- Preparar dados para consumo no Power BI.

### Principais funções:
- `renovar_access_token()`
- `buscar_contas_a_receber()`
- `buscar_clientes()`
- `comparar_nomes()`
- `comparacao_notion()`
- `conectar_banco()`

### Tecnologias utilizadas:
- `requests`
- `pandas`
- `sqlalchemy`
- `json`
- `numpy`

---

## `inadimplencia.py`

Script responsável pelo tratamento e estruturação analítica das informações financeiras.

A solução consolida os dados vindos da API do Conta Azul e integra informações alimentadas manualmente para permitir gestão operacional de inadimplência.

### Principais responsabilidades:
- Estruturar base analítica;
- Normalizar informações financeiras;
- Consolidar informações de inadimplência;
- Criar dataset para o Power BI;
- Integrar dados automáticos e manuais;
- Garantir consistência operacional.

### Tecnologias utilizadas:
- `pandas`
- `sqlalchemy`
- `openpyxl`

---

## `observer_excel.py`

Script responsável pelo monitoramento automático de arquivos Excel utilizados pela operação financeira.

A solução utiliza Watchdog para detectar alterações nos arquivos e iniciar automaticamente os processos de atualização.

### Principais responsabilidades:
- Monitorar arquivos críticos;
- Detectar modificações automaticamente;
- Identificar mudanças via hash SHA-256;
- Controlar múltiplas execuções simultâneas;
- Executar atualização automática do Power BI;
- Enviar notificações via Slack;
- Trabalhar com fallback por polling.

### Principais funções:
- `file_hash()`
- `DebouncedRunner()`
- `MultiFileHandler()`
- `start_watchdog()`
- `start_polling()`

### Tecnologias utilizadas:
- `watchdog`
- `threading`
- `hashlib`
- `selenium`
- `slack webhook`

---

## `rpa_powerbi.py`

RPA desenvolvida utilizando Selenium para atualização automática dos datasets do Power BI Web.

A automação executa interações diretamente no navegador em modo headless, simulando o clique de atualização nos conjuntos de dados financeiros.

### Principais responsabilidades:
- Abrir Power BI Web;
- Localizar datasets financeiros;
- Atualizar dashboards automaticamente;
- Trabalhar em modo headless;
- Enviar alertas de erro e sucesso;
- Automatizar atualização operacional.

### Tecnologias utilizadas:
- `selenium`
- `webdriver`
- `slack webhook`

---

# Soluções Desenvolvidas

## Gestão de Inadimplência

Painel voltado ao acompanhamento operacional e financeiro de clientes inadimplentes.

### Principais análises:
- Clientes inadimplentes;
- Valores em atraso;
- Tempo de atraso;
- Histórico de inadimplência;
- Situação operacional;
- Acompanhamento de cobranças.

---

## Gestão de Restituições

Controle operacional de restituições financeiras alimentado por Excel integrado ao Power BI.

### Principais análises:
- Valores pendentes;
- Restituições concluídas;
- Fluxo operacional;
- Acompanhamento temporal;
- Gestão operacional do financeiro.

---

## Integração Manual + Automática

Uma das principais necessidades do projeto foi combinar:

- Base automática vinda da API do Conta Azul;
- Dados operacionais alimentados manualmente;
- Estrutura consistente sem quebra de relacionamento.

Para resolver isso, foi criada uma estrutura dividida entre:
- tabela fato;
- tabela dimensão;
- macros de verificação;
- controle de nomes ausentes, novos e retornados.

---

# Resultados Obtidos

| Métrica | Antes | Depois |
|---|---|---|
| Atualização dos dashboards | Manual | Automatizada |
| Dependência operacional | Alta | Reduzida |
| Tempo de atualização | Alto | Quase instantâneo |
| Gestão de inadimplência | Fragmentada | Centralizada |
| Controle operacional | Manual | Automatizado |
| Atualização Power BI | Manual | Automática |

---

# Stack Utilizada

## Dados & Engenharia
- Python
- PostgreSQL
- SQLAlchemy
- Pandas
- APIs REST
- ETL / ELT

## BI & Analytics
- Power BI
- DAX
- Dashboards Financeiros
- Modelagem Relacional

## Automação
- Selenium
- Watchdog
- RPA
- Slack Webhooks
- Windows Task Scheduler

## Integrações
- Conta Azul API
- Notion API
- Excel
- Dropbox

---

# Estrutura do Projeto

```txt
automacao-financeira-bi/
│
├── src/
│   ├── extract/
│   ├── transform/
│   ├── automation/
│   └── utils/
│
├── docs/
├── samples/
│
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

# Segurança

Para publicação pública deste projeto:

- Tokens foram removidos;
- Credenciais foram ocultadas;
- Webhooks foram sanitizados;
- Dados reais foram substituídos por exemplos;
- Informações sensíveis não foram incluídas.

---

# Aprendizados e Competências Desenvolvidas

Durante o desenvolvimento deste projeto foram trabalhados temas como:

- Integração de APIs;
- Engenharia de dados;
- ETL;
- Automação operacional;
- Atualização automatizada de dashboards;
- Monitoramento de arquivos;
- Integração entre sistemas;
- Estruturação analítica;
- Business Intelligence;
- Modelagem relacional;
- Gestão operacional financeira.
