"""Interface desktop da carteira."""

from pathlib import Path
import sqlite3

from PySide6.QtCharts import (
    QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QLineSeries, QPieSeries, QValueAxis,
)
from PySide6.QtCore import QDate, QLocale, Qt
from PySide6.QtGui import QColor, QCursor, QPainter
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QTabWidget,
    QScrollArea, QTableWidget, QTableWidgetItem, QToolTip, QVBoxLayout, QWidget,
)

from carteira import (
    CLASSES, abrir_banco, aportes_por_mes, carregar_planilha_inicial, fechar_mes, parametro, posicoes, totais,
)

PASTA = Path(__file__).resolve().parent
AMBAR = "#e2ad67"
CORES = ("#7ebdd2", "#a4afe7", "#e59391", "#83b9aa", "#c09bcd")
CLASSE_COR = dict(zip(CLASSES, CORES))
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


def tabela(colunas, linhas):
    grade = QTableWidget(len(linhas), len(colunas))
    grade.setHorizontalHeaderLabels(colunas)
    grade.verticalHeader().hide()
    grade.setAlternatingRowColors(True)
    grade.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    grade.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    grade.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    grade.horizontalHeader().setStretchLastSection(True)
    for i, linha in enumerate(linhas):
        for j, valor in enumerate(linha):
            grade.setItem(i, j, QTableWidgetItem(str(valor)))
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


def mostrar_fatia(fatia, mensagem, dentro):
    fatia.setExploded(dentro)
    if dentro:
        QToolTip.showText(QCursor.pos(), mensagem)
    else:
        QToolTip.hideText()


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
    for fatia, resumo in detalhes:
        fatia.setLabel(f"{fatia.label()} · {numero(fatia.percentage() * 100, 1)}%")
        mensagem = f"{fatia.label()} · {resumo}" if resumo else fatia.label()
        fatia.hovered.connect(lambda dentro, item=fatia, texto=mensagem: mostrar_fatia(item, texto, dentro))
    return vista


def mostrar_barra(dentro, indice, dados, simbolo):
    if dentro:
        mes, valor = dados[indice]
        QToolTip.showText(QCursor.pos(), f"{mes[5:]}/{mes[:4]} · {moeda(valor, simbolo)}")
    else:
        QToolTip.hideText()


def grafico_barras(titulo, dados, cor, simbolo="R$"):
    chart, vista = grafico(titulo)
    vista.setMinimumHeight(218)
    chart.legend().hide()
    valores = [valor for _, valor in dados if valor is not None]
    if not valores:
        chart.setTitle(f"{titulo} · Sem dados")
        return vista
    if any(valor is None for _, valor in dados):
        chart.setTitle(f"{titulo} · * Sem fechamento")
    barras = QBarSet(titulo)
    barras.setColor(QColor(cor))
    barras.append([valor if valor is not None else 0 for _, valor in dados])
    barras.hovered.connect(lambda dentro, i: mostrar_barra(dentro, i, dados, simbolo))
    serie = QBarSeries()
    serie.append(barras)
    chart.addSeries(serie)
    meses = QBarCategoryAxis()
    meses.append([f"{mes[5:]}/{mes[2:4]}{'*' if valor is None else ''}" for mes, valor in dados])
    chart.addAxis(meses, Qt.AlignmentFlag.AlignBottom)
    serie.attachAxis(meses)
    eixo = QValueAxis()
    eixo.setLabelFormat(f"{simbolo} %.0f")
    minimo = min(0, min(valores) * 1.12)
    maximo = max(0, max(valores) * 1.12)
    eixo.setRange(minimo, maximo if minimo != maximo else 1)
    chart.addAxis(eixo, Qt.AlignmentFlag.AlignLeft)
    serie.attachAxis(eixo)
    return vista


