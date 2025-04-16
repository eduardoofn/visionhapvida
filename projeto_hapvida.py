import streamlit as st
import pandas as pd
import datetime
import fitz  # PyMuPDF
import re
import urllib.parse
from sqlalchemy import create_engine, text
import psycopg2
import sys
from datetime import timedelta
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
from dotenv import load_dotenv
import os

# === CONFIGURAR CONEXAO COM SUPABASE (POSTGRESQL - POOLER) ===
load_dotenv(dotenv_path="config.env")

SUPABASE_CONFIG = {
    "usuario": os.getenv("USUARIO"),
    "senha": urllib.parse.quote_plus(os.getenv("SENHA", "")),
    "host": os.getenv("HOST"),
    "porta": os.getenv("PORTA"),
    "banco": os.getenv("BANCO")
}

def conectar():
    return create_engine(
        f"postgresql+psycopg2://{SUPABASE_CONFIG['usuario']}:{SUPABASE_CONFIG['senha']}"
        f"@{SUPABASE_CONFIG['host']}:{SUPABASE_CONFIG['porta']}/{SUPABASE_CONFIG['banco']}",
        connect_args={"client_encoding": "utf8"}
    )

def adicionar_dias_uteis(data_inicial, dias_uteis):
    data = data_inicial
    count = 0
    while count < dias_uteis:
        data += timedelta(days=1)
        if data.weekday() < 5:
            count += 1
    return data


# === ESTILO GLOBAL CUSTOMIZADO ===


# === DESATIVAR AUTOCOMPLETE DE CAMPOS TEXT_INPUT ===
st.markdown("""
    <style>
    header {visibility: hidden;}
    [data-testid="stDeployButton"] {display: none !important;}

    /* Títulos menores */
    h1, h2, h3, h4, h5, h6 {
        font-size: 18px !important;
        margin-bottom: 8px;
    }
    input[type="text"], input[type="number"] {
        autocomplete: off !important;
    }
    </style>
""", unsafe_allow_html=True)

# === FUNCAO PARA EXTRAIR DADOS DO PDF ===
def extrair_dados_pdf(file):
    doc = fitz.open(stream=file.read(), filetype="pdf")
    texto = "\n".join([page.get_text("text") for page in doc])

    numero_pedido = re.search(r"Pedido de Compra\s+Nº Pedido:\s*(\d+)", texto)
    data_emissao = re.search(r"Data Emiss[ãa]o:\s*(\d{2}\.\d{2}\.\d{4})", texto)
    hospital = re.search(r"Dados de Faturamento\n(.*?)\n", texto)
    endereco = re.search(r"HAM - HOSPITAL ILHA DO LEITE\n(.*?)\nRECIFE", texto, re.DOTALL)

    itens = re.findall(r"\d{5}\s+(\d{2}\.\d{2}\.\d{4})\s+(\d+)\s+(.*?)\s+(\d+,\d{3})\s+UD\s+(\d+,\d{3})", texto)

    pedido = {
        "numero_pedido": numero_pedido.group(1) if numero_pedido else None,
        "data_emissao": datetime.datetime.strptime(data_emissao.group(1), "%d.%m.%Y") if data_emissao else None,
        "hospital": hospital.group(1).strip() if hospital else None,
        "endereco_entrega": endereco.group(1).replace("\n", " ").strip() if endereco else None,
        "estado": "Pernambuco",
        "uf": "PE"
    }

    lista_itens = []
    for item in itens:
        data_entrega = datetime.datetime.strptime(item[0], "%d.%m.%Y")
        lista_itens.append({
            "codigo_material": item[1],
            "descricao": item[2].strip(),
            "quantidade": int(float(item[3].replace(".", "").replace(",", "."))),
            "valor_unitario": float(item[4].replace(",", ".")),
            "data_entrega": data_entrega
        })

    return pedido, lista_itens

