"""Interface desktop da carteira."""

from pathlib import Path
import json
import math
import sqlite3
import sys
import threading

from PySide6.QtCharts import (
    QBarCategoryAxis, QBarSet, QCategoryAxis, QChart, QChartView, QLineSeries,
    QPieSeries, QStackedBarSeries, QValueAxis,
)
from PySide6.QtCore import QDate, QDateTime, QEvent, QLocale, QObject, QStandardPaths, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QTabWidget,
    QScrollArea, QTableWidget, QTableWidgetItem, QToolTip, QVBoxLayout, QWidget,
)

from carteira import (
    CLASSES, abrir_banco, aportes_por_mes, carregar_planilha_inicial, fechar_mes, parametro, posicoes, totais,
)
from mercado import carregar_chaves, cotacoes_b3, cotacoes_eua, cotacoes_yahoo

# No executável empacotado, os dados ficam ao lado do .exe; no código-fonte, ao lado do app.py.
PASTA = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
# Recursos empacotados (ícone e banco inicial) ficam na pasta temporária do PyInstaller.
RECURSOS = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else PASTA
INTERVALO_MERCADO_MS = 5 * 60 * 1000  # brapi e Finnhub têm cota; o câmbio e o Bitcoin seguem a cada 30 s
AMBAR = "#e2ad67"
CORES = ("#7ebdd2", "#a4afe7", "#e59391", "#83b9aa", "#c09bcd")
CLASSE_COR = dict(zip(CLASSES, CORES))
CLASSES_COM_METAS = ("FIIs", "Ações", "ETFs")
# Cores das fatias por ativo: as mesmas cores das classes na aba Geral, para ficarem bem distintas.
PALETA_ATIVOS = (AMBAR, CORES[0], CORES[2], CORES[3], CORES[1], CORES[4])
TEMA = """
QWidget { background:#181a2a; color:#eef2fa; font-family:'Segoe UI'; font-size:14px; }
QLabel[tipo="titulo"] {font-size:27px; font-weight:700;}
QLabel[tipo="secao"] {font-size:17px; font-weight:600; }
QLabel[tipo="valor"] {font-size:24px; font-weight:650; color:#e2ad67;}
QLabel[tipo="nota"] {color:#aab6c9;}
QWidget#cartao {background:#24273c; border:1px solid #383c56; border-radius:10px;}
QWidget#cartao QLabel {background:transparent;}
QPushButton {background:#2c3046; border:1px solid #494f69; border-radius:6px; padding:8px 14px;}
QPushButton:hover {background:#3a3f59;}
QPushButton[tipo="principal"] {background:#e2ad67; color:#231b15; font-weight:700;}
QPushButton[tipo="principal"]:hover {background:#f0c286;}
QLineEdit, QDateEdit, QDoubleSpinBox, QComboBox {background:#24273c; padding:6px;}
QTabBar::tab {background:#202338; padding:12px 18px; border-bottom:2px solid #202338;}
QTabBar::tab:selected {background:#2d314a; border-bottom:2px solid #e2ad67;}
QTabWidget::pane {border:0;}
QScrollArea {border:0;}
QScrollBar:vertical {width:10px; background:#202338; margin:2px;}
QScrollBar:horizontal {height:10px; background:#202338; margin:2px;}
QScrollBar::handle {background:#626987; border-radius:3px; min-height:28px; min-width:28px;}
QScrollBar::handle:hover {background:#9299b9;}
QScrollBar::add-line, QScrollBar::sub-line {width:0; height:0;}
QScrollBar::add-page, QScrollBar::sub-page {background:transparent;}
QPushButton[tipo="compacto"] {padding:3px 8px;}
QToolTip {background:#24273c; color:#f1f0f7; border:1px solid #494f69; padding:7px;}

QTableWidget {background:#171d26; alternate-background-color:#1e2632; border:0; gridline-color:#383c56;}
QHeaderView::section {background:#283343; border:0; padding:8px; font-weight:600;}
"""


def numero(valor, casas=2):
    if valor is None:
        return "—"
    return f"{valor:,.{casas}f}".translate(str.maketrans(",.", ".,"))


def moeda(valor, simbolo="R$"):
    return f"{simbolo} {numero(valor)}" if valor is not None else "—"


def rotulo(texto, tipo="nota"):
    item = QLabel(texto)
    item.setProperty("tipo", tipo)
    item.setWordWrap(True)
    return item


def botao(texto, acao, principal=False):
    item = QPushButton(texto)
    if principal:
        item.setProperty("tipo", "principal")
    item.clicked.connect(acao)
    return item


def tabela(colunas, linhas, compacta=False):
    grade = QTableWidget(len(linhas), len(colunas))
    grade.setHorizontalHeaderLabels(colunas)
    grade.verticalHeader().hide()
    grade.setAlternatingRowColors(True)
    grade.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    grade.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    grade.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    grade.horizontalHeader().setStretchLastSection(not compacta)
    for i, linha in enumerate(linhas):
        for j, valor in enumerate(linha):
            item = QTableWidgetItem(str(valor))
            if compacta and j:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grade.setItem(i, j, item)
    if compacta:
        grade.verticalHeader().setDefaultSectionSize(30)
        altura = grade.horizontalHeader().sizeHint().height()
        grade.setFixedHeight(altura + 30 * max(1, min(8, len(linhas))) + 13)
    return grade


def campo_numero(valor=0, casas=2):
    campo = QDoubleSpinBox()
    campo.setDecimals(casas)
    campo.setRange(0, 1e12)
    campo.setValue(valor or 0)
    return campo


def campo_data():
    campo = QDateEdit(QDate.currentDate())
    campo.setCalendarPopup(True)
    campo.setDisplayFormat("dd/MM/yyyy")
    return campo


