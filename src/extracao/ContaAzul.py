#!/usr/bin/env python
# coding: utf-8

# In[2]:


import requests
import json
import os
import re
import time
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from openpyxl import load_workbook  # opcional
from sqlalchemy import create_engine, text
from sqlalchemy import String, Numeric, Date, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from zoneinfo import ZoneInfo  # fuso
import json
from dotenv import load_dotenv

load_dotenv()

TZ_BR = ZoneInfo("America/Sao_Paulo")

# Dados Conta Azul
client_id = os.getenv("client_id")
client_secret = os.getenv("client_secret")
token_url = "https://auth.contaazul.com/oauth2/token"

# Diretório log
try:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    BASE_DIR = os.getcwd()

# Token Conta Azul
TOKEN_PATH = r"C:\Users\Gabriel Alef\Projeto\Script\token.json"
token_file = TOKEN_PATH
def carregar_token():
    if os.path.exists(token_file):
        with open(token_file, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        raise Exception(f"Arquivo de token não encontrado em: {token_file}")
def salvar_token(data):
    os.makedirs(os.path.dirname(token_file), exist_ok=True)
    with open(token_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
def renovar_access_token():
    token_data = carregar_token()
    refresh_token = token_data["refresh_token"]
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret
    }
    response = requests.post(token_url, data=data)
    if response.status_code == 200:
        novo_token = response.json()
        salvar_token({
            "access_token": novo_token["access_token"],
            "refresh_token": novo_token.get("refresh_token", refresh_token)
        })
        return novo_token["access_token"]
    else:
        raise Exception(f"Erro ao renovar access_token: {response.text}")
        
# Busca de dados Conta Azul
def buscar_contas_a_receber(access_token):
    url = "https://api-v2.contaazul.com/v1/financeiro/eventos-financeiros/contas-a-receber/buscar"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    query_base = {
        "tamanho_pagina": "100",
        "data_vencimento_de": "2018-01-01",
        "data_vencimento_ate": datetime.today().strftime("%Y-%m-%d"),
        "status": "ATRASADO"
    }
    tudo, pagina = [], 1
    while True:
        query = query_base.copy()
        query["pagina"] = str(pagina)
        r = requests.get(url, headers=headers, params=query)
        if r.status_code != 200:
            raise Exception(f"Erro página {pagina}: {r.text}")
        data = r.json()
        itens = data.get("itens", [])
        if not itens:
            break
        tudo.extend(itens)
        pagina += 1
    return pd.DataFrame(tudo)
def buscar_clientes(access_token):
    url = "https://api-v2.contaazul.com/v1/pessoa"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    query_base = {"tamanho_pagina": "100", "tipo_perfil": "CLIENTE", "status": "TODOS"}
    tudo, pagina = [], 1
    while True:
        query = query_base.copy()
        query["pagina"] = str(pagina)
        r = requests.get(url, headers=headers, params=query)
        if r.status_code != 200:
            raise Exception(f"Erro página {pagina}: {r.text}")
        data = r.json()
        itens = data.get("itens", [])
        if not itens:
            break
        tudo.extend(itens)
        pagina += 1
    return pd.DataFrame(tudo)

# União das bases do Notion e Conta Azul
def comparar_nomes(df_final, df_unico):
    set_final = set(df_final["Nome"].dropna().astype(str)) 
    if isinstance(df_unico, pd.DataFrame):
        col = df_unico.columns[0]
        set_unico = set(df_unico[col].dropna().astype(str))
    else:
        set_unico = set(pd.Series(df_unico).dropna().astype(str))
    todos = set_final.union(set_unico)
    df_out = pd.DataFrame({"Nome": list(todos)})
    df_out["Inadimplente?"] = np.where(df_out["Nome"].isin(set_final), "Sim", "Não")
    return df_out.drop_duplicates(subset=["Nome"]).reset_index(drop=True)

#API Notion
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("DATABASE_ID")
NOTION_VERSION = "2022-06-28"
PG_CONN_STR  = "postgresql+psycopg2://postgres:123456@localhost:5432/ProjetoImport"
PG_TABLE     = "Conta_Azul"
headers_notion = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_VERSION,
}