# === MENU LATERAL ===
menu = st.sidebar.radio(" ", ["🏠 Home", "📥 Upload", "🧾 Produção", "📋 Tabela de Pedidos", "📊 Tabela Geral",  "📈 Acompanhamento", "🚚 Logística"], label_visibility="collapsed")


engine = conectar()

# === HOME ===
if menu == "🏠 Home":
    st.title("🏠 Bem-vindo ao Sistema de Produção")
    st.write("Use o menu lateral para navegar entre as opções.")

# === IMPORTAR PDF ===
elif menu == "📥 Upload":
    st.title("📥 Importar Pedido PDF")
    uploaded_file = st.file_uploader("Escolha um PDF de pedido", type="pdf")
    if uploaded_file:
        pedido, itens = extrair_dados_pdf(uploaded_file)

        st.subheader("Resumo do Pedido")
        st.json(pedido)

        st.subheader("Itens do Pedido")
        df_itens = pd.DataFrame(itens)
        st.dataframe(df_itens)

        if st.button("Salvar no Supabase"):
            with engine.connect() as conn:
                numero_pedido = pedido["numero_pedido"]
                existe = conn.execute(text("SELECT 1 FROM pedidos WHERE numero_pedido = :numero"), {"numero": numero_pedido}).first()

            if existe:
                st.warning(f"⚠️ O pedido número {numero_pedido} já foi importado.")
            else:
                with engine.begin() as conn:
                    result = conn.execute(
                        text("""
                            INSERT INTO pedidos (numero_pedido, data_emissao, hospital, endereco_entrega, estado, uf)
                            VALUES (:numero_pedido, :data_emissao, :hospital, :endereco_entrega, :estado, :uf)
                            RETURNING id
                        """), pedido
                    )
                    id_pedido = result.fetchone()[0]

                    for item in itens:
                        item['id_pedido'] = id_pedido
                        conn.execute(
                            text("""
                                INSERT INTO itens_pedido (id_pedido, codigo_material, descricao, quantidade, valor_unitario, data_entrega)
                                VALUES (:id_pedido, :codigo_material, :descricao, :quantidade, :valor_unitario, :data_entrega)
                            """), item
                        )
                st.success("✅ Pedido e itens salvos com sucesso!")
                st.stop()


elif menu == "📈 Acompanhamento":

    st.markdown("""
        <style>
        .block-container {
            padding: 0rem 1rem !important;
            margin: 0 auto !important;
            max-width: 100% !important;
        }
        .ag-root-wrapper, .ag-theme-streamlit .ag-root-wrapper {
            border: none !important;
        }
        .ag-theme-streamlit .ag-root, .ag-theme-streamlit .ag-header, .ag-theme-streamlit .ag-body {
            border: none !important;
            box-shadow: none !important;
        }
        .ag-theme-streamlit .ag-center-cols-viewport {
            overflow-x: auto !important;
        }
        .ag-theme-streamlit .ag-center-cols-container {
            min-width: 100% !important;
        }
        .ag-theme-streamlit {
            width: 100% !important;
            max-width: 100vw !important;
            margin-left: 0 !important;
            margin-right: 0 !important;
        }
        </style>
    """, unsafe_allow_html=True)

    st.title("📈 Acompanhamento da Produção")
    try:
        df = pd.read_sql("""
            SELECT pr.id, p.numero_pedido, ip.descricao, pr.status_tecido, pr.faturamento, pr.logistica, 
                   pr.nota_fiscal, pr.ordem_fabricacao, pr.quantidade_op, pr.consumo, pr.tecido
            FROM producao pr
            JOIN itens_pedido ip ON pr.id_item_pedido = ip.id
            JOIN pedidos p ON ip.id_pedido = p.id
            ORDER BY pr.id DESC
        """, con=engine)

        gb = GridOptionsBuilder.from_dataframe(df)
        gb.configure_pagination()
        gb.configure_default_column(filter=True, editable=True, groupable=True)
        grid_options = gb.build()

        grid_response = AgGrid(
            df,
            gridOptions=grid_options,
            update_mode=GridUpdateMode.MODEL_CHANGED,
            fit_columns_on_grid_load=True,
            theme="streamlit",
            height=600,
            allow_unsafe_jscode=True,
            editable=True
        )

        edited_df = grid_response["data"]
        if st.button("💾 Salvar Alterações"):
            try:
                with engine.begin() as conn:
                    for _, row in edited_df.iterrows():
                        conn.execute(text("""
                            UPDATE producao SET
                                status_tecido = :status_tecido,
                                faturamento = :faturamento,
                                logistica = :logistica,
                                nota_fiscal = :nota_fiscal,
                                ordem_fabricacao = :ordem_fabricacao,
                                quantidade_op = :quantidade_op,
                                consumo = :consumo,
                                tecido = :tecido
                            WHERE id = :id
                        """), row.to_dict())
                st.success("✅ Alterações salvas com sucesso!")
            except Exception as e:
                st.error(f"Erro ao salvar: {e}")
    except Exception as e:
        st.error(f"Erro ao carregar: {e}")

