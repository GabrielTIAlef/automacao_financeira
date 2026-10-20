# Contrato demonstrativo e efeitos externos

## Identidade e cobertura

Clientes e recebíveis usam UUIDs estáveis da origem. Nomes são atributos de
apresentação, nunca chaves. Clientes homônimos com UUIDs distintos permanecem
distintos. Documento é texto, preservando zeros. Uma carga exige cadastro não
vazio e IDs únicos, sem recebível sem correspondência cadastral.

A consulta abrange recebíveis com status ATRASADO, vencimento entre início e
referência explícitos, inclusive. Sim/Não significa saldo vencido positivo nessa
janela e nessa origem, não ausência de qualquer dívida fora da cobertura.
Clientes ativos e inativos são mantidos conforme a flag booleana da origem.

Zero recebíveis é válido somente após paginação completa e reconciliação com o
total anunciado. Resposta sem coleção, sem total ou com página/cursor repetido
é erro. Mudança no total durante a coleta bloqueia a publicação. Isso reduz
inconsistências, mas a API não oferece uma transação de snapshot entre páginas:
alterações que preservem a contagem podem exigir coleta em janela controlada.

## Tipos

- IDs: UUID textual normalizado, obrigatório.
- Nome: texto não vazio, sem controles; preservado para apresentação.
- Documento: texto ou nulo, até 30 caracteres, nunca convertido em número.
- Datas: ISO AAAA-MM-DD ou objeto date sem horário; data inválida não vira nulo.
- Dinheiro: Decimal e NUMERIC(18,2), sem arredondamento silencioso. Aceita ponto
  decimal ou BRL com vírgula e duas casas, como R$ 1.234,56. Não finitos são rejeitados.
- Recebível: total, pago e não pago obrigatórios e não negativos, total = pago + saldo.
- Dias de atraso: derivados da data de referência, sem depender do relógio dos testes.
- Exportação Excel: valores monetários em texto decimal para preservar precisão;
  strings potencialmente interpretadas como fórmulas são escapadas.

O contrato é da demonstração. Casos reais fora desses limites exigem evolução
explícita, sem dedução de regras privadas da antiga empresa.

## Notion e campos manuais

Usa versão fixada 2025-09-03, data_source_id explícito e propriedade rich_text
Cliente_ID. As páginas gerenciadas precisam apontar para UUID de cliente conhecido.
IDs ausentes, duplicados ou não mapeados interrompem a coleta, sem conciliação por nome.

O título é configurável, padrão Nome. A sincronização atualiza apenas Inadimplente?,
como rich_text Sim/Não. Páginas novas recebem também título e Cliente_ID.
Campos manuais de cobrança/negociação são lidos para o snapshot local e não são
sobrescritos nos PATCHs. Tipos suportados: title, rich_text, select, status e checkbox.
Tipos inesperados não são silenciosamente descartados.

O data source de destino é registrado no lote e conferido antes de consultar ou
entregar intenções pendentes. Trocar a configuração não redireciona uma fila antiga
para outro destino; requer reconciliação explícita. Usar um banco por conta autorizada.

Não há migração automática de nomes antigos para UUID, criação automática de
propriedades ou alteração de schema Notion. Configurar o data source é tarefa
explícita em conta própria autorizada, não parte dos testes deste projeto.

## Modelo local

DDL em [sql/001_schema.sql](../sql/001_schema.sql), schema af:

- clientes: cadastro por UUID; flag presente identifica a última coleta. Clientes
  ausentes são mantidos como não presentes para preservar referências do ledger.
- Conta_Azul: snapshot dos recebíveis vencidos na janela, por ID estável.
- Conta_Azul_Mao: snapshot de campos manuais Notion, por cliente, com page_id único.
- execucoes: lote local confirmado, datas, contagens e saldo. Não guarda as versões
  antigas dos recebíveis nem substitui auditoria financeira completa.
