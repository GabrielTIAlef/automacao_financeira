-- Inicialização em schema af vazio. Não migra tabelas legadas.
CREATE SCHEMA IF NOT EXISTS af;
CREATE TABLE af.schema_version(version integer PRIMARY KEY CHECK(version = 1), ddl_sha256 char(64) NOT NULL);
CREATE TABLE af.execucoes(
 run_id uuid PRIMARY KEY, criado_em timestamptz NOT NULL,
 inicio date NOT NULL, referencia date NOT NULL CHECK(referencia >= inicio),
 contagens jsonb NOT NULL, saldo numeric(18,2) NOT NULL CHECK(saldo >= 0),
 notion_source_id uuid NOT NULL
);
CREATE TABLE af.clientes(
 cliente_id uuid PRIMARY KEY, nome text NOT NULL, documento text, ativo boolean NOT NULL,
 presente boolean NOT NULL, run_id uuid NOT NULL REFERENCES af.execucoes(run_id)
);
CREATE TABLE af."Conta_Azul"(
 recebivel_id uuid PRIMARY KEY, cliente_id uuid NOT NULL REFERENCES af.clientes(cliente_id),
 status text NOT NULL CHECK(status = 'ATRASADO'), total numeric(18,2) NOT NULL CHECK(total >= 0),
 pago numeric(18,2) NOT NULL CHECK(pago >= 0), nao_pago numeric(18,2) NOT NULL CHECK(nao_pago >= 0),
 vencimento date NOT NULL, descricao text, dias_atraso integer NOT NULL CHECK(dias_atraso >= 0),
 run_id uuid NOT NULL REFERENCES af.execucoes(run_id), CHECK(total = pago + nao_pago)
);
CREATE TABLE af."Conta_Azul_Mao"(
 cliente_id uuid PRIMARY KEY REFERENCES af.clientes(cliente_id), page_id uuid NOT NULL UNIQUE,
 fields jsonb NOT NULL, run_id uuid NOT NULL REFERENCES af.execucoes(run_id)
);
CREATE TABLE af.outbox_notion(
 intent_id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES af.execucoes(run_id),
 cliente_id uuid NOT NULL REFERENCES af.clientes(cliente_id), nome text NOT NULL,
 inadimplente boolean NOT NULL, page_id uuid,
 state text NOT NULL CHECK(state IN ('pending','inflight','complete','blocked','ambiguous','superseded')),
 reason text, UNIQUE(run_id, cliente_id)
);
CREATE INDEX ix_outbox_state ON af.outbox_notion(state);
CREATE INDEX ix_outbox_cliente ON af.outbox_notion(cliente_id);
CREATE INDEX ix_recebiveis_cliente ON af."Conta_Azul"(cliente_id);
CREATE VIEW af.inadimplencia_por_cliente AS
SELECT c.cliente_id, c.nome, c.documento, c.ativo,
 count(r.recebivel_id) AS titulos, COALESCE(sum(r.nao_pago),0) AS saldo,
 COALESCE(sum(r.nao_pago),0) > 0 AS inadimplente
FROM af.clientes c LEFT JOIN af."Conta_Azul" r USING(cliente_id)
WHERE c.presente GROUP BY c.cliente_id;