def grafico(titulo):
    item = QChart()
    item.setTheme(QChart.ChartTheme.ChartThemeDark)
    item.setBackgroundBrush(QColor("#24273c"))
    item.setTitle(titulo)
    item.setLocale(QLocale("pt_BR"))
    item.setLocalizeNumbers(True)
    item.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
    vista = QChartView(item)
    vista.setRenderHint(QPainter.RenderHint.Antialiasing)
    vista.setMinimumHeight(275)
    return item, vista


def quantidade(valor):
    return numero(valor, 8).rstrip("0").rstrip(",")


def data_br(dia):
    return QDate.fromString(dia, "yyyy-MM-dd").toString("dd/MM/yyyy") or dia


def intervalo_meses(inicio, fim):
    mes = QDate.fromString(inicio + "-01", "yyyy-MM-dd")
    ultimo = QDate.fromString(fim + "-01", "yyyy-MM-dd")
    meses = []
    while mes.isValid() and mes <= ultimo:
        meses.append(mes.toString("yyyy-MM"))
        mes = mes.addMonths(1)
    return meses


def rolavel(pagina):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(pagina)
    return area


def registro_visual(titulo, detalhe):
    cartao = QWidget(objectName="cartao")
    caixa = QVBoxLayout(cartao)
    caixa.setContentsMargins(14, 10, 14, 10)
    caixa.addWidget(rotulo(titulo, "secao"))
    caixa.addWidget(rotulo(detalhe))
    return cartao


class DicaFixa(QObject):
    """Mantém a dica da fatia visível enquanto o mouse se move dentro da rosca.

    O Qt esconde a dica ao primeiro movimento; por isso ela é exibida de novo a cada movimento.
    """

    def __init__(self, vista):
        super().__init__(vista)
        self.vista = vista
        self.texto = None
        vista.setMouseTracking(True)
        vista.installEventFilter(self)

    def mostrar(self, texto):
        self.texto = texto
        if texto:
            self.exibir()
        else:
            QToolTip.hideText()

    def exibir(self):
        # O retângulo informa ao Qt a área em que a dica continua válida: ela só some ao sair da rosca.
        QToolTip.showText(QCursor.pos(), self.texto, self.vista, self.vista.rect())

    def eventFilter(self, objeto, evento):
        if evento.type() == QEvent.Type.MouseMove and self.texto:
            self.exibir()
        return False


def rosca(titulo, dados):
    chart, vista = grafico(titulo)
    vista.setMinimumHeight(365)
    pizza = QPieSeries()
    pizza.setHoleSize(0.53)
    pizza.setPieSize(0.94)
    chart.addSeries(pizza)
    detalhes = []
    for nome, valor, cor, resumo in dados:
        if valor is not None and valor > 0:
            fatia = pizza.append(nome, valor)
            fatia.setColor(QColor(cor))
            fatia.setBorderColor(QColor("#24273c"))
            fatia.setExplodeDistanceFactor(0.035)
            detalhes.append((fatia, resumo))
    chart.legend().setVisible(0 < len(detalhes) <= 8)
    if not detalhes:
        chart.setTitle(f"{titulo} · Sem dados")
    dica = DicaFixa(vista)
    for fatia, resumo in detalhes:
        fatia.setLabel(f"{fatia.label()} · {numero(fatia.percentage() * 100, 1)}%")
        mensagem = f"{fatia.label()} · {resumo}" if resumo else fatia.label()
        fatia.hovered.connect(lambda dentro, item=fatia, texto=mensagem: (
            item.setExploded(dentro), dica.mostrar(texto if dentro else None)))
    return vista


def mostrar_barra(dentro, indice, dados, simbolo):
    if dentro:
        mes, valor = dados[indice]
        QToolTip.showText(QCursor.pos(), f"{mes[5:]}/{mes[:4]} · {moeda(valor, simbolo)}")
    else:
        QToolTip.hideText()


def eixo_valores(chart, valores, simbolo="R$"):
    eixo = QValueAxis()
    eixo.setTitleText(simbolo)
    minimo = min(0, min(valores) * 1.12)
    maximo = max(1, max(valores) * 1.12) if minimo == 0 else max(0, max(valores) * 1.12)
    eixo.setRange(minimo, maximo)
    eixo.applyNiceNumbers()
    intervalo = (eixo.max() - eixo.min()) / max(1, eixo.tickCount() - 1)
    eixo.setLabelFormat("%.2f" if intervalo < 1 else "%.0f")
    chart.addAxis(eixo, Qt.AlignmentFlag.AlignLeft)
    return eixo


def grafico_linhas(titulo, meses, linhas):
    chart, vista = grafico(titulo)
    chart.legend().setVisible(len(linhas) > 1)
    valores = [valor for _, _, dados in linhas for valor in dados if valor is not None]
    if not valores:
        chart.setTitle(f"{titulo} · Sem fechamentos")
        chart.legend().hide()
        return vista
    datas = QCategoryAxis()
    datas.setLabelsPosition(QCategoryAxis.AxisLabelsPosition.AxisLabelsPositionOnValue)
    datas.setStartValue(-1)
    passo = max(1, math.ceil(len(meses) / 8))
    for i in range(len(meses)):
        if (len(meses) - 1 - i) % passo == 0:
            datas.append(f"{meses[i][5:]}/{meses[i][2:4]}", i)
    datas.setRange(-0.55, len(meses) - 0.45)
    chart.addAxis(datas, Qt.AlignmentFlag.AlignBottom)
    reais = eixo_valores(chart, valores)
    for nome, cor, dados in linhas:
        serie = QLineSeries()
        serie.setName(nome)
        serie.setColor(QColor(cor))
        serie.setPointsVisible(True)
        for i, valor in enumerate(dados):
            if valor is not None:
                serie.append(i, valor)
        serie.hovered.connect(lambda ponto, dentro, nome=nome: QToolTip.showText(
            QCursor.pos(), f"{nome} · {moeda(ponto.y())}"
        ) if dentro else QToolTip.hideText())
        chart.addSeries(serie)
        serie.attachAxis(datas)
        serie.attachAxis(reais)
    return vista