class Janela(QMainWindow):
    def __init__(self, banco):
        super().__init__()
        self.banco = banco
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
        evolucao, vista = grafico("Evolução mensal em reais")
        meses = self.banco.execute("SELECT mes, patrimonio, aporte_total FROM mensal ORDER BY mes").fetchall()
        if not meses:
            evolucao.setTitle("Evolução mensal · sem fechamentos")
        for coluna, nome, cor in ((1, "Patrimônio", AMBAR), (2, "Aporte acumulado", "#a78357")):
            serie = QLineSeries()
            serie.setName(nome)
            serie.setColor(QColor(cor))
            serie.setPointsVisible(True)
            for i, linha in enumerate(meses):
                serie.append(i, linha[coluna])
            evolucao.addSeries(serie)
        if meses:
            from PySide6.QtCharts import QCategoryAxis

            eixo = QCategoryAxis()
            eixo.setLabelsPosition(QCategoryAxis.AxisLabelsPosition.AxisLabelsPositionOnValue)
            eixo.setStartValue(-1)
            passo = max(1, len(meses) // 6)
            for i, linha in enumerate(meses):
                if i % passo == 0 or i == len(meses) - 1:
                    eixo.append(linha[0][5:] + "/" + linha[0][2:4], i)
            eixo.setRange(-0.18, max(1, len(meses) - 0.82))
            reais = QValueAxis()
            reais.setRange(0, max(1, max(max(m[1:]) for m in meses) * 1.1))
            reais.setLabelFormat("%.0f")
            evolucao.addAxis(eixo, Qt.AlignmentFlag.AlignBottom)
            evolucao.addAxis(reais, Qt.AlignmentFlag.AlignLeft)
            for serie in evolucao.series():
                serie.attachAxis(eixo)
                serie.attachAxis(reais)
        corpo.addWidget(vista)
        corpo.addWidget(tabela(
            ("Classe", "Aportado", "Patrimônio", "Valorização", "Proventos"),
            [(classe, moeda(a), moeda(p), moeda(p - a if p is not None else None), moeda(d))
             for classe, (a, p, d) in zip(CLASSES, dados)],
        ))
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
             "Valorização", "Rendimento total", "Dividendo mensal", "Dividendo total"),
            [(mes[5:] + "/" + mes[:4], moeda(am), moeda(at), moeda(p), moeda(gm),
              f"{numero(pc * 100)}%" if pc is not None else "—", moeda(gt), moeda(dm), moeda(dt))
             for mes, am, at, p, gm, pc, gt, dm, dt in dados],
        ))
        return pagina

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
            linha.addWidget(botao("Informar patrimônio", lambda: self.editar_parametro("Saldo renda fixa", "Patrimônio (R$)")))
        else:
            linha.addWidget(botao("Atualizar cotação", lambda: self.cotacao(classe)))
        if classe in ("FIIs", "Ações", "ETFs"):
            linha.addWidget(botao("Dividendos", lambda: self.dividendos(classe)))
        if exterior:
            linha.addWidget(botao("+ Remessa", lambda: self.aporte(classe)))
            linha.addWidget(botao("Informar câmbio", lambda: self.editar_parametro("USD/BRL", "Câmbio atual (R$/US$)", 6)))
        corpo.addLayout(linha)
        corpo.addWidget(rotulo(f"Aportado {moeda(aporte)}    ·    Patrimônio {moeda(patrimonio)}    ·    Proventos {moeda(proventos)}", "secao"))

        graficos = QHBoxLayout()
        if classe in ("FIIs", "Ações", "ETFs"):
            base = QColor(cor)
            graficos.addWidget(rosca(f"Distribuição · {classe}", [
                (ativo, qtd * preco if preco is not None else None,
                 base.lighter(76 + 14 * (i % 6)).name(),
                 f"{quantidade(qtd)} unidades · {moeda(qtd * preco, simbolo)}" if preco is not None else "")
                for i, (ativo, qtd, _, preco) in enumerate(pos)
            ]), 1)
        barras = QVBoxLayout()
        historico = dict(self.banco.execute(
            "SELECT mes, ganho_mes FROM mensal_classe WHERE classe=? ORDER BY mes", (classe,)
        ))
        aportes = aportes_por_mes(self.banco, classe)
        meses = sorted(historico.keys() | aportes.keys())
        if meses:
            meses = intervalo_meses(meses[0], meses[-1])[-12:]
        barras.addWidget(grafico_barras("Rendimento do mês", [(mes, historico.get(mes)) for mes in meses], cor))
        barras.addWidget(grafico_barras("Aporte mensal", [(mes, aportes.get(mes, 0)) for mes in meses], cor))
        graficos.addLayout(barras, 2)
        corpo.addLayout(graficos)

        if pos:
            corpo.addWidget(rotulo("Meus ativos", "secao"))
            grade = QGridLayout()
            for i, registro in enumerate(pos):
                grade.addWidget(self.cartao_ativo(classe, registro), i // 3, i % 3)
                grade.setColumnStretch(i % 3, 1)
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
        corpo.addStretch()
        return rolavel(pagina)

    def cartao_ativo(self, classe, registro):
        ativo, qtd, custo, preco = registro
        simbolo = "US$" if classe == "ETFs" else "R$"
        patrimonio = qtd * preco if preco is not None else None
        cartao = QWidget(objectName="cartao")
        caixa = QVBoxLayout(cartao)
        caixa.setContentsMargins(16, 14, 16, 14)
        faixa = QHBoxLayout()
        nome = rotulo(ativo, "secao")
        nome.setStyleSheet(f"color: {CLASSE_COR[classe]};")
        faixa.addWidget(nome, 1)
        mais = botao("+", lambda: self.compra(classe, ativo, preco))
        mais.setToolTip("Adicionar aporte")
        faixa.addWidget(mais)
        detalhes = botao("…", lambda: self.historico_ativo(classe, ativo))
        detalhes.setToolTip("Informações completas do ativo")
        faixa.addWidget(detalhes)
        caixa.addLayout(faixa)
        caixa.addWidget(rotulo(moeda(patrimonio, simbolo), "valor"))
        grade = QFormLayout()
        for legenda, valor in (
            ("Quantidade", quantidade(qtd)), ("Preço médio", moeda(custo / qtd if qtd else None, simbolo)),
            ("Preço atual", moeda(preco, simbolo)), ("Total aportado", moeda(custo, simbolo)),
            ("Rendimento total", moeda(patrimonio - custo if patrimonio is not None else None, simbolo)),
        ):
            grade.addRow(rotulo(legenda), rotulo(valor, "dado"))
        caixa.addLayout(grade)
        if classe in ("FIIs", "Ações", "ETFs"):
            caixa.addWidget(botao("Dividendos", lambda: self.dividendos(classe, ativo)))
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
                f"Cotação informada no aporte {moeda(cotacao, simbolo)}",
            ))
        lista.addStretch()
        corpo.addWidget(rolavel(conteudo))
        janela.exec()

    def compra(self, classe, ticker=None, cotacao=None):
        dia = campo_data()
        ativo = QLineEdit(ticker or "")
        ativo.setReadOnly(ticker is not None)
        qtd, custo = campo_numero(casas=8), campo_numero()
        preco = campo_numero(cotacao, casas=8)
        simbolo = "US$" if classe == "ETFs" else "R$"

        def gravar():
            codigo = ativo.text().strip().upper()
            if not codigo or min(qtd.value(), preco.value(), custo.value()) <= 0:
                raise ValueError("Informe o código do ativo, a quantidade, o valor total e o preço atual.")
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
                 custo.value() / qtd.value(), custo.value(), preco.value()),
            )
            self.banco.execute("INSERT OR REPLACE INTO cotacoes VALUES (?, ?, ?)", (classe, codigo, preco.value()))

        self.formulario(f"Adicionar aporte · {ticker}" if ticker else f"Novo ativo · {classe}", [
            ("Código do ativo", ativo), ("Data", dia), ("Quantidade", qtd),
            (f"Valor total do aporte ({simbolo})", custo), (f"Preço atual por unidade ({simbolo})", preco),
        ], gravar, "Salvar aporte" if ticker else "Criar ativo e salvar aporte")

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

    def cotacao(self, classe):
        ativo, preco = QComboBox(), campo_numero(casas=6)
        pos = posicoes(self.banco, classe)
        if not pos:
            QMessageBox.information(self, "Cotação", "Registre uma compra para adicionar o ativo à carteira.")
            return
        ativo.addItems([a for a, *_ in pos])
        ativo.currentIndexChanged.connect(lambda i: preco.setValue(pos[i][3] or 0))
        preco.setValue(pos[0][3] or 0)

        def gravar():
            if preco.value() <= 0:
                raise ValueError("Informe uma cotação maior que zero.")
            self.banco.execute("INSERT OR REPLACE INTO cotacoes VALUES (?, ?, ?)", (classe, ativo.currentText(), preco.value()))

        self.formulario("Informar cotação", [("Ativo", ativo), ("Preço (US$)" if classe == "ETFs" else "Preço (R$)", preco)], gravar)

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
    app.setStyle("Fusion")
    app.setStyleSheet(TEMA)
    banco = abrir_banco(PASTA / "dados" / "carteira.sqlite")
    try:
        carregar_planilha_inicial(banco, PASTA / "Profits.xlsx")
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as erro:
        QMessageBox.warning(None, "Histórico da planilha", f"Falha ao carregar o histórico local.\n{erro}")
    janela = Janela(banco)
    janela.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