# === CADASTRO DE PRODUCAO ===
if menu == "🧾 Produção":
    st.title("🧾 Cadastro de Produção")

    try:
        df = pd.read_sql("""
            SELECT ip.id, p.numero_pedido, ip.descricao
            FROM itens_pedido ip
            JOIN pedidos p ON p.id = ip.id_pedido
            ORDER BY p.numero_pedido DESC
        """, con=engine)
    except Exception as e:
        st.error(f"Erro ao carregar itens: {e}")
        st.stop()

    df['opcao'] = df.apply(lambda x: f"{x.numero_pedido} - {x.descricao}", axis=1)
    opcoes_unicas = sorted(df['opcao'].unique())
    item_selecionado = st.selectbox("Selecionar Produto para Produção", options=opcoes_unicas, index=None, placeholder="Digite ou selecione...")

    if item_selecionado:
        df_filtrado = df[df['opcao'] == item_selecionado]
        if df_filtrado.empty:
            st.error("Erro ao localizar o item selecionado.")
            st.stop()

        id_item = df_filtrado['id'].values[0]

        status_tecido_df = pd.read_sql("SELECT nome FROM status_tecido ORDER BY nome", con=engine)
        faturamento_df = pd.read_sql("SELECT nome FROM status_faturamento ORDER BY nome", con=engine)
        logistica_df = pd.read_sql("SELECT nome FROM logistica ORDER BY nome", con=engine)

        with st.form("form_producao"):
            status_tecido = st.selectbox("Status do Tecido", options=[""] + status_tecido_df['nome'].tolist(), index=0, placeholder="(opcional)")
            faturamento = st.selectbox("Faturamento", options=[""] + faturamento_df['nome'].tolist(), index=0, placeholder="(opcional)")
            logistica = st.selectbox("Logística", options=[""] + logistica_df['nome'].tolist(), index=0, placeholder="(opcional)")

            nota_fiscal = st.text_input("Nota Fiscal", value="", key="nota_fiscal")
            ordem_fabricacao = st.text_input("Ordem de Fabricação", value="", key="ordem_fabricacao")
            quantidade_op = st.number_input("Quantidade OP", min_value=0, step=1)
            consumo = st.number_input("Consumo por Peça", min_value=0.0, step=0.01)
            tecido = st.text_input("Tecido", value="", key="tecido")

            submit = st.form_submit_button("Salvar Produção")

            if submit:
                with st.spinner("Salvando dados..."):
                    data_faturamento = datetime.date.today() if faturamento == "OK" else None

                    with engine.begin() as conn:
                        conn.execute(
                            text("""
                                INSERT INTO producao (
                                    id_item_pedido, status_tecido, faturamento, data_faturamento, 
                                    nota_fiscal, ordem_fabricacao, quantidade_op, consumo, tecido, logistica
                                ) VALUES (
                                    :id_item_pedido, :status_tecido, :faturamento, :data_faturamento, 
                                    :nota_fiscal, :ordem_fabricacao, :quantidade_op, :consumo, :tecido, :logistica
                                )
                            """),
                            {
                                "id_item_pedido": int(id_item),
                                "status_tecido": status_tecido,
                                "faturamento": faturamento,
                                "data_faturamento": data_faturamento,
                                "nota_fiscal": nota_fiscal,
                                "ordem_fabricacao": ordem_fabricacao,
                                "quantidade_op": int(quantidade_op),
                                "consumo": float(consumo),
                                "tecido": tecido,
                                "logistica": logistica
                            }
                        )

                        

                    st.success("✅ Produção salva com sucesso!")
                    # Atualizar data_entrega e cor_prioridade
                    try:
                        df_calc = pd.read_sql("""
                            SELECT pr.id, p.data_emissao
                            FROM producao pr
                            JOIN itens_pedido ip ON pr.id_item_pedido = ip.id
                            JOIN pedidos p ON ip.id_pedido = p.id
                        """, con=engine)

                        hoje = datetime.date.today()
                        pulmao = 30

                        df_calc["data_entrega"] = df_calc["data_emissao"].apply(lambda d: adicionar_dias_uteis(d, pulmao))
                        df_calc["cor_prioridade"] = df_calc["data_entrega"].apply(lambda data_entrega: (
                            "5.AZUL" if hoje <= adicionar_dias_uteis(data_entrega, -pulmao)
                            else "4.VERDE" if hoje <= adicionar_dias_uteis(data_entrega, -int(pulmao * 0.66))
                            else "3.AMARELO" if hoje <= adicionar_dias_uteis(data_entrega, -int(pulmao * 0.33))
                            else "2.VERMELHO" if hoje <= data_entrega
                            else "1.PRETO"
                        ))

                        with engine.begin() as conn:
                            for _, row in df_calc.iterrows():
                                conn.execute(text("""
                                    UPDATE producao
                                    SET data_entrega = :data_entrega,
                                        cor_prioridade = :cor_prioridade
                                    WHERE id = :id
                                """), {
                                    "id": int(row.id),
                                    "data_entrega": row.data_entrega,
                                    "cor_prioridade": row.cor_prioridade
                                })
                    except Exception as e:
                        st.error(f"Erro ao atualizar campos automáticos: {e}")
                st.experimental_rerun()