TITLE_PROP_OVERRIDE = os.getenv("NOTION_TITLE_PROP") or None  # ex.: "Nome"

# Normaliza UUID hifenizado
def _normalize_notion_id(x: str) -> str:
    s = str(x or "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", s):
        return s
    u = re.sub(r"[^0-9a-fA-F]", "", s)
    if len(u) == 32:
        return f"{u[0:8]}-{u[8:12]}-{u[12:16]}-{u[16:20]}-{u[20:32]}"
    return s

def _req_notion(method, url, **kw):
    r = requests.request(method, url, headers=headers_notion, timeout=30, **kw)
    if r.status_code >= 400:
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        raise RuntimeError(f"Notion API error {r.status_code} @ {url}\nDetail: {detail}")
    return r

def ensure_notion_ready(database_id: str):
    _req_notion("GET", "https://api.notion.com/v1/users/me")
    dbid = _normalize_notion_id(database_id)
    meta = _req_notion("GET", f"https://api.notion.com/v1/databases/{dbid}").json()
    return dbid, meta

# Detecção de título
def get_title_prop_name_from_meta(db_meta: dict) -> str | None:
    props = (db_meta.get("properties") or {})
    for k, v in props.items():
        t = v.get("type")
        if t == "title":
            return k
        if isinstance(v, dict) and "title" in v:
            return k
    return None

def detect_title_property(database_id: str, db_meta: dict | None = None) -> str:
    dbid = _normalize_notion_id(database_id)
    if db_meta is None:
        db_meta = _req_notion("GET", f"https://api.notion.com/v1/databases/{dbid}").json()
    name = get_title_prop_name_from_meta(db_meta)
    if name:
        return name

    r = _req_notion("POST", f"https://api.notion.com/v1/databases/{dbid}/query", json={"page_size": 1}).json()
    results = r.get("results", [])
    if results:
        props = (results[0].get("properties") or {})
        for k, v in props.items():
            if v.get("type") == "title" and isinstance(v.get("title"), list):
                return k
            if isinstance(v, dict) and isinstance(v.get("title"), list):
                return k

    if TITLE_PROP_OVERRIDE:
        return TITLE_PROP_OVERRIDE

    keys = list((db_meta.get("properties") or {}).keys())
    raise RuntimeError(
        "Não foi possível detectar a propriedade de título automaticamente. "
        "O database pode estar vazio. "
        "Defina TITLE_PROP_OVERRIDE (ex.: 'Nome') ou exporte manualmente uma página primeiro. "
        f"Propriedades vistas no schema: {keys}"
    )

def notion_retrieve_database(database_id):
    dbid = _normalize_notion_id(database_id)
    r = _req_notion("GET", f"https://api.notion.com/v1/databases/{dbid}")
    return r.json()

def notion_ensure_property_rich_text(database_id, prop_name):
    dbid = _normalize_notion_id(database_id)
    meta = notion_retrieve_database(dbid)
    props = meta.get("properties", {}) or {}
    if prop_name in props:
        return
    body = {"properties": {prop_name: {"rich_text": {}}}}
    _req_notion("PATCH", f"https://api.notion.com/v1/databases/{dbid}", json=body)

def notion_query_by_title(database_id, title_prop, title_value):
    if not title_value or str(title_value).strip() == "":
        return None
    dbid = _normalize_notion_id(database_id)
    url = f"https://api.notion.com/v1/databases/{dbid}/query"
    payload = {"filter": {"property": title_prop, "title": {"equals": str(title_value)}}, "page_size": 1}
    r = _req_notion("POST", url, json=payload).json()
    results = r.get("results", [])
    return results[0]["id"] if results else None

def notion_create_page(database_id, props):
    dbid = _normalize_notion_id(database_id)
    body = {"parent": {"database_id": dbid}, "properties": props}
    r = _req_notion("POST", "https://api.notion.com/v1/pages", json=body)
    return r.json()

def notion_update_page(page_id, props):
    _req_notion("PATCH", f"https://api.notion.com/v1/pages/{page_id}", json={"properties": props})

def build_properties_notion(title_prop, nome, inadimplente_txt):
    return {
        title_prop: {"title": [{"text": {"content": str(nome)}}]},
        "Inadimplente?": {"rich_text": [{"text": {"content": str(inadimplente_txt)}}]},
    }

