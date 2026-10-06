"""Maquetación del PDF: portada con el resumen, ficha de cada alerta y réplica de sus facturas."""
import pandas as pd
from reportlab.graphics.barcode import code128
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.platypus import (Flowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

import alertas as al
import config
from formato import fecha_corta, fecha_larga, kg, limpia, mxn, nz
from graficos import grafica, historico_de

c = colors.HexColor
ST = {
    "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=19, leading=23, textColor=c(config.INK)),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=c(config.INK)),
    "h3": ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=8, leading=11, textColor=c(config.MUTED),
                         spaceAfter=3),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9, leading=12.5, textColor=c(config.INK)),
    "small": ParagraphStyle("small", fontName="Helvetica", fontSize=7.5, leading=10, textColor=c(config.MUTED)),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8, leading=10, textColor=c(config.INK)),
    "cellr": ParagraphStyle("cellr", fontName="Helvetica", fontSize=8, leading=10, textColor=c(config.INK),
                            alignment=TA_RIGHT),
    "etq": ParagraphStyle("etq", fontName="Helvetica", fontSize=8, leading=10, textColor=c(config.MUTED)),
}


# --- Bloques comunes --------------------------------------------------------------------------------------------
def tabla(datos, anchos, der=(), extra=()):
    t = Table(datos, colWidths=anchos, repeatRows=1)
    est = [("FONT", (0, 0), (-1, -1), "Helvetica", 8), ("TEXTCOLOR", (0, 0), (-1, -1), c(config.INK)),
           ("LINEBELOW", (0, 0), (-1, -1), .4, c(config.LINE)), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
           ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
           ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7), ("TEXTCOLOR", (0, 0), (-1, 0), c(config.MUTED)),
           ("LINEBELOW", (0, 0), (-1, 0), .8, c(config.INK))]
    est += [("ALIGN", (col, 0), (col, -1), "RIGHT") for col in der]
    t.setStyle(TableStyle(est + list(extra)))
    return t


def kpis(items, ancho):
    celdas = [[Paragraph(f'<font size="6.8" color="{config.MUTED}">{e.upper()}</font><br/>'
                         f'<font name="Helvetica-Bold" size="14" color="{col or config.INK}">{v}</font>', ST["body"])
               for e, v, col in items]]
    t = Table(celdas, colWidths=[ancho / len(items)] * len(items), rowHeights=[15 * mm])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), .6, c(config.LINE)),
                           ("INNERGRID", (0, 0), (-1, -1), .6, c(config.LINE)),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    return t


def caja(contenido, ancho, fondo=config.BAND, borde=None):
    t = Table([[contenido]], colWidths=[ancho])
    est = [("BACKGROUND", (0, 0), (-1, -1), c(fondo)), ("LEFTPADDING", (0, 0), (-1, -1), 9),
           ("RIGHTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 7),
           ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]
    if borde:
        est.append(("LINEBEFORE", (0, 0), (0, -1), 2.5, c(borde)))
    t.setStyle(TableStyle(est))
    return t


# --- Ficha (evidencia numérica) ---------------------------------------------------------------------------------
def _cabecera(g, ancho):
    texto = "GRAVE · POR DEBAJO DEL PRECIO" if g.dif < 0 else "GRAVE · POR ENCIMA DEL PRECIO"
    sev = Table([[Paragraph(f'<font color="white" name="Helvetica-Bold" size="7.5">&nbsp;{texto}&nbsp;</font>',
                            ST["small"])]],
                style=[("BACKGROUND", (0, 0), (-1, -1), c(config.CRIT if g.dif < 0 else config.WARN)),
                       ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                       ("LEFTPADDING", (0, 0), (-1, -1), 2)])
    sev.hAlign = "LEFT"
    verbo = "vendido a" if g.ops == 1 else f"vendido {g.ops} veces a"
    tit = Paragraph(f"{g.nombre_material} {verbo} {mxn(g.precio, 2)}/kg frente a {mxn(g.esperado, 2)}/kg esperado",
                    ST["h2"])
    cliente = g.cliente + (f" · {g.n_clientes} tiendas" if g.publico and g.n_clientes > 1 else "")
    quien = Paragraph(f"<b>{g.sociedad}</b> · {g.nombre_sociedad}<br/>{cliente}<br/>Material {g.material} · unidad "
                      f"{g.unidad}<br/>Venta del {fecha_corta(g.fecha)}",
                      ParagraphStyle("q", parent=ST["small"], alignment=TA_RIGHT))
    t = Table([[[sev, Spacer(1, 4), tit], quien]], colWidths=[ancho * .66, ancho * .34])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 1.4, c(config.INK)),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return t


