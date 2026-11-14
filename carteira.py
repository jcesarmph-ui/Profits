"""Armazenamento, importação e cálculos da carteira."""

import re
import sqlite3
from datetime import datetime
from pathlib import Path

CLASSES = ("Renda fixa", "FIIs", "Ações", "Cripto", "ETFs")


def abrir_banco(caminho):
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    banco = sqlite3.connect(caminho)
    banco.executescript("""
        CREATE TABLE IF NOT EXISTS compras (
            classe TEXT, dia TEXT, ativo TEXT, quantidade REAL,
            preco REAL, custo REAL
        );
        CREATE TABLE IF NOT EXISTS aportes (
            classe TEXT, dia TEXT, reais REAL, dolares REAL
        );
        CREATE TABLE IF NOT EXISTS proventos (
            classe TEXT, dia TEXT, ativo TEXT, valor REAL
        );
        CREATE TABLE IF NOT EXISTS cotacoes (
            classe TEXT, ativo TEXT, preco REAL, PRIMARY KEY (classe, ativo)
        );
        CREATE TABLE IF NOT EXISTS parametros (
            nome TEXT PRIMARY KEY, valor REAL
        );
        CREATE TABLE IF NOT EXISTS mensal (
            mes TEXT PRIMARY KEY, aporte_mes REAL, aporte_total REAL,
            patrimonio REAL, ganho_mes REAL, percentual REAL,
            ganho_total REAL, provento_mes REAL, provento_total REAL
        );
        CREATE TABLE IF NOT EXISTS mensal_classe (
            classe TEXT, mes TEXT, aporte_total REAL, patrimonio REAL,
            ganho_mes REAL, ganho_total REAL, percentual REAL,
            PRIMARY KEY (classe, mes)
        );
        CREATE TABLE IF NOT EXISTS origem_planilha (
            aba TEXT, celula TEXT, valor TEXT,
            PRIMARY KEY (aba, celula)
        );
    """)
    if "cotacao_registrada" not in {linha[1] for linha in banco.execute("PRAGMA table_info(compras)")}:
        with banco:
            banco.execute("ALTER TABLE compras ADD COLUMN cotacao_registrada REAL")
    return banco


def parametro(banco, nome, padrao=0):
    linha = banco.execute("SELECT valor FROM parametros WHERE nome=?", (nome,)).fetchone()
    return linha[0] if linha else padrao


def posicoes(banco, classe):
    return banco.execute("""
        SELECT c.ativo, SUM(c.quantidade), SUM(c.custo), q.preco
        FROM compras c LEFT JOIN cotacoes q USING (classe, ativo)
        WHERE c.classe=? GROUP BY c.ativo ORDER BY c.ativo
    """, (classe,)).fetchall()


def totais(banco, classe):
    cambio = parametro(banco, "USD/BRL", None) if classe == "ETFs" else 1
    proventos = banco.execute(
        "SELECT COALESCE(SUM(valor), 0) FROM proventos WHERE classe=?", (classe,)
    ).fetchone()[0]
    campo, tabela = ("reais", "aportes") if classe in ("Renda fixa", "ETFs") else ("custo", "compras")
    aporte = banco.execute(
        f"SELECT COALESCE(SUM({campo}), 0) FROM {tabela} WHERE classe=?", (classe,)
    ).fetchone()[0]
    if classe == "Renda fixa":
        return aporte, parametro(banco, "Saldo renda fixa", None) if aporte else parametro(banco, "Saldo renda fixa"), 0
    pos = posicoes(banco, classe)
    valor = sum(qtd * preco for _, qtd, _, preco in pos if preco is not None)
    if classe == "ETFs":
        caixa = banco.execute("SELECT COALESCE(SUM(dolares), 0) FROM aportes WHERE classe=?", (classe,)).fetchone()[0]
        valor += caixa - sum(custo for _, _, custo, _ in pos)
    incompleto = any(preco is None for _, _, _, preco in pos) or (cambio is None and (pos or aporte))
    return aporte, None if incompleto else valor * (cambio or 1), None if proventos and cambio is None else proventos * (cambio or 1)


