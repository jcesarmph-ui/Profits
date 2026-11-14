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
    """)
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
                banco.execute("INSERT INTO compras VALUES (?, ?, ?, ?, ?, ?)",
                              (classe, dia.date().isoformat(), ativo, qtd, preco, custo))
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
    meses = "JAN FEV MAR ABR MAI JUN JUL AGO SET OUT NOV DEZ".split()
    for rotulo, *valores in livro["MENSAL"].iter_rows(min_row=2, max_col=9, values_only=True):
        if rotulo is None:
            continue
        sigla, ano = re.fullmatch(r"([A-Z]{3})\s*\((\d{4})\)", rotulo.strip()).groups()
        mes = meses.index("OUT" if sigla == "OTT" else sigla) + 1
        banco.execute("INSERT INTO mensal VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (f"{ano}-{mes:02d}", *valores))