def grafico_barras(titulo, dados, cor, simbolo="R$"):
    chart, vista = grafico(titulo)
    vista.setMinimumHeight(285)
    chart.legend().hide()
    valores = [valor for _, valor in dados if valor is not None]
    if not valores:
        chart.setTitle(f"{titulo} · Sem dados")
        return vista
    if any(valor is None for _, valor in dados):
        chart.setTitle(f"{titulo}  ·  * mês sem fechamento")
    positivas = QBarSet(titulo)
    positivas.setColor(QColor(cor))
    positivas.append([max(0, valor or 0) for _, valor in dados])
    positivas.hovered.connect(lambda dentro, i: mostrar_barra(dentro, i, dados, simbolo))
    serie = QStackedBarSeries()
    serie.append(positivas)
    if min(valores) < 0:
        negativas = QBarSet("Negativo")
        negativas.setColor(QColor("#ed8f99"))
        negativas.append([min(0, valor or 0) for _, valor in dados])
        negativas.hovered.connect(lambda dentro, i: mostrar_barra(dentro, i, dados, simbolo))
        serie.append(negativas)
    serie.setBarWidth(0.72)
    chart.addSeries(serie)
    meses = QBarCategoryAxis()
    meses.append([f"{mes[5:]}/{mes[2:4]}{'*' if valor is None else ''}" for mes, valor in dados])
    chart.addAxis(meses, Qt.AlignmentFlag.AlignBottom)
    serie.attachAxis(meses)
    serie.attachAxis(eixo_valores(chart, valores, simbolo))
    return vista


class Sinal(QObject):
    """Leva o resultado das consultas da thread de rede para a interface."""

    recebido = Signal(dict)