def notion_fetch_all_names(database_id, title_prop=None):
    dbid = _normalize_notion_id(database_id)
    meta = notion_retrieve_database(dbid)
    if not title_prop:
        title_prop = detect_title_property(dbid, meta)

    nomes, url = [], f"https://api.notion.com/v1/databases/{dbid}/query"
    start_cursor = None
    while True:
        body = {"page_size": 100}
        if start_cursor:
            body["start_cursor"] = start_cursor
        r = _req_notion("POST", url, json=body).json()
        for page in r.get("results", []):
            props = page.get("properties", {}) or {}
            tp = props.get(title_prop) or {}
            title_arr = None
            if isinstance(tp, dict):
                title_arr = tp.get("title")
            elif isinstance(tp, list):
                title_arr = tp
            if isinstance(title_arr, list):
                text = "".join(part.get("plain_text", "") for part in title_arr).strip()
                if text:
                    nomes.append(text)
        if r.get("has_more"):
            start_cursor = r.get("next_cursor")
        else:
            break
    return list(dict.fromkeys(nomes)), title_prop  # remove duplicados preservando ordem


# Envia ao Notion (apenas "Sim"/"Não")
def enviar_comparacao_para_notion(df_final, df_unico):
    df_comp = comparar_nomes(df_final, df_unico)
    dbid, meta = ensure_notion_ready(DATABASE_ID)
    title_prop = detect_title_property(dbid, meta)
    notion_ensure_property_rich_text(dbid, "Inadimplente?")

    total = len(df_comp)
    for i, row in enumerate(df_comp.to_dict(orient="records"), start=1):
        nome = (row.get("Nome") or "").strip()
        inad_txt = (row.get("Inadimplente?") or "").strip()
        if not nome:
            print(f"[{i}/{total}] Pulado: Nome vazio")
            continue

        props = build_properties_notion(title_prop, nome, inad_txt)
        page_id = notion_query_by_title(dbid, title_prop, nome)
        if page_id:
            notion_update_page(page_id, props)
            print(f"[{i}/{total}] Atualizado: {nome} (Inadimplente?={inad_txt})")
        else:
            notion_create_page(dbid, props)
            print(f"[{i}/{total}] Criado: {nome} (Inadimplente?={inad_txt})")
    return df_comp

# Postgres
def conectar_banco():
    url = "postgresql+psycopg2://postgres:123456@localhost:5432/ProjetoImport"
    engine = create_engine(url, pool_pre_ping=True)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        print("✅ Conexão Postgres OK")
    return engine

# Conversão de números BRL
def parse_brl_number(series: pd.Series) -> pd.Series:
    s = (
        series.astype(str)
        .str.replace("R$", "", regex=False)
        .str.strip()
    )
    mask_brl = s.str.contains(",", na=False)
    s = s.where(
        ~mask_brl,
        s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    )
    return pd.to_numeric(s, errors="coerce")

