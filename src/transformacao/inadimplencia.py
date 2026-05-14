#!/usr/bin/env python
# coding: utf-8

# In[4]:


import requests
import json
import os
import sys
from datetime import datetime
import pandas as pd
from openpyxl import load_workbook
from dotenv import load_dotenv

load_dotenv()

# Configurações para funcionar API do Conta Azul
client_id = os.getenv("client_id")
client_secret = os.getenv("client_secret")
token_url = "https://auth.contaazul.com/oauth2/token"

# Corrigir para funcionar dentro do .exe
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Caminho do Token para funcionar e processo
token_file = os.path.join(BASE_DIR, "token.json")
def carregar_token():
    if os.path.exists(token_file):
        with open(token_file, "r") as f:
            return json.load(f)
    else:
        raise Exception("Arquivo de token não encontrado.")
def salvar_token(data):
    with open(token_file, "w") as f:
        json.dump(data, f)
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

def buscar_contas_a_receber(access_token):
    url = "https://api-v2.contaazul.com/v1/financeiro/eventos-financeiros/contas-a-receber/buscar"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    query_base = {
        "tamanho_pagina": "100",
        "data_vencimento_de": "2018-01-01",
        "data_vencimento_ate": datetime.today().strftime("%Y-%m-%d"),
        "status": "ATRASADO"
    }

    tudo = []
    pagina = 1

    while True:
        query = query_base.copy()
        query["pagina"] = str(pagina)
        response = requests.get(url, headers=headers, params=query)
        if response.status_code != 200:
            raise Exception(f"Erro página {pagina}: {response.text}")
        data = response.json()
        itens = data.get("itens", [])
        if not itens:
            break
        tudo.extend(itens)
        pagina += 1

    return pd.DataFrame(tudo)

def buscar_clientes(access_token):
    url = "https://api-v2.contaazul.com/v1/pessoa"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    query_base = {
        "tamanho_pagina": "100",
        "tipo_perfil": "CLIENTE",
        "status": "TODOS"
    }

    tudo = []
    pagina = 1

    while True:
        query = query_base.copy()
        query["pagina"] = str(pagina)
        response = requests.get(url, headers=headers, params=query)
        if response.status_code != 200:
            raise Exception(f"Erro página {pagina}: {response.text}")
        data = response.json()
        itens = data.get("itens", [])
        if not itens:
            break
        tudo.extend(itens)
        pagina += 1

    return pd.DataFrame(tudo)

def main():
    token = renovar_access_token()

    # Inadimplentes
    df_inadimplentes = buscar_contas_a_receber(token)
    if "cliente" in df_inadimplentes.columns:
        df_inadimplentes["cliente_id"] = df_inadimplentes["cliente"].apply(
            lambda x: x.get("id") if isinstance(x, dict) else x
        )
        df_inadimplentes["cliente_nome"] = df_inadimplentes["cliente"].apply(
            lambda x: x.get("nome") if isinstance(x, dict) else x
        )
    df_inadimplentes.drop(columns=["cliente"], inplace=True)

    # Clientes
    df_clientes = buscar_clientes(token)
    df_clientes = df_clientes[["uuid", "nome", "documento", "ativo"]]

    # Merge
    df_final = pd.merge(
        df_inadimplentes,
        df_clientes,
        how="left",
        left_on="cliente_id",
        right_on="uuid"
    )
    df_final = df_final.drop(columns=["uuid", "cliente_nome"])

    # Exportar no mesmo local do executável
    caminho_arquivo = os.path.join(BASE_DIR, "Conta_azul_Base.xlsx")
    df_final.to_excel(caminho_arquivo, index=False)

    print("✅ Dados atualizados com sucesso na planilha!")

# Executa automaticamente
if __name__ == "__main__":
    main()


# In[ ]:




