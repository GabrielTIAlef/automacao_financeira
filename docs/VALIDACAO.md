# Profissionalização — evidências e limites

Data: 20/10/2026.
Base inspecionada: main em 4af1c848ee4eb74dea935bad61750beb8039a06f.
Estado: proposta em branch para revisão; integração na main e reescrita histórica não realizadas.

## Implementação realizada

- Removidas URLs de banco com senha, caminhos pessoais e configuração copiada de
  outro projeto. .env.example agora cobre as variáveis utilizadas.
- Entrypoints mantidos sem efeitos na importação, sem subprocesso implícito e com
  execução real somente por comando explícito. Não se usa python genérico para RPA.
- HTTP com timeout, destinos permitidos, redirecionamento bloqueado, contratos e
  retries limitados de 429 apenas para operações seguras.
- OAuth compartilhado com Basic auth, lock, escrita atômica e estado de recuperação.
- Cliente Notion versionado por data_source_id e conciliação por Cliente_ID, não nome.
- Validação de UUID, dinheiro, datas, identidades, cardinalidade e completude.
- Snapshot local com DDL, constraints, reconciliação e advisory lock PostgreSQL.
- Ledger e outbox na transação local, com estados de entrega e de ambiguidade.
- Destino Notion vinculado ao lote, impedindo redirecionar fila com outra configuração.
- Excel preparado antes da carga, manifesto por último e falha após commit explícita.
- Observador com worker único, retomada de falhas, hashes após sucesso e polling
  de segurança. RPA em função run, sem apagar locks ou presumir refresh concluído.
- Notificações sanitizadas e opcionais. Nenhuma mensagem real foi enviada.
- Dados/HTTP/browser fictícios, script de PostgreSQL temporário e lockfile próprio.
- Workflow GitHub Actions preparado e validado com actionlint 1.7.12, sem
  ShellCheck/pyflakes. Ainda não executado no GitHub nesta etapa local.
- README consolidado com história profissional, limites e competências; contrato,
  segurança e reprodução documentados sem restaurar arquivos privados.

## Testes executados

Ambiente: Windows x86-64, Python 3.12.14, PostgreSQL 18.6.
A suíte foi desenvolvida por etapas. A primeira versão completa passou com 64
testes. Após acrescentar a proteção de destino e seu teste, a suíte atual passou
com **65 testes, zero falhas, zero erros e zero casos ignorados** na instalação
nova por requirements.txt. Demonstração concluída e servidor encerrado.

O segundo ambiente vazio, instalado por requirements-lock.txt, também aprovou
os 65 testes, sem falhas, erros ou omissões. A demonstração terminou com sucesso
e o PostgreSQL foi encerrado. As versões instaladas coincidem; pip check passou
nos dois ambientes. Tempos observados das suítes atuais: 51.380s e 52.304s, sem
caracterizar benchmark do ETL em produção.

Composição atual: **41 testes de contrato/HTTP/OAuth/monitor/RPA e 24 PostgreSQL**.
Não foi medida cobertura percentual; quantidade de testes não equivale a cobertura total.

### Cenários relevantes

- Homônimos preservados por UUID, documentos com zeros e dinheiro decimal.
- Consultas paginadas completas, contratos inválidos, limites e cursores repetidos.
- Zero recebíveis válido, flags falsas na cobertura e preservação após falha de fonte.
- Rotação token persistida, falha/timeout ambíguos e bloqueio de refresh antigo.
- Lock concorrente e preservação de arquivo/token/perfil alheio.
- Mudança durante execução, retry sem novo evento, hashes após sucesso e fallback.
- RPA com driver fake: clique, fechamento, timeout, dataset ausente e status requested.
- SQL/FK, reconciliação e rollback de snapshots, lote e outbox.
- Falha de arquivos após commit sinalizada como banco_confirmado=True.
- Entrega Notion idempotente após sucesso, sem sobrescrever campos manuais.
- Criação seguida de timeout, estado inflight de crash e recuperação por ID.
- Página conhecida desaparecida e configuração de destino alterada bloqueadas.
- Demonstração por CLI em banco exclusivo, com HTTP e navegador fictícios.

Resultados: [evidence/validacao_local.json](evidence/validacao_local.json).
Instalação: [REPRODUCAO.md](REPRODUCAO.md).
Os testes provocam falhas controladas para verificar recuperação. Erros esperados
nesses cenários não representam falha da suíte.

## Decisões e compatibilidade

O contrato novo exige mapeamento por UUID no Notion e schema af versionado.
Não migra tabelas antigas ou páginas por nome. Os arquivos antigos permanecem
como wrappers, mas sua execução passa a exigir argumentos e configurações explícitas.

Zero recebíveis não é erro de extração. A base cadastral vazia é bloqueada por
segurança. A aplicação preserva manuais e não tenta reimplementar macros de
restituição, dashboards ou fórmulas corporativas não publicados.

Não há exatamente uma transação para todos os sistemas. Ledger e outbox descrevem
o que foi confirmado localmente e o que ainda exige entrega/reconciliação externa.

## Segurança e pendências

1. Publicar e abrir proposta somente após autorização do usuário.
2. Confirmar primeira execução no GitHub/Linux após publicação.
3. Integrar na main somente após autorização específica e CI satisfatório.
4. Credencial no histórico original continua exposta: corrigir a versão atual
   não apaga commits, revoga credenciais ou remove caches. Etapa separada autorizada.
5. Nenhum sistema, banco, arquivo ou navegador corporativo foi acessado. Não houve
   homologação de APIs reais, migração produtiva, benchmark de escala ou teste macOS.
6. O token store é local e não criptografado pelo projeto. ACLs, secret manager,
   papéis de produção, TLS, backup e monitoramento produtivo não são implantados.
7. O CI não faz deploy nem configura regras obrigatórias de merge.
8. O monitor não persiste sua fila entre reinícios e não substitui um agendador durável.
9. Configurar uma conta/banco por execução; não é serviço multiempresa com isolamento de tenants.

## Prontidão

A entrega local corrige as falhas impeditivas e apresenta uma demonstração
reproduzível da integração sem contas reais. Está em revisão; a publicação e a
validação remota ainda não estão concluídas. Não descrever como homologada em produção.
