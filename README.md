# Automação Financeira BI

Projeto de automação financeira com integração entre Conta Azul, Excel, PostgreSQL, Notion, Power BI e RPA.

## Problema

A empresa precisava acompanhar inadimplência e informações financeiras com atualização automática, combinando dados da API Conta Azul com informações manuais controladas em Excel.

## Solução

Foi criada uma rotina em Python para extrair dados da Conta Azul, tratar recebíveis vencidos, cruzar informações com bases manuais, atualizar o PostgreSQL e alimentar dashboards no Power BI.

## Arquitetura

Conta Azul API / Excel  
→ Python ETL  
→ PostgreSQL / Notion  
→ Power BI  
→ Selenium RPA  
→ Slack Alerts

## Stack

- Python
- Pandas
- Requests
- SQLAlchemy
- PostgreSQL
- Excel
- Selenium
- Watchdog
- Power BI
- Notion API

## Componentes

- `conta_azul.py`: extrai contas a receber e clientes da Conta Azul.
- `inadimplencia.py`: trata e estrutura dados de inadimplência.
- `observer_excel.py`: monitora alterações em arquivos Excel.
- `rpa_powerbi.py`: atualiza o dataset no Power BI.

## Resultados

- Acompanhamento de clientes inadimplentes.
- Integração entre base automática e controle manual.
- Atualização automática dos painéis.
- Redução de retrabalho na cobrança.
- Maior visibilidade para o time financeiro e atendimento.

## Segurança

Credenciais, tokens, dados reais e arquivos internos foram removidos.