def _motivo(g):
    if g.precio < g.esperado / 2:
        return (f"El precio ({mxn(g.precio, 2)}/kg) es menos de la mitad de la mediana de 30 días del material "
                f"({mxn(g.esperado, 2)}/kg; mitad = {mxn(g.esperado / 2, 2)}).")
    return (f"El precio ({mxn(g.precio, 2)}/kg) es más del doble de la mediana de 30 días del material "
            f"({mxn(g.esperado, 2)}/kg; doble = {mxn(g.esperado * 2, 2)}).")


def _contexto(g, h):
    cli = h[h.es_cliente & ~h.es_alerta]
    otros = h[~h.es_cliente]
    partes = []
    if len(cli) >= 3:
        med = cli.precio_kg.median()
        if g.dif < 0:
            n_igual, cmp = int((cli.precio_kg <= g.precio * 1.02).sum()), "igual o menor"
        else:
            n_igual, cmp = int((cli.precio_kg >= g.precio * .98).sum()), "igual o mayor"
        quien = ("este cliente" if g.n_clientes == 1 else
                 "estas tiendas" if g.publico else f"estos {g.n_clientes} clientes")
        verbo = "compró" if g.n_clientes == 1 else "compraron"
        texto = f"En los últimos 6 meses {quien} {verbo} {len(cli)} veces este material a una mediana de {mxn(med, 2)}/kg"
        if n_igual:
            texto += f"; en {n_igual} ocasiones a un precio {cmp} que el de esta venta"
        partes.append(texto + ".")
        partes.append(f"Frente a su propio histórico, la diferencia sería de {mxn((g.precio - med) * g.kg, signo=True)} "
                      f"en lugar de {mxn(g.dif, signo=True)}.")
    elif len(cli) == 0:
        partes.append("No hay compras anteriores de este cliente en los últimos 6 meses: es una venta nueva.")
    if len(otros) >= 5:
        partes.append(f"Otros clientes de {g.sociedad} pagaron una mediana de {mxn(otros.precio_kg.median(), 2)}/kg en "
                      f"el mismo periodo ({len(otros):,} líneas de factura).")
    if g.dif > 0:
        partes.append("La venta está por encima del precio habitual: conviene revisar si es un error de captura de "
                      "unidades o un precio pactado.")
    return " ".join(partes)