# Principal
def main():
    nomes_notion_antes, title_prop = notion_fetch_all_names(DATABASE_ID, title_prop=None)
    df_unico = pd.Series(nomes_notion_antes, dtype="string").dropna().drop_duplicates().values
    print(f"📥 Nomes capturados do Notion (antes): {len(df_unico)} | title_prop: {title_prop}")

    # 1) Conta Azul
    token = renovar_access_token()

    df_inadimplentes = buscar_contas_a_receber(token)
    if "cliente" in df_inadimplentes.columns:
        df_inadimplentes["cliente_id"] = df_inadimplentes["cliente"].apply(
            lambda x: x.get("id") if isinstance(x, dict) else x
        )
        df_inadimplentes["cliente_nome"] = df_inadimplentes["cliente"].apply(
            lambda x: x.get("nome") if isinstance(x, dict) else x
        )
        df_inadimplentes.drop(columns=["cliente"], inplace=True, errors="ignore")

    df_clientes = buscar_clientes(token)
    cols_clientes = [c for c in ["uuid", "nome", "documento", "ativo"] if c in df_clientes.columns]
    df_clientes = df_clientes[cols_clientes].copy()

    df_final = pd.merge(
        df_inadimplentes,
        df_clientes,
        how="left",
        left_on="cliente_id",
        right_on="uuid" if "uuid" in df_clientes.columns else "cliente_id"
    )

    for col in ["uuid", "cliente_nome"]:
        if col in df_final.columns:
            df_final.drop(columns=[col], inplace=True)

    # Renomear para o esquema final
    rename_map = {
        "id": "ID",
        "status": "Status",
        "valor_total": "Total",
        "total": "Total",
        "descricao": "Descricao",
        "data_vencimento": "Data_Vencimento",
        "status_traduzido": "Status_Traduzido",
        "nao_pago": "Nao_Pago",
        "pago": "Pago",
        "data_criacao": "Data_Criacao",
        "data_alteracao": "Data_Alteracao",
        "cliente_id": "Cliente_ID",
        "nome": "Nome",
        "documento": "Documento",
        "ativo": "Ativo",
    }
    rename_map = {k: v for k, v in rename_map.items() if k in df_final.columns}
    df_final = df_final.rename(columns=rename_map)

    # Tipos / datas
    if "Data_Vencimento" in df_final.columns:
        df_final["Data_Vencimento"] = pd.to_datetime(df_final["Data_Vencimento"], errors="coerce").dt.date
    for c in ["Data_Criacao", "Data_Alteracao"]:
        if c in df_final.columns:
            df_final[c] = pd.to_datetime(df_final[c], errors="coerce", utc=True)

    # Corrigir números
    for col in ["Total", "Pago", "Nao_Pago"]:
        if col in df_final.columns:
            df_final[col] = parse_brl_number(df_final[col])

    # 3) Envia para Postgres
    engine = conectar_banco()
    dtype_map = {}
    if "ID" in df_final.columns: dtype_map["ID"] = PG_UUID(as_uuid=False)
    if "Status" in df_final.columns: dtype_map["Status"] = Text()
    if "Total" in df_final.columns: dtype_map["Total"] = Numeric(18, 2)
    if "Descricao" in df_final.columns: dtype_map["Descricao"] = Text()
    if "Data_Vencimento" in df_final.columns: dtype_map["Data_Vencimento"] = Date()
    if "Status_Traduzido" in df_final.columns: dtype_map["Status_Traduzido"] = Text()
    if "Nao_Pago" in df_final.columns: dtype_map["Nao_Pago"] = Numeric(18, 2)
    if "Pago" in df_final.columns: dtype_map["Pago"] = Numeric(18, 2)
    if "Data_Criacao" in df_final.columns: dtype_map["Data_Criacao"] = DateTime(timezone=True)
    if "Data_Alteracao" in df_final.columns: dtype_map["Data_Alteracao"] = DateTime(timezone=True)
    if "Cliente_ID" in df_final.columns: dtype_map["Cliente_ID"] = PG_UUID(as_uuid=False)
    if "Nome" in df_final.columns: dtype_map["Nome"] = Text()
    if "Documento" in df_final.columns: dtype_map["Documento"] = Text()
    if "Ativo" in df_final.columns: dtype_map["Ativo"] = Text()

    def to_json_str(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False)
        return v
    
    # Converte qualquer coluna que tenha dict/list
    for c in df_final.columns:
        if df_final[c].map(lambda v: isinstance(v, (dict, list))).any():
            df_final[c] = df_final[c].map(to_json_str)
            dtype_map[c] = Text()  # garante tipo compatível no Postgres
            
    df_final.to_sql(
        name="Conta_Azul",
        con=engine,
        if_exists="replace",
        index=False,
        dtype=dtype_map,
        method="multi",
        chunksize=5000
    )
    print("✅ df_final enviado para a tabela Conta_Azul.")

    # 4) Atualiza Notion (upsert)
    df_comp = enviar_comparacao_para_notion(df_final, df_unico)
    print("✅ Comparação concluída. Linhas:", len(df_comp))


if __name__ == "__main__":
    main()


# In[3]:


import requests 
import json
import os
import re
import time
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from openpyxl import load_workbook  # opcional
from sqlalchemy import create_engine, text
from sqlalchemy import String, Numeric, Date, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from zoneinfo import ZoneInfo