class Janela(QMainWindow):
    def __init__(self, banco):
        super().__init__()
        self.banco = banco
        self.rede = QNetworkAccessManager(self)
        self.cotacoes_ao_vivo = {}
        self.paineis_cotacao = {}
        self.falha_cotacao = False
        self.consultas_pendentes = 0
        self.atualizar_depois = False
        self.sinal = Sinal(self)
        self.sinal.recebido.connect(self.receber_mercado)
        self.setWindowTitle("Profits")
        self.resize(1250, 790)
        raiz = QWidget()
        layout = QVBoxLayout(raiz)
        layout.setContentsMargins(22, 18, 22, 18)
        faixa = QHBoxLayout()
        faixa.addWidget(rotulo("Profits", "titulo"))
        faixa.addStretch()
        if parametro(banco, "Planilha local carregada"):
            faixa.addWidget(botao("Dados de origem", self.dados_origem))
        layout.addLayout(faixa)
        self.abas = QTabWidget()
        layout.addWidget(self.abas)
        self.setCentralWidget(raiz)
        self.atualizar()
        self.timer_cotacoes = QTimer(self)
        self.timer_cotacoes.timeout.connect(self.buscar_cotacoes)
        self.timer_cotacoes.start(30_000)
        self.timer_mercado = QTimer(self)
        self.timer_mercado.timeout.connect(self.buscar_mercado)
        self.timer_mercado.start(INTERVALO_MERCADO_MS)
        QTimer.singleShot(0, self.atualizar_cotacoes)

    def atualizar_cotacoes(self):
        """Botão Atualizar: consulta todas as cotações e redesenha a página com os valores novos."""
        self.atualizar_depois = True
        self.buscar_cotacoes()
        self.buscar_mercado()

    def concluir_consulta(self, mudou):
        self.consultas_pendentes -= 1
        if mudou or (self.atualizar_depois and self.consultas_pendentes == 0):
            self.atualizar_depois = False
            self.atualizar()

    def buscar_cotacoes(self):
        url = "https://economia.awesomeapi.com.br/json/last/USD-BRL,BTC-BRL"
        pedido = QNetworkRequest(QUrl(url))
        pedido.setTransferTimeout(8_000)
        self.consultas_pendentes += 1
        resposta = self.rede.get(pedido)
        resposta.finished.connect(lambda: self.receber_cotacoes(resposta))

    def buscar_mercado(self):
        """Consulta B3 e ETFs dos EUA numa thread, para não travar a janela."""
        try:
            chaves = carregar_chaves(PASTA / "dados")
        except (OSError, ValueError):
            chaves = {}
        b3 = [codigo for codigo, in self.banco.execute(
            "SELECT DISTINCT ativo FROM compras WHERE classe IN ('FIIs', 'Ações')")]
        eua = [codigo for codigo, in self.banco.execute("SELECT DISTINCT ativo FROM compras WHERE classe='ETFs'")]

        def consultar():
            # Yahoo Finance é a fonte principal (sem conta). brapi e Finnhub só completam o que faltar.
            precos = {
                **cotacoes_yahoo(b3, ".SA"),
                **cotacoes_yahoo(eua),
            }
            faltam_b3 = [codigo for codigo in b3 if codigo.upper() not in precos]
            faltam_eua = [codigo for codigo in eua if codigo.upper() not in precos]
            precos = {
                **cotacoes_b3(faltam_b3, chaves.get("brapi")),
                **cotacoes_eua(faltam_eua, chaves.get("finnhub")),
                **precos,
            }
            self.sinal.recebido.emit({"precos": precos})

        self.consultas_pendentes += 1
        threading.Thread(target=consultar, daemon=True).start()

    def receber_mercado(self, resultado):
        mudou = False
        try:
            classes = {codigo: classe for classe, codigo in self.banco.execute(
                "SELECT DISTINCT classe, ativo FROM compras")}
            atuais = {(classe, codigo): preco for classe, codigo, preco in self.banco.execute(
                "SELECT classe, ativo, preco FROM cotacoes")}
            with self.banco:
                for codigo, preco in resultado["precos"].items():
                    if codigo not in classes:
                        continue
                    chave = classes[codigo], codigo
                    mudou = mudou or atuais.get(chave) != preco
                    self.banco.execute("INSERT OR REPLACE INTO cotacoes VALUES (?, ?, ?)", (*chave, preco))
        except sqlite3.Error:
            mudou = False
        self.concluir_consulta(mudou)

    def receber_cotacoes(self, resposta):
        mudou = False
        try:
            dados = json.loads(bytes(resposta.readAll()))
            cotacoes = {}
            for par in ("USDBRL", "BTCBRL"):
                preco = float(dados[par]["bid"])
                if not math.isfinite(preco) or preco <= 0:
                    raise ValueError("Cotação inválida")
                data = QDateTime.fromSecsSinceEpoch(int(dados[par]["timestamp"]))
                cotacoes[par] = (preco, data.toString("dd/MM · HH:mm"))
            self.cotacoes_ao_vivo = cotacoes
            mudou = self.aplicar_cotacoes(cotacoes)
            self.falha_cotacao = False
        except (ValueError, KeyError, TypeError, OverflowError, sqlite3.Error):
            self.falha_cotacao = True
        finally:
            resposta.deleteLater()
        self.exibir_cotacoes()
        self.concluir_consulta(mudou)

    def aplicar_cotacoes(self, cotacoes):
        """Grava o dólar e o Bitcoin ao vivo na avaliação da carteira. Retorna se algum valor mudou."""
        dolar, _ = cotacoes["USDBRL"]
        bitcoin, _ = cotacoes["BTCBRL"]
        antigo_dolar = parametro(self.banco, "USD/BRL", None)
        antigo_btc = self.banco.execute(
            "SELECT preco FROM cotacoes WHERE classe='Cripto' AND ativo='BTC'"
        ).fetchone()
        with self.banco:
            self.banco.execute("INSERT OR REPLACE INTO parametros VALUES (?, ?)", ("USD/BRL", dolar))
            self.banco.execute("INSERT OR REPLACE INTO cotacoes VALUES (?, ?, ?)", ("Cripto", "BTC", bitcoin))
        return dolar != antigo_dolar or antigo_btc is None or antigo_btc[0] != bitcoin

    def exibir_cotacoes(self):
        for par, (valor, detalhe) in self.paineis_cotacao.items():
            if par in self.cotacoes_ao_vivo:
                preco, data = self.cotacoes_ao_vivo[par]
                valor.setText(moeda(preco))
                status = " · Falha ao atualizar" if self.falha_cotacao else ""
                detalhe.setText(f"AwesomeAPI · {data}{status}")
            else:
                detalhe.setText("Cotação indisponível" if self.falha_cotacao else "Consultando cotação…")

    def painel_cotacao(self, par, titulo):
        cartao = QWidget(objectName="cartao")
        caixa = QHBoxLayout(cartao)
        caixa.setContentsMargins(14, 8, 14, 8)
        caixa.setSpacing(16)
        caixa.addWidget(rotulo(titulo, "secao"))
        valor = rotulo("—", "valor")
        detalhe = rotulo("")
        caixa.addWidget(valor)
        caixa.addWidget(detalhe)
        self.paineis_cotacao[par] = valor, detalhe
        self.exibir_cotacoes()
        return cartao

    def dados_origem(self):
        janela = QDialog(self)
        janela.setWindowTitle("Dados da planilha original")
        janela.resize(920, 620)
        caixa = QVBoxLayout(janela)
        caixa.addWidget(rotulo("Valores preservados da planilha original", "secao"))
        abas = QTabWidget()
        for aba, in self.banco.execute("SELECT DISTINCT aba FROM origem_planilha ORDER BY aba"):
            linhas = self.banco.execute("SELECT celula, valor FROM origem_planilha WHERE aba=?", (aba,))
            abas.addTab(tabela(("Célula", "Valor na planilha"), list(linhas)), aba)
        caixa.addWidget(abas)
        janela.exec()

    def atualizar(self):
        indice = max(0, self.abas.currentIndex())
        self.paineis_cotacao.clear()
        while self.abas.count():
            aba = self.abas.widget(0)
            self.abas.removeTab(0)
            aba.deleteLater()
        self.abas.addTab(self.geral(), "Geral")
        self.abas.addTab(self.mensal(), "Mensal")
        for classe in CLASSES:
            self.abas.addTab(self.ativos(classe), classe)
        self.abas.setCurrentIndex(indice)

    def salvar(self, acao):
        try:
            with self.banco:
                acao()
        except (ValueError, OSError, KeyError, TypeError, sqlite3.Error) as erro:
            QMessageBox.warning(self, "Confira os dados", str(erro))
        else:
            self.atualizar()

    def formulario(self, titulo, campos, gravar, texto_salvar="Salvar"):
        janela = QDialog(self)
        janela.setWindowTitle(titulo)
        janela.setMinimumWidth(410)
        form = QFormLayout(janela)
        for legenda, campo in campos:
            form.addRow(legenda, campo)
        botoes = QDialogButtonBox()
        botao_salvar = botoes.addButton(texto_salvar, QDialogButtonBox.ButtonRole.AcceptRole)
        botao_salvar.setProperty("tipo", "principal")
        botoes.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        botoes.rejected.connect(janela.reject)

        def executar():
            try:
                with self.banco:
                    gravar()
            except (ValueError, sqlite3.Error) as erro:
                QMessageBox.warning(janela, "Confira os dados", str(erro))
            else:
                janela.accept()

        botao_salvar.clicked.connect(executar)
        form.addRow(botoes)
        if janela.exec() == QDialog.DialogCode.Accepted:
            self.atualizar()
            return True
        return False

    def geral(self):
        pagina = QWidget()
        corpo = QVBoxLayout(pagina)
        dados = [totais(self.banco, classe) for classe in CLASSES]
        aporte = sum(grupo[0] for grupo in dados)
        pendentes = [classe for classe, grupo in zip(CLASSES, dados) if grupo[1] is None]
        patrimonio = None if pendentes else sum(grupo[1] for grupo in dados)
        dividendos = None if any(grupo[2] is None for grupo in dados) else sum(grupo[2] for grupo in dados)
        faixa = QHBoxLayout()
        for titulo, valor in (
            ("Patrimônio", patrimonio), ("Aporte acumulado", aporte),
            ("Valorização", patrimonio - aporte if patrimonio is not None else None), ("Proventos", dividendos),
        ):
            cartao = QWidget(objectName="cartao")
            caixa = QVBoxLayout(cartao)
            caixa.setContentsMargins(16, 12, 16, 12)
            caixa.addWidget(rotulo(titulo))
            caixa.addWidget(rotulo(moeda(valor), "valor"))
            faixa.addWidget(cartao)
        corpo.addLayout(faixa)
        if pendentes:
            corpo.addWidget(rotulo("Dados pendentes em " + ", ".join(pendentes) + ". A alocação usa as classes com saldo conhecido."))
        graficos = QHBoxLayout()
        graficos.addWidget(rosca("Alocação atual", [
            (classe, grupo[1], cor, moeda(grupo[1]))
            for classe, grupo, cor in zip(CLASSES, dados, CORES)
        ]), 1)
        metas = QWidget()
        caixa = QVBoxLayout(metas)
        caixa.addWidget(rosca("Alocação desejada", [
            (classe, parametro(self.banco, f"Meta · {classe}"), cor, "")
            for classe, cor in zip(CLASSES, CORES)
        ]))
        faixa = QHBoxLayout()
        campos = {}
        for classe in CLASSES:
            coluna = QVBoxLayout()
            coluna.addWidget(rotulo(classe))
            campo = campo_numero(parametro(self.banco, f"Meta · {classe}"))
            campo.setMaximum(100)
            campo.setSuffix(" %")
            campos[classe] = campo
            coluna.addWidget(campo)
            faixa.addLayout(coluna)
        caixa.addLayout(faixa)

        def gravar_metas():
            valores = {classe: campo.value() for classe, campo in campos.items()}
            if sum(round(valor * 100) for valor in valores.values()) != 10000:
                raise ValueError("A soma das metas precisa ser de 100%.")
            self.banco.executemany("INSERT OR REPLACE INTO parametros VALUES (?, ?)",
                                  [(f"Meta · {classe}", valor) for classe, valor in valores.items()])

        caixa.addWidget(botao("Salvar metas", lambda: self.salvar(gravar_metas), True))
        graficos.addWidget(metas, 1)
        corpo.addLayout(graficos)
        meses = self.banco.execute("SELECT mes, patrimonio, aporte_total FROM mensal ORDER BY mes").fetchall()
        corpo.addWidget(tabela(
            ("Classe", "Aportado", "Patrimônio", "Valorização", "Proventos"),
            [(classe, moeda(a), moeda(p), moeda(p - a if p is not None else None), moeda(d))
             for classe, (a, p, d) in zip(CLASSES, dados)],
            compacta=True,
        ))
        corpo.addWidget(grafico_linhas("Evolução mensal em reais", [mes for mes, _, _ in meses], [
            ("Patrimônio", AMBAR, [patrimonio for _, patrimonio, _ in meses]),
            ("Aporte acumulado", CORES[0], [aporte for _, _, aporte in meses]),
        ]))
        return rolavel(pagina)

    def mensal(self):
        pagina = QWidget()
        corpo = QVBoxLayout(pagina)
        faixa = QHBoxLayout()
        faixa.addWidget(rotulo("Fechamentos mensais", "secao"))
        faixa.addStretch()
        faixa.addWidget(botao("Fechar mês atual", self.dialogo_fechamento, True))
        corpo.addLayout(faixa)
        dados = self.banco.execute("SELECT * FROM mensal ORDER BY mes DESC").fetchall()
        corpo.addWidget(tabela(
            ("Mês", "Aporte mensal", "Aporte total", "Patrimônio final", "Rendimento do mês",
             "Valorização", "Rendimento total", "Div. mensal", "Div. total"),
            [(mes[5:] + "/" + mes[:4], moeda(am), moeda(at), moeda(p), moeda(gm),
              f"{numero(pc * 100)}%" if pc is not None else "—", moeda(gt), moeda(dm), moeda(dt))
             for mes, am, at, p, gm, pc, gt, dm, dt in dados],
            compacta=True,
        ))
        dados.reverse()
        meses = [linha[0] for linha in dados]
        graficos = QGridLayout()
        for i, (coluna, titulo, cor) in enumerate((
            (1, "Aporte mensal", CORES[0]), (4, "Rendimento do mês", AMBAR),
            (6, "Rendimento total", CORES[1]), (8, "Dividendo total", CORES[3]),
        )):
            graficos.addWidget(grafico_linhas(titulo, meses, [
                (titulo, cor, [linha[coluna] for linha in dados]),
            ]), i // 2, i % 2)
        corpo.addLayout(graficos)
        corpo.addStretch()
        return rolavel(pagina)

    def dialogo_fechamento(self):
        mes = QDate.currentDate().toString("yyyy-MM")
        if QMessageBox.question(self, "Fechar mês", "Salvar o patrimônio atual como fechamento de "
                                f"{mes[5:]}/{mes[:4]}?") == QMessageBox.StandardButton.Yes:
            self.salvar(lambda: fechar_mes(self.banco, mes))

    def ativos(self, classe):
        pagina = QWidget()
        corpo = QVBoxLayout(pagina)
        fixa = classe == "Renda fixa"
        exterior = classe == "ETFs"
        simbolo = "US$" if exterior else "R$"
        cor = CLASSE_COR[classe]
        pos = posicoes(self.banco, classe)
        aporte, patrimonio, proventos = totais(self.banco, classe)

        linha = QHBoxLayout()
        titulo = rotulo(classe, "titulo")
        titulo.setStyleSheet(f"color: {cor};")
        linha.addWidget(titulo)
        linha.addStretch()
        linha.addWidget(botao("+ Aporte" if fixa else "+ Novo ativo",
                              lambda: self.aporte(classe) if fixa else self.compra(classe), True))
        if fixa:
            linha.addWidget(botao("Atualizar valor", lambda: self.editar_parametro("Saldo renda fixa", "Atualizar valor (R$)")))
        else:
            linha.addWidget(botao("Atualizar", self.atualizar_cotacoes))
        if classe in CLASSES_COM_METAS:
            linha.addWidget(botao("Dividendos", lambda: self.dividendos(classe)))
        if exterior:
            linha.addWidget(botao("+ Remessa", lambda: self.aporte(classe)))
        corpo.addLayout(linha)
        if exterior:
            corpo.addWidget(self.painel_cotacao("USDBRL", "Dólar comercial · USD/BRL"),
                            alignment=Qt.AlignmentFlag.AlignLeft)
        elif classe == "Cripto":
            corpo.addWidget(self.painel_cotacao("BTCBRL", "Bitcoin · BTC/BRL"),
                            alignment=Qt.AlignmentFlag.AlignLeft)
        corpo.addWidget(rotulo(f"Aportado {moeda(aporte)}    ·    Patrimônio {moeda(patrimonio)}    ·    Proventos {moeda(proventos)}", "secao"))

        if classe in CLASSES_COM_METAS:
            graficos = QHBoxLayout()
            cores = {ativo: PALETA_ATIVOS[i % len(PALETA_ATIVOS)]
                     for i, (ativo, *_resto) in enumerate(pos)}
            dolar = parametro(self.banco, "USD/BRL", None) if exterior else None

            def resumo_atual(qtd, preco):
                if preco is None:
                    return ""
                texto = f"{quantidade(qtd)} unidades · {moeda(qtd * preco, simbolo)}"
                if dolar:
                    texto += f" · {moeda(qtd * preco * dolar, 'R$')}"
                return texto

            graficos.addWidget(rosca("Alocação atual", [
                (ativo, qtd * preco if preco is not None else None, cores[ativo], resumo_atual(qtd, preco))
                for ativo, qtd, _, preco in pos
            ]), 1)
            graficos.addWidget(rosca("Alocação desejada", [
                (ativo, parametro(self.banco, f"Meta de ativo · {classe} · {ativo}"), cores[ativo], "")
                for ativo, *_resto in pos
            ]), 1)
            corpo.addLayout(graficos)
            if pos:
                corpo.addWidget(botao("Editar alocação desejada", lambda: self.editar_metas_ativos(classe, pos)),
                                alignment=Qt.AlignmentFlag.AlignRight)

        if pos:
            corpo.addWidget(rotulo("Meus ativos", "secao"))
            grade = QGridLayout()
            for i, registro in enumerate(pos):
                grade.addWidget(self.cartao_ativo(classe, registro), i // 3, i % 3,
                                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            for coluna in range(3):
                grade.setColumnStretch(coluna, 1)
            corpo.addLayout(grade)
        elif not fixa:
            corpo.addWidget(rotulo("Cadastre seu primeiro ativo em + Novo ativo."))
        if fixa or exterior:
            aportes = self.banco.execute(
                "SELECT dia, reais, dolares FROM aportes WHERE classe=? ORDER BY dia DESC", (classe,)
            ).fetchall()
            corpo.addWidget(rotulo("Remessas" if exterior else "Histórico de aportes", "secao"))
            for dia, reais, dolares in aportes:
                detalhe = f"{moeda(reais)} → {moeda(dolares, 'US$')}" if exterior else moeda(reais)
                corpo.addWidget(registro_visual(data_br(dia), detalhe))
        historico = dict(self.banco.execute(
            "SELECT mes, ganho_mes FROM mensal_classe WHERE classe=? ORDER BY mes", (classe,)
        ))
        aportes = aportes_por_mes(self.banco, classe)
        meses = sorted(historico.keys() | aportes.keys())
        if meses:
            meses = intervalo_meses(meses[0], meses[-1])[-12:]
        corpo.addWidget(grafico_barras("Rendimento do mês", [(mes, historico.get(mes)) for mes in meses], cor))
        titulo_aporte = "Aporte mensal · Remessas em reais" if exterior else "Aporte mensal"
        corpo.addWidget(grafico_barras(titulo_aporte, [(mes, aportes.get(mes, 0)) for mes in meses], cor))
        corpo.addStretch()
        return rolavel(pagina)

    def editar_metas_ativos(self, classe, pos):
        campos = {}
        for ativo, *_resto in pos:
            chave = f"Meta de ativo · {classe} · {ativo}"
            campo = campo_numero(parametro(self.banco, chave))
            campo.setMaximum(100)
            campo.setSuffix(" %")
            campos[chave] = ativo, campo

        def gravar():
            valores = [(chave, campo.value()) for chave, (_, campo) in campos.items()]
            if sum(round(valor * 100) for _, valor in valores) != 10000:
                raise ValueError("A soma das metas precisa ser de 100%.")
            self.banco.executemany("INSERT OR REPLACE INTO parametros VALUES (?, ?)", valores)

        self.formulario("Alocação desejada · " + classe, list(campos.values()), gravar)

    def cartao_ativo(self, classe, registro):
        ativo, qtd, custo, preco = registro
        simbolo = "US$" if classe == "ETFs" else "R$"
        patrimonio = qtd * preco if preco is not None else None
        cartao = QWidget(objectName="cartao")
        caixa = QVBoxLayout(cartao)
        caixa.setContentsMargins(12, 8, 12, 10)
        caixa.setSpacing(4)
        faixa = QHBoxLayout()
        nome = rotulo(ativo, "secao")
        nome.setStyleSheet(f"color: {CLASSE_COR[classe]};")
        faixa.addWidget(nome, 1)
        mais = botao("+", lambda: self.compra(classe, ativo, preco))
        mais.setProperty("tipo", "compacto")
        mais.setToolTip("Adicionar aporte")
        faixa.addWidget(mais)
        detalhes = botao("…", lambda: self.historico_ativo(classe, ativo))
        detalhes.setProperty("tipo", "compacto")
        detalhes.setToolTip("Informações completas do ativo")
        faixa.addWidget(detalhes)
        caixa.addLayout(faixa)
        saldo = rotulo(moeda(patrimonio, simbolo), "valor")
        saldo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        saldo.setToolTip("Patrimônio atual")
        caixa.addWidget(saldo)
        grade = QFormLayout()
        grade.setVerticalSpacing(2)
        grade.setHorizontalSpacing(16)
        for legenda, valor in (
            ("Quantidade", quantidade(qtd)), ("Preço médio", moeda(custo / qtd if qtd else None, simbolo)),
            ("Preço atual", moeda(preco, simbolo)), ("Total aportado", moeda(custo, simbolo)),
            ("Rendimento total", moeda(patrimonio - custo if patrimonio is not None else None, simbolo)),
        ):
            dado = rotulo(valor, "dado")
            dado.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grade.addRow(rotulo(legenda), dado)
        caixa.addLayout(grade)
        if classe in CLASSES_COM_METAS:
            dividendos = botao("Dividendos", lambda: self.dividendos(classe, ativo))
            dividendos.setProperty("tipo", "compacto")
            caixa.addWidget(dividendos, alignment=Qt.AlignmentFlag.AlignHCenter)
        return cartao

    def historico_ativo(self, classe, ativo):
        janela = QDialog(self)
        janela.setWindowTitle(f"{ativo} · Informações completas")
        janela.resize(650, 520)
        corpo = QVBoxLayout(janela)
        corpo.addWidget(rotulo(f"{ativo} · Histórico de aportes", "titulo"))
        conteudo = QWidget()
        lista = QVBoxLayout(conteudo)
        simbolo = "US$" if classe == "ETFs" else "R$"
        for dia, qtd, preco, custo, cotacao in self.banco.execute(
            "SELECT dia, quantidade, preco, custo, cotacao_registrada FROM compras "
            "WHERE classe=? AND ativo=? ORDER BY dia DESC, rowid DESC", (classe, ativo),
        ):
            lista.addWidget(registro_visual(
                f"{data_br(dia)}  ·  {moeda(custo, simbolo)}",
                f"{quantidade(qtd)} unidades · Preço pago por unidade {moeda(preco, simbolo)}\n"
                f"Cotação no momento do aporte {moeda(cotacao, simbolo)}",
            ))
        lista.addStretch()
        corpo.addWidget(rolavel(conteudo))
        janela.exec()

    def compra(self, classe, ticker=None, cotacao=None):
        dia = campo_data()
        ativo = QLineEdit(ticker or "")
        ativo.setReadOnly(ticker is not None)
        qtd, custo = campo_numero(casas=8), campo_numero()
        simbolo = "US$" if classe == "ETFs" else "R$"

        def gravar():
            codigo = ativo.text().strip().upper()
            if not codigo or min(qtd.value(), custo.value()) <= 0:
                raise ValueError("Informe o código do ativo, a quantidade e o valor total.")
            if ticker is None and self.banco.execute(
                "SELECT 1 FROM compras WHERE classe=? AND ativo=? COLLATE NOCASE", (classe, codigo)
            ).fetchone():
                raise ValueError("O ativo já existe. Use o botão + do cartão para registrar o aporte.")
            if ticker is not None:
                codigo = ticker
            self.banco.execute(
                "INSERT INTO compras (classe, dia, ativo, quantidade, preco, custo, cotacao_registrada) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (classe, dia.date().toString("yyyy-MM-dd"), codigo, qtd.value(),
                 custo.value() / qtd.value(), custo.value(), cotacao),
            )

        if self.formulario(f"Adicionar aporte · {ticker}" if ticker else f"Novo ativo · {classe}", [
            ("Código do ativo", ativo), ("Data", dia), ("Quantidade", qtd),
            (f"Valor total do aporte ({simbolo})", custo),
        ], gravar, "Salvar aporte" if ticker else "Criar ativo e salvar aporte"):
            self.buscar_mercado()

    def aporte(self, classe):
        dia, reais, dolares = campo_data(), campo_numero(), campo_numero()
        exterior = classe == "ETFs"

        def gravar():
            if reais.value() <= 0 or (exterior and dolares.value() <= 0):
                raise ValueError("Informe valores maiores que zero.")
            self.banco.execute("INSERT INTO aportes VALUES (?, ?, ?, ?)",
                               (classe, dia.date().toString(Qt.DateFormat.ISODate), reais.value(), dolares.value()))

        campos = [("Data", dia), ("Valor pago (R$)", reais)]
        if exterior:
            campos.append(("Valor recebido após taxas (US$)", dolares))
        self.formulario("Registrar remessa" if exterior else "Registrar aporte", campos, gravar)

    def editar_parametro(self, nome, legenda, casas=2):
        valor = campo_numero(parametro(self.banco, nome), casas)

        def gravar():
            if nome == "USD/BRL" and valor.value() <= 0:
                raise ValueError("Informe um câmbio maior que zero.")
            self.banco.execute("INSERT OR REPLACE INTO parametros VALUES (?, ?)", (nome, valor.value()))

        self.formulario(legenda, [(legenda, valor)], gravar)

    def dividendos(self, classe, ticker=None):
        janela = QDialog(self)
        janela.setWindowTitle(f"Dividendos · {classe}")
        janela.resize(1000, 630)
        corpo = QVBoxLayout(janela)
        corpo.addWidget(rotulo(f"Dividendos · {classe}", "titulo"))
        faixa = QHBoxLayout()
        ativos = QComboBox()
        ativos.addItem("Todos os ativos", None)
        codigos = {a for a, *_ in posicoes(self.banco, classe)}
        codigos.update(a for a, in self.banco.execute("SELECT DISTINCT ativo FROM proventos WHERE classe=?", (classe,)) if a)
        for codigo in sorted(codigos):
            ativos.addItem(codigo, codigo)
        if ticker:
            ativos.setCurrentIndex(ativos.findData(ticker))
        periodo = QComboBox()
        periodo.addItems(["Últimos 12 meses", "Todo o histórico"])
        faixa.addWidget(rotulo("Ativo"))
        faixa.addWidget(ativos)
        faixa.addWidget(rotulo("Período"))
        faixa.addWidget(periodo)
        faixa.addStretch()
        faixa.addWidget(botao("+ Registrar dividendo", lambda: registrar(), True))
        corpo.addLayout(faixa)
        painel = QVBoxLayout()
        corpo.addLayout(painel)
        simbolo = "US$" if classe == "ETFs" else "R$"

        def preencher():
            while painel.count():
                painel.takeAt(0).widget().deleteLater()
            codigo = ativos.currentData()
            fim = QDate.currentDate().toString("yyyy-MM")
            inicio = QDate.currentDate().addMonths(-11).toString("yyyy-MM")
            registros = self.banco.execute(
                "SELECT dia, ativo, valor FROM proventos WHERE classe=? AND (? IS NULL OR ativo=?) "
                "AND (? OR substr(dia, 1, 7) BETWEEN ? AND ?) ORDER BY dia DESC, rowid DESC",
                (classe, codigo, codigo, periodo.currentIndex() == 1, inicio, fim),
            ).fetchall()
            mensal = {}
            for dia, _, valor in registros:
                mensal[dia[:7]] = mensal.get(dia[:7], 0) + valor
            if periodo.currentIndex() == 1 and mensal:
                inicio, fim = min(mensal), max(mensal)
            meses = intervalo_meses(inicio, fim)
            total = sum(mensal.values())
            resumo = QHBoxLayout()
            resumo.addWidget(registro_visual("Total recebido", moeda(total, simbolo)))
            resumo.addWidget(registro_visual("Último pagamento",
                f"{data_br(registros[0][0])} · {moeda(registros[0][2], simbolo)}" if registros else "—"))
            resumo.addWidget(registro_visual("Média mensal", moeda(total / len(meses), simbolo)))
            faixa_resumo = QWidget()
            faixa_resumo.setLayout(resumo)
            painel.addWidget(faixa_resumo)
            meses_grafico = meses[-12:] if periodo.currentIndex() == 0 else meses
            painel.addWidget(grafico_barras("Dividendos por mês", [
                (mes, mensal.get(mes, 0)) for mes in meses_grafico
            ] if registros else [], CLASSE_COR[classe], simbolo))
            conteudo = QWidget()
            lista = QVBoxLayout(conteudo)
            lista.addWidget(rotulo("Histórico de pagamentos", "secao"))
            for dia, ativo, valor in registros:
                lista.addWidget(registro_visual(f"{data_br(dia)} · {ativo}", moeda(valor, simbolo)))
            if not registros:
                lista.addWidget(rotulo("Nenhum dividendo neste período."))
            lista.addStretch()
            painel.addWidget(rolavel(conteudo), 1)

        def registrar():
            if self.provento(classe, ativos.currentData()):
                preencher()

        ativos.currentIndexChanged.connect(preencher)
        periodo.currentIndexChanged.connect(preencher)
        preencher()
        janela.exec()

    def provento(self, classe, ticker=None):
        dia, ativo, valor = campo_data(), QLineEdit(ticker or ""), campo_numero()
        ativo.setReadOnly(ticker is not None)

        def gravar():
            ticker = ativo.text().strip().upper()
            if not ticker or valor.value() <= 0:
                raise ValueError("Informe o ativo e o valor recebido.")
            self.banco.execute("INSERT INTO proventos VALUES (?, ?, ?, ?)",
                               (classe, dia.date().toString(Qt.DateFormat.ISODate), ticker, valor.value()))

        return self.formulario("Registrar provento", [("Data", dia), ("Ativo", ativo),
                                               ("Valor recebido (US$)" if classe == "ETFs" else "Valor recebido (R$)", valor)], gravar)


def main():
    QLocale.setDefault(QLocale("pt_BR"))
    app = QApplication([])
    app.setApplicationName("Profits")
    pasta_dados = PASTA / "dados"
    executavel = getattr(sys, "frozen", False)
    if executavel:
        pasta_dados = Path(QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation
        ))
        app.setWindowIcon(QIcon(str(RECURSOS / "moeda.png")))
    app.setStyle("Fusion")
    app.setStyleSheet(TEMA)
    caminho_banco = pasta_dados / "carteira.sqlite"
    primeiro_acesso = not caminho_banco.exists()
    banco = abrir_banco(caminho_banco)
    try:
        if executavel and primeiro_acesso:
            origem = sqlite3.connect((RECURSOS / "carteira-inicial.sqlite").as_uri() + "?mode=ro", uri=True)
            try:
                origem.backup(banco)
            finally:
                origem.close()
        elif not executavel:
            carregar_planilha_inicial(banco, PASTA / "Profits.xlsx")
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as erro:
        QMessageBox.warning(None, "Histórico da planilha", f"Falha ao carregar o histórico local.\n{erro}")
    janela = Janela(banco)
    janela.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