def _datos_venta(g, cf_al, fact_al, cf_ref, r_ref, info, ancho):
    def precio_en(cf):
        if cf is None:
            return "-"
        l = cf[cf.NoIdentificacion.astype(str).str.lstrip("0") == g.material]
        if not len(l):
            return "-"
        return f"${l.ValorUnitario.iloc[0]:,.2f} por {config.UNIDAD.get(str(l.ClaveUnidad.iloc[0]), l.ClaveUnidad.iloc[0])}"

    nombre_cli = limpia(cf_al.ReceptorNombre.iloc[0]) if cf_al is not None else g.cliente.upper()
    if g.n_clientes > 1:
        nombre_cli += f" ({g.n_clientes} tiendas)" if g.publico else f" y {g.n_clientes - 1} clientes más"
    usuario = " · ".join(x for x in [nz(info.usuario, ""), nz(info.nombre_usuario, "")] if x) or "-"
    facturas = fact_al + (f" y {len(g.facturas) - 1} más" if len(g.facturas) > 1 else "")
    ref = f"{r_ref.billing_document} del {fecha_corta(r_ref.billing_date)}" if r_ref is not None else \
        "Sin factura a precio normal en el último mes"
    filas = [
        [Paragraph("Cliente", ST["etq"]), Paragraph(f"{nombre_cli} ({str(info.cliente).lstrip('0')})", ST["cell"]),
         Paragraph("Facturó", ST["etq"]), Paragraph(usuario, ST["cell"])],
        [Paragraph("Factura de la alerta", ST["etq"]), Paragraph(facturas, ST["cell"]),
         Paragraph("Oficina de ventas", ST["etq"]), Paragraph(str(g.oficina), ST["cell"])],
        [Paragraph("Precio en la factura", ST["etq"]), Paragraph(precio_en(cf_al), ST["cell"]),
         Paragraph("Precio normal (referencia)", ST["etq"]), Paragraph(precio_en(cf_ref), ST["cell"])],
        [Paragraph("Factura de referencia", ST["etq"]), Paragraph(ref, ST["cell"]), "", ""],
    ]
    t = Table(filas, colWidths=[ancho * .17, ancho * .33, ancho * .2, ancho * .3])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), .4, c(config.LINE)), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return t