- outbox_notion: intenções por lote/cliente, estado e motivo sanitizado.
- inadimplencia_por_cliente: view de clientes presentes, quantidade e saldo.

Snapshot financeiro, cadastro, snapshot manual, lote e intenções são publicados
na mesma transação. Há FKs, checks e reconciliação. Tabelas não são recriadas por
replace. A inicialização recusa objetos legados no schema af e divergência de DDL.
Não migra tabelas antigas no public nem instala papéis ou permissões produtivas.

## Outbox e falhas parciais

Estado das intenções: pending, inflight, complete, blocked, ambiguous ou superseded.
Uma coleta nova substitui intenções pendentes antigas pelo desejo mais recente.
Intenções inflight/ambiguous são preservadas até reconciliação, sem repetir uma
criação que pode já ter ocorrido no servidor.

Antes de escrever, a sincronização relê as páginas e confere identidade única.
Uma criação sem resposta conclusiva permanece ambígua. Se uma consulta posterior
encontrar a página pelo Cliente_ID, uma coleta e sincronização novas podem fazer
PATCH seguro e marcar a intenção antiga como reconciliada/superseded. Sem essa
evidência, a criação fica bloqueada. Página antes conhecida que desapareceu não
é recriada automaticamente.

Não há exactly-once distribuído ou unicidade imposta pelo Notion em Cliente_ID.
O lock serializa executores deste projeto que usam o mesmo banco. Outros sistemas
podem criar páginas concorrentes: as duplicatas devem ser resolvidas explicitamente.
Conexões a outro banco também não compartilham esse lock.

PostgreSQL, Notion, arquivos e Power BI não formam uma transação única. Arquivos
são preparados antes do commit e publicados depois. Uma falha posterior informa
banco_confirmado=True; isso não significa rollback local. O JSON final é publicado
por último, mas cada substituição de arquivo é individual. Leitores devem conferir
o hash do Excel e o run_id; não há leitor externo automático implantado aqui.

## Observador e navegador

O observador solicita refresh após mudança de arquivo, não inicia nova extração.
Um worker serializa todas as execuções e agrupa eventos. Mudança durante uma
execução permanece pendente; falha é tentada novamente com intervalo, sem exigir
outro evento. Hashes são confirmados apenas após sucesso.

Watchdog é complementado por polling de segurança, que continua após falha do
observador. Arquivo ausente/ilegível adia a execução. O shutdown aguarda a tarefa
ativa; não mata threads à força nem anuncia encerramento que não foi confirmado.
O estado do monitor é em memória: ao reiniciar, estabelece uma nova linha de base,
sem fila persistente de eventos anteriores.

A RPA tem função run importável, perfil configurável e trava própria. Não apaga
Singletons do Chrome. Dataset ausente e timeout propagam falha. Retorna requested
com completion_verified=False: clique não comprova conclusão do refresh.

## Contratos HTTP e referências oficiais

Foram consultadas as documentações públicas em 20/10/2026, sem chamar APIs autenticadas:

- [Conta Azul OAuth](https://developers.contaazul.com/authorize-multiple-clients):
  Basic auth e renovação com refresh_token rotacionado.
- [Cadastro atual de pessoas](https://developers.contaazul.com/open-api-docs/open-api-person/v1):
  GET /v1/pessoas, coleção items e totalItems. Diferente do /pessoa legado.
- [Recebíveis](https://developers.contaazul.com/docs/financial-apis-openapi/v1/createreceivablefinancialevent):
  rota de busca de contas a receber, coleção itens e itens_totais.
- [Notion: migração para data sources](https://developers.notion.com/guides/get-started/upgrade-guide-2025-09-03)
  e [consulta](https://developers.notion.com/reference/query-a-data-source).

O adapter aceita uuid/id do cliente quando consistentes, rejeitando conflito.
Respostas reais de uma conta não foram homologadas. Alterações futuras de API
podem exigir adaptação. Documentação e fakes não substituem homologação autorizada.