NOTION_VERSION = "2022-06-28"

# ----- CONFIG -----
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("DATABASE_ID")
PG_CONN_STR  = "postgresql+psycopg2://postgres:123456@localhost:5432/ProjetoImport"
PG_TABLE     = "Conta_Azul_Mao"

# Colunas do Notion (como estão lá) -> nomes na tabela do Postgres
COLMAP = {
    "Nome": "Nome",
    "Inadimplente?": "Inadimplente",
    "Status": "Status",
    "Probabilidade recuperação": "Probabilidade_Recuperacao",
    "Ciente do Débito?": "Ciente_do_Debito",
    "Tem negociação comercial?": "Tem_Negociacao_Comercial",
    "1º Contato de Cobrança?": "Contato_Cobranca_Primeiro",
    "Negociação Realizada?": "Negociacao_Realizada",
    "Situação da Dívida": "Situacao_da_Divida",
}

# ----- Notion helpers -----
def _join_plain_text(arr):
    return "".join((x.get("plain_text", "") for x in (arr or []))).strip()

def _parse_prop(prop):
    """Apenas Title, Text (rich_text) e Select -> string."""
    if not prop: return None
    t = prop.get("type")
    if t == "title":
        return _join_plain_text(prop.get("title", []))
    if t == "rich_text":
        return _join_plain_text(prop.get("rich_text", []))
    if t == "select":
        s = prop.get("select")
        return s.get("name") if s else None
    return None  # ignora quaisquer outros tipos

def fetch_notion_database(notion_token, database_id, page_size=100):
    headers = {
        "Authorization": f"Bearer {notion_token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    payload = {"page_size": page_size}
    results = []
    while True:
        resp = requests.post(url, headers=headers, json=payload)
        if resp.status_code == 429:  # rate limit
            time.sleep(int(resp.headers.get("Retry-After", "1")))
            continue
        resp.raise_for_status()
        data = resp.json()
        results.extend(data.get("results", []))
        if data.get("has_more") and data.get("next_cursor"):
            payload["start_cursor"] = data["next_cursor"]
        else:
            break
    return results

def notion_results_to_tabular(results):
    rows = []
    for page in results:
        props = page.get("properties", {}) or {}
        row = {}
        # pega só as colunas que você mapeou no COLMAP
        for notion_col in COLMAP.keys():
            val = _parse_prop(props.get(notion_col))
            row[notion_col] = val
        rows.append(row)
    df = pd.DataFrame(rows, columns=list(COLMAP.keys()))
    # renomeia para os nomes da tabela no Postgres
    df = df.rename(columns=COLMAP)
    # normaliza para string (TEXT); nulos continuam como NaN/None
    for c in df.columns:
        df[c] = df[c].astype("string")
    return df

# ----- Upload para Postgres (append na tabela já existente) -----
def append_to_postgres(df: pd.DataFrame, conn_str: str, table: str):
    engine = create_engine(conn_str, pool_pre_ping=True)
    # sanity check na conexão
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    # mapeia tudo para TEXT (conforme tipos vindos do Notion neste cenário)
    dtype_map = {c: Text() for c in df.columns}

    df.to_sql(
        name=table,
        con=engine,
        if_exists="replace",   # <- insere na tabela já criada
        index=False,
        dtype=dtype_map,
        method="multi",
        chunksize=5000,
    )

if __name__ == "__main__":
    results = fetch_notion_database(NOTION_TOKEN, DATABASE_ID)
    df = notion_results_to_tabular(results)

    # Garantia: as colunas do DataFrame precisam bater com a tabela destino
    expected_cols = list(COLMAP.values())
    missing = [c for c in expected_cols if c not in df.columns]
    if missing:
        raise RuntimeError(f"Colunas faltando no DataFrame: {missing}")

    append_to_postgres(df, PG_CONN_STR, PG_TABLE)
    print(f"OK! Inseridas {len(df)} linhas em {PG_TABLE}.")


# In[4]:


import subprocess

subprocess.run(['python', r'C:\Users\Gabriel Alef\Projeto\rpa\RPA_Gestao_Financeira.py'])
print("Atualizar clicado")