# --- Réplica de la factura impresa ------------------------------------------------------------------------------
class FacturaImpresa(Flowable):
    """Factura reconstruida desde el CFDI con el aspecto de la impresa; el producto y su precio van recuadrados."""

    def __init__(self, cab, lineas, material, cliente_sap, ancho, max_lineas=4):
        super().__init__()
        self.cab, self.cliente = cab, str(cliente_sap)
        lin = lineas.copy()
        lin["es_alerta"] = lin.NoIdentificacion.astype(str).str.lstrip("0") == material
        self.ocultas = 0
        if len(lin) > max_lineas:  # la línea del producto y sus vecinas
            pos = int(lin.reset_index(drop=True).index[lin.es_alerta.values][0]) if lin.es_alerta.any() else 0
            ini = max(0, min(pos - 1, len(lin) - max_lineas))
            self.ocultas = len(lin) - max_lineas
            lin = lin.iloc[ini:ini + max_lineas]
        self.lin = lin
        self.width = ancho
        self.fila_h, self.cab_h = 6.2 * mm, 54 * mm
        self.height = self.cab_h + 6 * mm + self.fila_h * len(lin) + (5 * mm if self.ocultas else 0)

    def _caja(self, x, y, w, h, color=config.BORDE_FACTURA, grosor=1):
        self.canv.setStrokeColor(c(color))
        self.canv.setLineWidth(grosor)
        self.canv.rect(x, y, w, h, stroke=1, fill=0)

    def _barra(self, x, y, w, h, texto, color=config.BARRA_FACTURA, tam=5.6):
        cv = self.canv
        cv.setFillColor(c(color))
        cv.rect(x, y, w, h, stroke=0, fill=1)
        cv.setFillColor(colors.white)
        cv.setFont("Helvetica-Bold", tam)
        cv.drawCentredString(x + w / 2, y + h / 2 - tam * .35, texto)

    def _valor(self, x, y, w, h, texto, tam=7):
        cv = self.canv
        self._caja(x, y, w, h, config.BARRA_FACTURA, .8)
        cv.setFillColor(colors.black)
        cv.setFont("Helvetica", tam)
        cv.drawCentredString(x + w / 2, y + h / 2 - tam * .35, texto)

    def draw(self):
        cv, cab, W, top = self.canv, self.cab, self.width, self.height
        # Emisor (el CFDI no trae su dirección: solo RFC, régimen y código postal)
        cv.setFillColor(c(config.AZUL_FACTURA))
        cv.setFont("Helvetica-Bold", 11)
        cv.drawCentredString(W * .31, top - 9 * mm, limpia(cab.EmisorNombre).upper())
        cv.setFillColor(colors.black)
        cv.setFont("Helvetica", 5.6)
        cv.drawCentredString(W * .31, top - 14 * mm, f"RFC {cab.EmisorRfc} · Régimen {cab.EmisorRegimen} · Lugar de "
                                                     f"expedición CP {cab.LugarExpedicion}")
        # Bloque FACTURA
        x0, w0 = W * .64, W * .36
        y = top - 5 * mm
        self._barra(x0, y, w0, 5 * mm, "FACTURA", config.ROJO_FACTURA, 7)
        y -= 4 * mm
        self._barra(x0, y, w0, 4 * mm, "FOLIO FISCAL")
        y -= 5 * mm
        self._valor(x0, y, w0, 5 * mm, cab.UUID, 6.6)
        y -= 4 * mm
        cw = w0 / 3
        for k, t in enumerate(["FOLIO", "SERIE", "CITA"]):
            self._barra(x0 + k * cw, y, cw, 4 * mm, t)
        y -= 11 * mm
        for k in range(3):
            self._caja(x0 + k * cw, y, cw, 11 * mm, config.BARRA_FACTURA, .8)
        folio = str(cab.Folio).lstrip("0")
        cv.setFillColor(colors.black)
        code128.Code128(folio, barHeight=5.5 * mm, barWidth=.5).drawOn(cv, x0 + .5 * mm, y + 4 * mm)
        cv.setFont("Helvetica", 6)
        cv.drawString(x0 + 3 * mm, y + 1 * mm, folio)
        cv.setFont("Helvetica", 7.5)
        cv.drawString(x0 + cw + 2 * mm, y + 7.5 * mm, str(cab.Serie))
        hw = w0 / 2
        for etq, val in [(("FECHA Y HORA DE EMISION", "FECHA Y HORA DE CERTIFICACION"), (cab.Fecha, cab.FechaTimbrado)),
                         (("SERIE CERTIFICADO CSD", "NO. SERIE CERTIFICADO SAT"),
                          (nz(cab.NoCertificado, "-"), nz(cab.NoCertificadoSAT, "-")))]:
            y -= 4 * mm
            self._barra(x0, y, hw, 4 * mm, etq[0], tam=5)
            self._barra(x0 + hw, y, hw, 4 * mm, etq[1], tam=5)
            y -= 5 * mm
            self._valor(x0, y, hw, 5 * mm, str(val[0]))
            self._valor(x0 + hw, y, hw, 5 * mm, str(val[1]))
        # Cliente
        by, bh, bw = top - self.cab_h + 1 * mm, 35 * mm, W * .36
        self._caja(0, by, bw, bh)
        filas = [("CLIENTE/BILL TO", self.cliente.lstrip("0")), (None, limpia(cab.ReceptorNombre).upper()),
                 ("DOMICILIO FISCAL", ""), (None, f"Código postal {cab.ReceptorDomicilioFiscal}"),
                 ("RFC A QUIEN SE EXPIDE", cab.ReceptorRfc),
                 ("FORMA DE PAGO", f"{cab.FormaPago} - {config.FORMA_PAGO.get(str(cab.FormaPago), '')}"),
                 ("TIPO DE DOCUMENTO", "I - Ingreso"),
                 ("USO CFDI", f"{cab.ReceptorUsoCFDI} - {config.USO_CFDI.get(str(cab.ReceptorUsoCFDI), '')}"),
                 ("REGIMEN", str(cab.ReceptorRegimen))]
        yy = by + bh - 4.2 * mm
        for etq, val in filas:
            if etq:
                cv.setFillColor(c(config.BORDE_FACTURA))
                cv.setFont("Helvetica", 7.4)
                cv.drawString(2 * mm, yy, etq)
                cv.setFillColor(colors.black)
                cv.setFont("Helvetica", 5.8)
                vx = bw * .56
                if val:
                    cv.drawString(vx, yy, simpleSplit(val, "Helvetica", 5.8, bw - vx - 1.5 * mm)[0])
            else:
                cv.setFillColor(colors.black)
                cv.setFont("Helvetica-Bold", 5.8)
                cv.drawString(2 * mm, yy, val[:60])
            yy -= 3.5 * mm if etq else 3 * mm
        # Condiciones (en lugar del destinatario, que no viene en el CFDI)
        cx, cw2 = W * .37, W * .26
        self._caja(cx, by, cw2, bh)
        cv.setFillColor(c(config.BORDE_FACTURA))
        cv.setFont("Helvetica", 8.5)
        cv.drawString(cx + 2 * mm, by + bh - 4.2 * mm, "CONDICIONES:")
        cv.setFillColor(colors.black)
        cv.setFont("Helvetica", 6.2)
        for k, t in enumerate([f"Método de pago {cab.MetodoPago}", f"Moneda {cab.Moneda}",
                               f"Exportación {cab.Exportacion}", f"Total {cab.Total:,.2f}"]):
            cv.drawString(cx + 2 * mm, by + bh - 9.5 * mm - k * 3.6 * mm, t)
        # Conceptos
        cols = [("CLAVE SAT", .09), ("CLAVE/CODE", .09), ("DESCRIPCION/DESCRIPTION", .27), ("CANT/QUANT", .1),
                ("UNIDAD", .08), ("PRECIO UNITARIO", .1), ("IMPORTE/AMOUNT", .11), ("IMPUESTO DET.", .08),
                ("DESCUENTO", .08)]
        ty = by - 8 * mm
        self._barra(0, ty, W, 6 * mm, "")
        xs, x = [], 0
        cv.setFont("Helvetica-Bold", 5.2)
        cv.setFillColor(colors.white)
        for t, f in cols:
            xs.append(x)
            cv.drawCentredString(x + W * f / 2, ty + 2.2 * mm, t)
            x += W * f
        xs.append(W)
        y = ty
        for r in self.lin.itertuples():
            y -= self.fila_h
            iva = nz(r.IVA_Traslado_Tasa, None)
            vals = [str(r.ClaveProdServ), str(r.NoIdentificacion), limpia(r.Descripcion), f"{r.Cantidad:,.3f}",
                    str(r.ClaveUnidad), f"{r.ValorUnitario:,.2f}", f"{r.Importe:,.2f}",
                    f"002-IVA({iva * 100:.0f}%)" if iva is not None else "-", f"{nz(r.Descuento_Concepto):,.2f}"]
            cv.setFillColor(colors.black)
            cv.setFont("Helvetica", 6.2)
            for k, v in enumerate(vals):
                ancho = xs[k + 1] - xs[k]
                trozos = simpleSplit(v, "Helvetica", 6.2, ancho - 2 * mm)[:2]
                for j, tz in enumerate(trozos):
                    cv.drawCentredString(xs[k] + ancho / 2,
                                         y + self.fila_h / 2 + (len(trozos) - 1) * 1.4 * mm - j * 2.8 * mm - 1, tz)
            if r.es_alerta:
                cv.setStrokeColor(c(config.ROJO_FACTURA))
                cv.setLineWidth(1.6)
                cv.rect(xs[1] - .5 * mm, y + .4 * mm, xs[3] - xs[1] + 1 * mm, self.fila_h - .8 * mm, stroke=1, fill=0)
                cv.rect(xs[5] - .5 * mm, y + .4 * mm, xs[6] - xs[5] + 1 * mm, self.fila_h - .8 * mm, stroke=1, fill=0)
        if self.ocultas:
            cv.setFillColor(c(config.MUTED))
            cv.setFont("Helvetica-Oblique", 6.2)
            cv.drawString(2 * mm, y - 4 * mm, f"… y {self.ocultas} conceptos más en esta factura")


