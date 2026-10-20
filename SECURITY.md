# Segurança e exposição histórica

O código original continha três URLs PostgreSQL com credenciais e cinco caminhos
Windows pessoais. Na auditoria direcionada de dez commits, cinco continham URL
de banco com credencial. Valores não são reproduzidos. A busca de nomes não
encontrou .env/token*.json versionados, mas isso não prova ausência de outros segredos.

Corrigir a versão atual não revoga credenciais nem remove versões antigas.
Não houve uso, rotação, revogação, reescrita histórica ou remoção de caches nesta
entrega. Contas da antiga empresa devem ser tratadas por seus administradores.
Não usar essas contas, testar as senhas publicadas ou compartilhar clones/backups
do estado anterior. Limpeza histórica depende de autorização separada.

## Execução explícita

- A demonstração utiliza somente dados e serviços fictícios e PostgreSQL local.
- Importar módulos não abre navegador, inicia subprocesso ou consulta serviços.
- HTTPClient bloqueia rede por padrão. Comandos collect/sync/refresh/watch exigem
  --allow-live; somente usar em contas próprias e autorizadas.
- A CLI init inicializa um PostgreSQL explicitamente configurado, sem API externa.
- Variáveis estão em .env.example. Caminhos relativos partem da raiz do projeto.
- Erros, logs e notificações não incluem senha, URL de conexão, corpos HTTP,
  nomes de clientes, caminhos de arquivos ou traceback externo.
- Slack usa somente mensagens fechadas para eventos de refresh. Nenhuma mensagem
  foi enviada a terceiros durante os testes e a preparação.

## OAuth

Tokens continuam sendo segredos locais em JSON, não criptografados pelo projeto.
Use uma pasta privada, permissões restritas e ACLs adequadas no Windows.
Arquivos temporários usam permissões restritas onde o sistema as suporta; isso
não substitui ACLs da pasta no Windows. Não há gerenciador de segredos implantado.

Uma trava exclusiva protege leitura/rotação/escrita do mesmo arquivo. Antes do
POST, grava rotation_pending. A rotação só volta a ready quando ambos os tokens
e a validade foram persistidos atomicamente. Se houver queda, timeout ou falha
de disco, não repete cegamente a rotação com refresh antigo. Recuperar por fluxo
autorizado e provisionar token válido; nunca editar ready sem verificar o estado.

Locks não têm expiração automática. Depois de crash, inspecionar se o processo
encerrou antes de remover um lock local, sem reutilizar sessões de terceiros.
Não há comando para capturar ou recuperar token de conta corporativa antiga.

## Banco, dados e navegador

O DDL não cria usuários/senhas ou concede superusuário. Inicialização exige um
proprietário de schema; produção deve separar esses privilégios dos de execução.
Migração de esquema existente, backups, TLS e monitoramento produtivo não estão
implantados pela demo.

Não versionar .env, arquivos de token, dados reais, exportações, logs, perfil
Chrome ou diretórios PostgreSQL. O .gitignore ajuda a evitar acidentes, sem ser
uma garantia contra publicação indevida. Planilhas podem conter dados financeiros
e pessoais mesmo sem credenciais.

Use perfil exclusivo próprio para a RPA. Locks do Chrome são preservados e perfil
em uso causa falha explícita. Não copie sessões autenticadas de outra empresa.

Testes PostgreSQL exigem marcação explícita, usuário auto_test e host local.
Criam/apagam apenas nomes gerados por eles. A demo aceita automacao_demo ou
automacao_demo_* local, sem query na URL. Esses nomes são guardas contra acidentes,
não uma fronteira contra configurações maliciosas ou proxy local.

O script portátil usa trust somente no cluster temporário fictício, encerra-o
no final e não instala serviço Windows. Essa configuração não é de produção.