# === TABELA LOGISTICA ===
elif menu == "🚚 Logística":
    st.title("🚚 Cadastro de Logística")

    # 🔄 Limpa o campo antes de exibir o input
    if st.session_state.get("limpar_logistica", False):
        st.session_state.nome_logistica = ""
        st.session_state.limpar_logistica = False

    nome = st.text_input("Nome da logística", key="nome_logistica")

    if st.button("Adicionar"):
        try:
            with engine.connect() as conn:
                ja_existe = pd.read_sql("SELECT 1 FROM logistica WHERE nome = %s", conn, params=(nome,))
                if not ja_existe.empty:
                    st.warning("🚨 Este nome de logística já está cadastrado.")
                else:
                    with engine.begin() as conn:
                        conn.execute(text("INSERT INTO logistica (nome) VALUES (:nome)"), {"nome": nome})
                    st.success("Logística adicionada com sucesso!")
                    st.session_state.limpar_logistica = True
                    st.rerun()
        except Exception as e:
            st.error(f"Erro ao salvar: {e}")

    # 🧾 Exibe tabela no final
    try:
        df_log = pd.read_sql("SELECT id, nome FROM logistica ORDER BY id DESC", con=engine)
        st.dataframe(df_log, use_container_width=True)
    except:
        st.warning("Nenhum dado encontrado ou erro ao carregar.")