# --- Páginas ----------------------------------------------------------------------------------------------------
def paginas_alerta(g, ctx, W):
    """Dos páginas por alerta: ficha con la evidencia numérica y facturas (referencia y alerta)."""
    h = historico_de(g, ctx.hist)
    cf_al, fact_al = al.factura_principal(g, ctx.lineas, ctx.cfdi)
    cf_ref, r_ref = al.elegir_referencia(g, ctx.candidatas[g.alerta_id], ctx.cfdi_ref)
    info = al.facturas_de(g, ctx.lineas).set_index("billing_document").loc[fact_al]
    pct = (g.precio / g.esperado - 1) * 100
    color = config.CRIT if g.dif < 0 else config.WARN

    s = [_cabecera(g, W), Spacer(1, 8),
         kpis([("Precio facturado", f"{mxn(g.precio, 2)}/kg", None),
               ("Esperado (mediana 30 d)", f"{mxn(g.esperado, 2)}/kg", None),
               ("Volumen", kg(g.kg), None),
               ("Diferencia" if g.dif < 0 else "Sobre el esperado", mxn(g.dif, signo=True), color)], W),
         Spacer(1, 8),
         caja([Paragraph(f"<b>Por qué salta la alerta.</b> {_motivo(g)} Desviación: {pct:+.0f}&nbsp;%.", ST["body"]),
               Spacer(1, 3), Paragraph(f"<b>Contexto.</b> {_contexto(g, h)}", ST["body"])], W, borde=color),
         Spacer(1, 9),
         Paragraph(f"HISTÓRICO DE PRECIO · {g.sociedad} · {g.nombre_material.upper()} · ÚLTIMOS 6 MESES · $/KG POR "
                   "LÍNEA DE FACTURA", ST["h3"]),
         grafica(g, h, W / mm, 57),
         Paragraph("Cada punto es una línea de factura. Línea discontinua: precio esperado. Zona rosa: precios que el "
                   "modelo marca como graves.", ST["small"]),
         Spacer(1, 10), Paragraph("DATOS DE LA VENTA", ST["h3"]),
         _datos_venta(g, cf_al, fact_al, cf_ref, r_ref, info, W)]
    nota = al.nota_factura(g, fact_al, ctx.lineas_fact)
    if nota:
        s += [Spacer(1, 6), Paragraph(f"<b>Nota:</b> {nota}", ST["body"])]

    s += [PageBreak(), Paragraph("Evidencia: facturas", ST["h2"]), Spacer(1, 6)]
    if cf_ref is not None:
        l = cf_ref[cf_ref.NoIdentificacion.astype(str).str.lstrip("0") == g.material].iloc[0]
        s += [KeepTogether([
            Paragraph(f"<b>Factura a precio normal</b> · {fecha_corta(r_ref.billing_date)} · "
                      f"{limpia(cf_ref.ReceptorNombre.iloc[0])} · ${l.ValorUnitario:,.2f} por "
                      f"{config.UNIDAD.get(str(l.ClaveUnidad), l.ClaveUnidad)} (${r_ref.precio_kg:,.2f}/kg)",
                      ST["body"]), Spacer(1, 3),
            FacturaImpresa(cf_ref.iloc[0], cf_ref, g.material, r_ref.customer_code, W, max_lineas=3)]),
            Spacer(1, 10)]
    else:
        s += [Paragraph("No hay en el último mes una factura de este producto a precio normal con CFDI cargado.",
                        ST["small"]), Spacer(1, 8)]
    sentido = "por debajo" if g.dif < 0 else "por encima"
    titulo = f"<b>Factura de la alerta, precio {sentido}</b> · {fecha_corta(g.fecha)} · ${g.precio:,.2f}/kg"
    if cf_al is None:
        s += [Paragraph(titulo, ST["body"]),
              Paragraph(f"La factura {fact_al} no ha llegado al sistema de CFDI en {config.PLAZO_DIAS} días; se envía la "
                        "alerta sin ella.", ST["small"])]
    elif al.es_global(cf_al):
        sap = al.lineas_sap(g, ctx.lineas, fact_al, cf_ref)
        s += [KeepTogether([
            Paragraph(titulo, ST["body"]),
            Paragraph(f"Factura global de ventas de mostrador (folio {cf_al.Folio.iloc[0]}, {len(cf_al)} tickets). El "
                      "CFDI no desglosa productos, así que las líneas de abajo son las posiciones de este producto en "
                      f"la factura SAP {fact_al}.", ST["small"]), Spacer(1, 3),
            FacturaImpresa(cf_al.iloc[0], sap, g.material, info.cliente, W, max_lineas=4)])]
    else:
        s += [KeepTogether([Paragraph(titulo, ST["body"]), Spacer(1, 3),
                            FacturaImpresa(cf_al.iloc[0], cf_al, g.material, info.cliente, W, max_lineas=4)])]
    s += [Spacer(1, 6), Paragraph("Facturas reconstruidas a partir del CFDI timbrado; no incluyen las direcciones, que "
                                  "no vienen en el CFDI.", ST["small"])]
    return s


