"""Consulta das cotações de ações e FIIs da B3 e de ETFs dos EUA.

As chaves ficam em dados/chaves.json, que é ignorado pelo Git:
{"brapi": "SEU_TOKEN_BRAPI", "finnhub": "SUA_CHAVE_FINNHUB"}
"""

import json
import urllib.parse
import urllib.request
from pathlib import Path

TEMPO_LIMITE = 10
TAMANHO_LOTE_B3 = 10


def carregar_chaves(pasta):
    caminho = Path(pasta) / "chaves.json"
    if not caminho.is_file():
        return {}
    return json.loads(caminho.read_text(encoding="utf-8"))


def _pedido_json(url, cabecalhos=None):
    pedido = urllib.request.Request(url, headers={"User-Agent": "Profits", **(cabecalhos or {})})
    with urllib.request.urlopen(pedido, timeout=TEMPO_LIMITE) as resposta:
        return json.loads(resposta.read().decode("utf-8"))


def cotacoes_yahoo(tickers, sufixo=""):
    """Preço atual pelo Yahoo Finance, sem conta nem chave. Retorna {código: preço}.

    Ações e FIIs da B3 usam sufixo ".SA"; ETFs dos EUA usam o código puro.
    Mesma fonte da GOOGLEFINANCE, então os valores batem com a planilha.
    """
    precos = {}
    for ticker in tickers:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker + sufixo)}?range=1d&interval=1d"
        try:
            dados = _pedido_json(url)
            meta = dados["chart"]["result"][0]["meta"]
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            continue
        preco = meta.get("regularMarketPrice")
        if isinstance(preco, (int, float)) and preco > 0:
            precos[ticker.upper()] = float(preco)
    return precos


def cotacoes_b3(tickers, token):
    """Preço atual de cada código da B3 pela brapi. Retorna {código: preço}."""
    precos = {}
    if not token:
        return precos
    tickers = list(tickers)
    for inicio in range(0, len(tickers), TAMANHO_LOTE_B3):
        lote = tickers[inicio:inicio + TAMANHO_LOTE_B3]
        url = "https://brapi.dev/api/v2/stocks/quote?" + urllib.parse.urlencode({"symbols": ",".join(lote)})
        try:
            dados = _pedido_json(url, {"Authorization": f"Bearer {token}"})
        except (OSError, ValueError):
            continue
        for item in dados.get("results", []):
            preco = item.get("regularMarketPrice")
            codigo = item.get("requestedSymbol") or item.get("symbol")
            if codigo and isinstance(preco, (int, float)) and preco > 0:
                precos[codigo.upper()] = float(preco)
    return precos


def cotacoes_eua(tickers, token):
    """Preço atual, em dólares, de cada ETF dos EUA pela Finnhub. Retorna {código: preço}."""
    precos = {}
    if not token:
        return precos
    for ticker in tickers:
        url = "https://finnhub.io/api/v1/quote?" + urllib.parse.urlencode({"symbol": ticker, "token": token})
        try:
            dados = _pedido_json(url)
        except (OSError, ValueError):
            continue
        preco = dados.get("c")
        if isinstance(preco, (int, float)) and preco > 0:
            precos[ticker.upper()] = float(preco)
    return precos