# === TABELA DE PEDIDOS ===
elif menu == "📋 Tabela de Pedidos":

    st.markdown("""
        <style>
        .block-container {
            padding: 0rem 1rem !important;
            margin: 0 auto !important;
            max-width: 100% !important;
        }
        .ag-root-wrapper, .ag-theme-streamlit .ag-root-wrapper {
            border: none !important;
        }
        .ag-theme-streamlit .ag-root, .ag-theme-streamlit .ag-header, .ag-theme-streamlit .ag-body {
            border: none !important;
            box-shadow: none !important;
        }
        .ag-theme-streamlit .ag-center-cols-viewport {
            overflow-x: auto !important;
        }
        .ag-theme-streamlit .ag-center-cols-container {
            min-width: 100% !important;
        }
        .ag-theme-streamlit {
            width: 100% !important;
            max-width: 100vw !important;
            margin-left: 0 !important;
            margin-right: 0 !important;
        }
        </style>
    """, unsafe_allow_html=True)        
            
    st.title("📋 Tabela de Pedidos")
    try:
        df = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", con=engine)
        gb = GridOptionsBuilder.from_dataframe(df)
        gb.configure_pagination()
        gb.configure_default_column(filter=True, editable=False, groupable=True)
        grid_options = gb.build()
        AgGrid(df, gridOptions=grid_options, update_mode=GridUpdateMode.NO_UPDATE, fit_columns_on_grid_load=True)
    except Exception as e:
        st.error(f"Erro ao carregar: {e}")

# === TABELA GERAL ===
elif menu == "📊 Tabela Geral":

    st.markdown("""
        <style>
        .block-container {
            padding: 0rem 1rem !important;
            margin: 0 auto !important;
            max-width: 100% !important;
        }
        .ag-root-wrapper, .ag-theme-streamlit .ag-root-wrapper {
            border: none !important;
        }
        .ag-theme-streamlit .ag-root, .ag-theme-streamlit .ag-header, .ag-theme-streamlit .ag-body {
            border: none !important;
            box-shadow: none !important;
        }
        .ag-theme-streamlit .ag-center-cols-viewport {
            overflow-x: auto !important;
        }
        .ag-theme-streamlit .ag-center-cols-container {
            min-width: 100% !important;
        }
        .ag-theme-streamlit {
            width: 100% !important;
            max-width: 100vw !important;
            margin-left: 0 !important;
            margin-right: 0 !important;
        }
        </style>
    """, unsafe_allow_html=True)
        
    st.title("📊 Tabela Geral de Produção")
    try:
        df = pd.read_sql("""
            SELECT p.numero_pedido, ip.descricao, pr.*
            FROM producao pr
            JOIN itens_pedido ip ON pr.id_item_pedido = ip.id
            JOIN pedidos p ON ip.id_pedido = p.id
            ORDER BY pr.id DESC
        """, con=engine)

        # Configuração visual da tabela
        gb = GridOptionsBuilder.from_dataframe(df)
        gb.configure_pagination()
        gb.configure_default_column(filter=True, editable=False, groupable=True)
        grid_options = gb.build()
        grid_options["domLayout"] = "autoHeight"  # Altura automática
        grid_options['suppressRowClickSelection'] = True

        AgGrid(
            df,
            gridOptions=grid_options,
            update_mode=GridUpdateMode.NO_UPDATE,
            fit_columns_on_grid_load=False,  # Desliga o ajuste automático
            theme="streamlit",
            height=600,
            allow_unsafe_jscode=True,
            enable_enterprise_modules=True,
            custom_css={
                ".ag-root-wrapper": {"border": "none"},
                ".ag-header": {"border-bottom": "none"},
                ".ag-cell": {"border-bottom": "none"},
                ".ag-row": {"border": "none"},
                ".ag-theme-streamlit": {"padding": "0px", "margin": "0 auto", "width": "100%"},
            }
        )


    except Exception as e:
        st.error(f"Erro ao carregar: {e}")