def portada(seleccion, n_esperando, W):
    n = len(seleccion)
    s = [Paragraph("Evidencia de alertas de precio", ST["h1"]), Spacer(1, 3),
         Paragraph(fecha_larga(config.HOY), ST["small"]), Spacer(1, 10),
         Paragraph(f"Este documento incluye {n} alerta{'s' if n != 1 else ''} grave{'s' if n != 1 else ''} cuya factura "
                   "ya está disponible (o que llevan más de "
                   f"{config.PLAZO_DIAS} días esperándola). Cada alerta tiene una página con la evidencia del precio y "
                   "otra con la factura a precio normal y la factura de la alerta.", ST["body"]), Spacer(1, 10)]
    filas = [["#", "Venta", "Sociedad", "Cliente", "Producto", "Precio", "Esperado", "Impacto", "Factura"]]
    for i, g in seleccion.iterrows():
        filas.append([str(i + 1), fecha_corta(g.fecha)[:5], g.sociedad, Paragraph(g.cliente, ST["cell"]),
                      Paragraph(g.nombre_material, ST["cell"]), f"{g.precio:,.2f}", f"{g.esperado:,.2f}",
                      Paragraph(f'<font color="{config.CRIT if g.dif < 0 else config.WARN}"><b>'
                                f'{mxn(g.dif, signo=True)}</b></font>', ST["cellr"]),
                      "Sí" if g.con_factura else "No llegó"])
    s.append(tabla(filas, [W * x for x in (.04, .08, .08, .22, .25, .08, .08, .1, .07)], der=(5, 6, 7)))
    s += [Spacer(1, 4), Paragraph("Precio y esperado en $/kg. Impacto = (precio - esperado) x kilos.", ST["small"])]
    if n_esperando:
        s += [Spacer(1, 8), Paragraph(f"{n_esperando} alerta{'s' if n_esperando != 1 else ''} más "
                                      f"esper{'an' if n_esperando != 1 else 'a'} su factura y saldrá"
                                      f"{'n' if n_esperando != 1 else ''} en próximos envíos.", ST["body"])]
    return s


def construir(seleccion, ctx, ruta, n_esperando):
    d = SimpleDocTemplate(str(ruta), pagesize=letter, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=13 * mm,
                          bottomMargin=16 * mm, title=f"Evidencia de alertas de precio {config.HOY}",
                          author="Quantrue")
    W = d.width
    s = portada(seleccion, n_esperando, W)
    for _, g in seleccion.iterrows():
        s += [PageBreak()] + paginas_alerta(g, ctx, W)

    def pie(canv, doc):
        canv.saveState()
        w, _ = doc.pagesize
        canv.setStrokeColor(c(config.LINE))
        canv.line(doc.leftMargin, 13 * mm, w - doc.rightMargin, 13 * mm)
        canv.setFont("Helvetica", 7)
        canv.setFillColor(c(config.MUTED))
        canv.drawString(doc.leftMargin, 9 * mm, f"Evidencia de alertas de precio · {fecha_corta(config.HOY)}")
        canv.drawRightString(w - doc.rightMargin, 9 * mm, f"Página {doc.page} · Generado automáticamente")
        canv.restoreState()

    d.build(s, onFirstPage=pie, onLaterPages=pie)
    return ruta