def fechar_mes(banco, mes):
    if banco.execute("SELECT 1 FROM mensal WHERE mes>=?", (mes,)).fetchone():
        raise ValueError("Escolha um mês posterior ao último fechamento.")
    if banco.execute(
        "SELECT 1 FROM compras WHERE dia>=? UNION ALL "
        "SELECT 1 FROM aportes WHERE dia>=? UNION ALL SELECT 1 FROM proventos WHERE dia>=?",
        (mes + '-32',) * 3,
    ).fetchone():
        raise ValueError("Há lançamentos posteriores ao mês escolhido.")
    dados = [totais(banco, classe) for classe in CLASSES]
    if any(valor is None for grupo in dados for valor in grupo):
        raise ValueError("Preencha o saldo, o câmbio e as cotações pendentes antes de fechar.")
    aporte, patrimonio, provento = map(sum, zip(*dados))
    anterior = banco.execute(
        "SELECT aporte_total, ganho_total, provento_total FROM mensal ORDER BY mes DESC LIMIT 1"
    ).fetchone() or (0, 0, 0)
    ganho_total = patrimonio - aporte
    ganho_mes = ganho_total - anterior[1]
    banco.execute("INSERT INTO mensal VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
        mes, aporte - anterior[0], aporte, patrimonio, ganho_mes,
        ganho_mes / aporte if aporte else None, ganho_total, provento - anterior[2], provento,
    ))
    for classe, (aporte, patrimonio, _) in zip(CLASSES, dados):
        ganho = patrimonio - aporte
        anterior = banco.execute(
            "SELECT mes, ganho_total FROM mensal_classe WHERE classe=? AND mes<? ORDER BY mes DESC LIMIT 1",
            (classe, mes),
        ).fetchone()
        mes_anterior = (datetime.fromisoformat(mes + "-01").date().toordinal() - 1)
        consecutivo = anterior and anterior[0] == datetime.fromordinal(mes_anterior).strftime("%Y-%m")
        variacao = ganho - anterior[1] if consecutivo else None
        banco.execute("INSERT INTO mensal_classe VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (classe, mes, aporte, patrimonio, variacao, ganho, ganho / aporte if aporte else None))


def mes_planilha(rotulo):
    meses = "JAN FEV MAR ABR MAI JUN JUL AGO SET OUT NOV DEZ".split()
    sigla, ano = re.fullmatch(r"([A-Z]{3})\s*\((\d{4})\)", rotulo.strip()).groups()
    return f"{ano}-{meses.index('OUT' if sigla == 'OTT' else sigla) + 1:02d}"


def carregar_planilha_inicial(banco, arquivo):
    if not arquivo.is_file() or parametro(banco, "Planilha local carregada"):
        return
    from openpyxl import load_workbook

    livro = load_workbook(arquivo, data_only=True)
    try:
        with banco:
            tabelas = ("compras", "aportes", "proventos", "mensal", "cotacoes")
            if not any(banco.execute(f"SELECT 1 FROM {tabela} LIMIT 1").fetchone() for tabela in tabelas):
                importar_abas(banco, livro)
            for classe, aba, coluna in zip(CLASSES, ("RENDA FIXA", "FII", "AÇÕES", "CRIPTO", "ETF"), (11, 24, 33, 19, 38)):
                for rotulo, aporte, patrimonio, ganho, *resto in livro[aba].iter_rows(
                    min_row=2, min_col=coluna, max_col=coluna + (4 if coluna == 11 else 5), values_only=True
                ):
                    if rotulo is not None:
                        percentual, total = resto if len(resto) == 2 else (None, resto[0])
                        banco.execute("INSERT OR IGNORE INTO mensal_classe VALUES (?, ?, ?, ?, ?, ?, ?)",
                                      (classe, mes_planilha(rotulo), aporte, patrimonio, ganho, total, percentual))
            # Preserva os valores das células auxiliares que não têm um campo na carteira.
            banco.executemany("INSERT OR IGNORE INTO origem_planilha VALUES (?, ?, ?)", (
                (aba.title, celula.coordinate, str(celula.value))
                for aba in livro for linha in aba.iter_rows()
                for celula in linha if celula.value is not None
            ))
            banco.execute("INSERT OR REPLACE INTO parametros VALUES (?, 1)", ("Planilha local carregada",))
    finally:
        livro.close()


def aportes_por_mes(banco, classe):
    tabela, campo = ("aportes", "reais") if classe in ("Renda fixa", "ETFs") else ("compras", "custo")
    return dict(banco.execute(
        f"SELECT substr(dia, 1, 7), SUM({campo}) FROM {tabela} WHERE classe=? GROUP BY 1",
        (classe,),
    ))


def importar(banco, arquivo):
    from openpyxl import load_workbook

    if any(banco.execute(f"SELECT 1 FROM {tabela} LIMIT 1").fetchone()
           for tabela in ("compras", "aportes", "proventos", "mensal", "parametros", "cotacoes")):
        raise ValueError("A importação inicial exige uma carteira vazia.")
    livro = load_workbook(arquivo, data_only=True)
    try:
        with banco:
            importar_abas(banco, livro)
    finally:
        livro.close()


def importar_abas(banco, livro):
    for classe, aba, colunas, cotacao, provento in (
        ("FIIs", "FII", (1, 2, 3, 4, 5), (10, 11), (19, 20, 22)),
        ("Ações", "AÇÕES", (1, 2, 3, 4, 5), (10, 11), (27, 28, 31)),
        ("Cripto", "CRIPTO", (1, 2, 3, 4, 5), (10, 11), None),
        ("ETFs", "ETF", (7, 8, 9, 11, 12), (24, 25), (30, 31, 33)),
    ):
        planilha = livro[aba]
        for linha in planilha.iter_rows(min_row=2, values_only=True):
            dia, ativo, preco, qtd, custo = (linha[i - 1] for i in colunas)
            if isinstance(dia, datetime):
                banco.execute("INSERT INTO compras (classe, dia, ativo, preco, quantidade, custo) VALUES (?, ?, ?, ?, ?, ?)",
                              (classe, dia.date().isoformat(), ativo, preco, qtd, custo))
            ticker, valor = (linha[i - 1] for i in cotacao)
            if isinstance(ticker, str) and isinstance(valor, (int, float)):
                if classe == "ETFs":
                    valor /= livro["ETF"]["O2"].value
                banco.execute("INSERT OR IGNORE INTO cotacoes VALUES (?, ?, ?)", (classe, ticker, valor))
            if provento:
                ticker, dia, valor = (linha[i - 1] for i in provento)
                if isinstance(dia, datetime):
                    banco.execute("INSERT INTO proventos VALUES (?, ?, ?, ?)",
                                  (classe, dia.date().isoformat(), ticker, valor))
    for classe, aba in (("ETFs", "ETF"), ("Renda fixa", "RENDA FIXA")):
        for dia, reais, _, _, dolares in livro[aba].iter_rows(min_row=2, max_col=5, values_only=True):
            if isinstance(dia, datetime):
                banco.execute("INSERT INTO aportes VALUES (?, ?, ?, ?)", (
                    classe, dia.date().isoformat(), reais, dolares if classe == "ETFs" else 0,
                ))
    banco.executemany("INSERT INTO parametros VALUES (?, ?)", [
        ("Saldo renda fixa", livro["RENDA FIXA"]["G2"].value),
        ("USD/BRL", livro["ETF"]["O2"].value),
    ])
    for rotulo, *valores in livro["MENSAL"].iter_rows(min_row=2, max_col=9, values_only=True):
        if rotulo is None:
            continue
        banco.execute("INSERT INTO mensal VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (mes_planilha(rotulo), *valores))
