"""Interface desktop da carteira."""

from pathlib import Path

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QPieSeries, QValueAxis
from PySide6.QtCore import QDate, QLocale, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from carteira import CLASSES, abrir_banco, fechar_mes, importar, parametro, posicoes, totais

PASTA = Path(__file__).resolve().parent
CORES = ("#59ddad", "#67a7fb", "#ac93fc", "#ffc879", "#f18bad")
TEMA = """
QWidget { background:#101318; color:#eef2fa; font-family:'Segoe UI'; font-size:14px; }
QLabel[tipo="titulo"] {font-size:27px; font-weight:700;}
QLabel[tipo="secao"] {font-size:17px; font-weight:600; }
QLabel[tipo="valor"] {font-size:24px; font-weight:650; color:#59ddad;}
QLabel[tipo="nota"] {color:#aab6c9;}
QWidget#cartao {background:#1b222c; border:1px solid #303b4b; border-radius:10px;}
QWidget#cartao QLabel {background:transparent;}
QPushButton {background:#232e3b; border:1px solid #3a495d; border-radius:6px; padding:8px 14px;}
QPushButton:hover {background:#334358;}
QPushButton[tipo="principal"] {background:#59ddad; color:#102019; font-weight:700;}
QPushButton[tipo="principal"]:hover {background:#87ebc5;}
QLineEdit, QDateEdit, QDoubleSpinBox, QComboBox {background:#1b222c; padding:6px;}
QTabBar::tab {background:#19212c; padding:12px 18px; border-bottom:2px solid #19212c;}
QTabBar::tab:selected {background:#263241; border-bottom:2px solid #59ddad;}
QTabWidget::pane {border:0;}
QTableWidget {background:#171d26; alternate-background-color:#1e2632; border:0; gridline-color:#303b4b;}
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
    item.setBackgroundBrush(QColor("#1b222c"))
    item.setTitle(titulo)
    item.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
    vista = QChartView(item)
    vista.setRenderHint(QPainter.RenderHint.Antialiasing)
    vista.setMinimumHeight(275)
    return item, vista


class Janela(QMainWindow):
    def __init__(self, banco):
        super().__init__()
        self.banco = banco
        self.setWindowTitle("Profits · 0.1.0")
        self.resize(1250, 790)
        raiz = QWidget()
        layout = QVBoxLayout(raiz)
        layout.setContentsMargins(22, 18, 22, 18)
        faixa = QHBoxLayout()
        faixa.addWidget(rotulo("Profits", "titulo"))
        faixa.addStretch()
        faixa.addWidget(botao("Importar planilha", self.importar_planilha))
        layout.addLayout(faixa)
        self.abas = QTabWidget()
        layout.addWidget(self.abas)
        self.setCentralWidget(raiz)
        self.atualizar()

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
        except (ValueError, OSError, KeyError, TypeError) as erro:
            QMessageBox.warning(self, "Confira os dados", str(erro))
        else:
            self.atualizar()

    def importar_planilha(self):
        arquivo, _ = QFileDialog.getOpenFileName(self, "Importar carteira", str(PASTA), "Excel (*.xlsx)")
        if arquivo:
            self.salvar(lambda: importar(self.banco, arquivo))

    def formulario(self, titulo, campos, gravar):
        janela = QDialog(self)
        janela.setWindowTitle(titulo)
        janela.setMinimumWidth(410)
        form = QFormLayout(janela)
        for legenda, campo in campos:
            form.addRow(legenda, campo)
        botoes = QDialogButtonBox()
        botao_salvar = botoes.addButton("Salvar", QDialogButtonBox.ButtonRole.AcceptRole)
        botoes.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        botoes.rejected.connect(janela.reject)

        def executar():
            try:
                with self.banco:
                    gravar()
            except ValueError as erro:
                QMessageBox.warning(janela, "Confira os dados", str(erro))
            else:
                janela.accept()

        botao_salvar.clicked.connect(executar)
        form.addRow(botoes)
        if janela.exec() == QDialog.DialogCode.Accepted:
            self.atualizar()

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
        alocacao, vista = grafico("Alocação por classe")
        pizza = QPieSeries()
        pizza.setHoleSize(0.53)
        for classe, grupo, cor in zip(CLASSES, dados, CORES):
            if grupo[1] is not None and grupo[1] > 0:
                fatia = pizza.append(classe, grupo[1])
                fatia.setColor(QColor(cor))
        for fatia in pizza.slices():
            fatia.setLabel(f"{fatia.label()} · {numero(fatia.percentage() * 100, 1)}%")
        alocacao.addSeries(pizza)
        if not pizza.count():
            alocacao.setTitle("Alocação por classe · sem posições avaliadas")
        graficos.addWidget(vista, 2)
        evolucao, vista = grafico("Evolução mensal em reais")
        meses = self.banco.execute("SELECT mes, patrimonio, aporte_total FROM mensal ORDER BY mes").fetchall()
        if not meses:
            evolucao.setTitle("Evolução mensal · sem fechamentos")
        for coluna, nome, cor in ((1, "Patrimônio", CORES[0]), (2, "Aporte acumulado", CORES[1])):
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
        graficos.addWidget(vista, 3)
        corpo.addLayout(graficos, 1)
        corpo.addWidget(tabela(
            ("Classe", "Aportado", "Patrimônio", "Valorização", "Proventos"),
            [(classe, moeda(a), moeda(p), moeda(p - a if p is not None else None), moeda(d))
             for classe, (a, p, d) in zip(CLASSES, dados)],
        ), 1)
        return pagina

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
        aporte, patrimonio, proventos = totais(self.banco, classe)
        saldo = rotulo(f"Aportado {moeda(aporte)}    ·    Patrimônio {moeda(patrimonio)}    ·    Proventos {moeda(proventos)}", "secao")
        corpo.addWidget(saldo)
        linha = QHBoxLayout()
        fixa = classe == "Renda fixa"
        exterior = classe == "ETFs"
        simbolo = "US$" if exterior else "R$"
        linha.addWidget(botao("+ Aporte" if fixa else "+ Compra",
                              lambda: self.aporte(classe) if fixa else self.compra(classe), True))
        if fixa:
            linha.addWidget(botao("Informar patrimônio", lambda: self.editar_parametro("Saldo renda fixa", "Patrimônio (R$)")))
        else:
            linha.addWidget(botao("Informar cotação", lambda: self.cotacao(classe)))
        if classe in ("FIIs", "Ações", "ETFs"):
            linha.addWidget(botao("+ Provento", lambda: self.provento(classe)))
        if exterior:
            linha.addWidget(botao("+ Remessa", lambda: self.aporte(classe)))
            linha.addWidget(botao("Informar câmbio", lambda: self.editar_parametro("USD/BRL", "Câmbio atual (R$/US$)", 6)))
        linha.addStretch()
        corpo.addLayout(linha)
        if not fixa:
            corpo.addWidget(rotulo("Posições", "secao"))
            corpo.addWidget(tabela(
                ("Ativo", "Quantidade", "Preço médio", "Última cotação", "Valor da posição"),
                [(ativo, numero(qtd, 8).rstrip("0").rstrip(","), moeda(custo / qtd, simbolo), moeda(preco, simbolo),
                  moeda(qtd * preco if preco is not None else None, simbolo))
                 for ativo, qtd, custo, preco in posicoes(self.banco, classe)],
            ))
        historico = QTabWidget()
        if not fixa:
            compras = self.banco.execute(
                "SELECT dia, ativo, quantidade, preco, custo FROM compras WHERE classe=? ORDER BY dia DESC, rowid DESC",
                (classe,),
            )
            historico.addTab(tabela(
                ("Data", "Ativo", "Quantidade", "Preço unitário", "Valor pago"),
                [(d, a, numero(q, 8), moeda(p, simbolo), moeda(c, simbolo)) for d, a, q, p, c in compras],
            ), "Compras")
        if fixa or exterior:
            aportes = self.banco.execute(
                "SELECT dia, reais, dolares FROM aportes WHERE classe=? ORDER BY dia DESC", (classe,)
            )
            historico.addTab(tabela(
                ("Data", "Aporte em reais", "Dólares recebidos") if exterior else ("Data", "Aporte"),
                [(d, moeda(r), moeda(u, "US$")) if exterior else (d, moeda(r)) for d, r, u in aportes],
            ), "Remessas" if exterior else "Aportes")
        if classe in ("FIIs", "Ações", "ETFs"):
            rendas = self.banco.execute(
                "SELECT dia, ativo, valor FROM proventos WHERE classe=? ORDER BY dia DESC", (classe,)
            )
            historico.addTab(tabela(("Data", "Ativo", "Valor recebido"),
                                    [(d, a, moeda(v, simbolo)) for d, a, v in rendas]), "Proventos")
        corpo.addWidget(historico)
        if not fixa:
            corpo.addWidget(rotulo("Avaliação pela última cotação salva."))
        return pagina

    def compra(self, classe):
        dia, ativo = campo_data(), QComboBox()
        ativo.setEditable(True)
        ativo.addItems([a for a, *_ in posicoes(self.banco, classe)])
        ativo.setCurrentIndex(-1)
        qtd, preco, custo = campo_numero(casas=8), campo_numero(casas=6), campo_numero()
        simbolo = "US$" if classe == "ETFs" else "R$"
        qtd.valueChanged.connect(lambda _: custo.setValue(qtd.value() * preco.value()))
        preco.valueChanged.connect(lambda _: custo.setValue(qtd.value() * preco.value()))

        def gravar():
            ticker = ativo.currentText().strip().upper()
            if not ticker or min(qtd.value(), preco.value(), custo.value()) <= 0:
                raise ValueError("Informe o ativo, a quantidade, o preço e o valor pago.")
            self.banco.execute("INSERT INTO compras VALUES (?, ?, ?, ?, ?, ?)",
                               (classe, dia.date().toString(Qt.DateFormat.ISODate), ticker,
                                qtd.value(), preco.value(), custo.value()))

        self.formulario("Registrar compra", [("Data", dia), ("Ativo ou código novo", ativo), ("Quantidade", qtd),
                                            (f"Preço unitário ({simbolo})", preco), (f"Valor pago ({simbolo})", custo)], gravar)

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

    def provento(self, classe):
        dia, ativo, valor = campo_data(), QLineEdit(), campo_numero()

        def gravar():
            ticker = ativo.text().strip().upper()
            if not ticker or valor.value() <= 0:
                raise ValueError("Informe o ativo e o valor recebido.")
            self.banco.execute("INSERT INTO proventos VALUES (?, ?, ?, ?)",
                               (classe, dia.date().toString(Qt.DateFormat.ISODate), ticker, valor.value()))

        self.formulario("Registrar provento", [("Data", dia), ("Ativo", ativo),
                                               ("Valor recebido (US$)" if classe == "ETFs" else "Valor recebido (R$)", valor)], gravar)


def main():
    QLocale.setDefault(QLocale(QLocale.Language.Portuguese, QLocale.Territory.Brazil))
    app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(TEMA)
    banco = abrir_banco(PASTA / "dados" / "carteira.sqlite")
    janela = Janela(banco)
    janela.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
