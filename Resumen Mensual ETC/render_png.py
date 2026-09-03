"""Convierte el HTML del Resumen Mensual ETC a PNG (para incrustar en el correo) y a PDF
(para adjuntar) -- el diseño del mockup (flexbox, CSS custom properties, conic-gradient del
donut) no es email-safe (Outlook/Word engine no soporta nada de eso), así que en vez de
mandar el HTML directo se manda una IMAGEN del render completo, igual de fiel al mockup en
cualquier cliente de correo. Reemplaza al "Edge headless" mencionado en el briefing original
-- se usa Chrome headless porque ya está instalado y probado en este equipo; el mecanismo es
el mismo (un navegador sin interfaz que renderiza el HTML).

El PDF NO es una captura del PNG (se vería pixelado/borroso al hacer zoom, exactamente la
queja que motivó agregar esto 2026-09-03) -- es el propio Chrome "imprimiendo" el HTML a PDF
con un @page del tamaño exacto del contenido (una sola página, sin cortes de sección), así
que el texto queda vectorial/seleccionable y nítido a cualquier zoom.
"""

import os
import shutil
import subprocess
import tempfile

from PIL import Image, ImageChops

# Candidatos de ruta al binario de Chrome/Chromium -- Windows (desarrollo local) primero,
# después los nombres típicos en Linux (Cloud Run, si se instala chromium en el Dockerfile).
_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "google-chrome-stable",
    "google-chrome",
    "chromium",
    "chromium-browser",
]


def _localizar_chrome():
    for candidato in _CHROME_CANDIDATES:
        if os.path.sep in candidato or ":" in candidato:  # ruta absoluta tipo Windows
            if os.path.exists(candidato):
                return candidato
        elif shutil.which(candidato):
            return shutil.which(candidato)
    raise RuntimeError(
        "No se encontró Chrome/Chromium para renderizar el HTML a PNG/PDF. En Windows "
        "instala Google Chrome; en el contenedor de Cloud Run hay que agregar 'chromium' al "
        "Dockerfile (apt-get install -y chromium) -- ver README."
    )


def _run_chrome(args):
    """Cada llamada usa su propio --user-data-dir temporal: sin esto, Chrome headless puede
    'engancharse' a una ventana normal ya abierta en la misma máquina (se vio literalmente
    al probar esto -- "Se está abriendo en una sesión de navegador existente") e ignorar
    silenciosamente flags como --force-device-scale-factor. Con perfil propio, headless
    siempre arranca una instancia aislada."""
    chrome = _localizar_chrome()
    with tempfile.TemporaryDirectory(prefix="chrome_headless_") as perfil:
        subprocess.run(
            [chrome, "--headless", "--disable-gpu", f"--user-data-dir={perfil}", *args],
            check=True, capture_output=True, timeout=60,
        )


def renderizar_html_a_png(html_path, png_path, ancho=1040, alto_max=4500, color_fondo="EFECE4",
                          escala=2):
    """Renderiza html_path a png_path, recortado a su contenido real, a `escala`x de
    resolución (2x por defecto -- "retina": el <img width="1040"> del correo se ve nítido
    incluso haciendo zoom, en vez de pixelarse). Devuelve (ancho_css, alto_css) del
    contenido recortado -- en px CSS, sin multiplicar por escala -- para que
    renderizar_html_a_pdf() pueda armar un @page del tamaño exacto."""
    uri = "file:///" + os.path.abspath(html_path).replace("\\", "/")
    _run_chrome([
        f"--force-device-scale-factor={escala}",
        f"--screenshot={os.path.abspath(png_path)}",
        f"--window-size={ancho},{alto_max}",
        f"--default-background-color=FF{color_fondo}",
        uri,
    ])
    return _recortar_a_contenido(png_path, color_fondo, escala)


def _recortar_a_contenido(png_path, color_fondo_hex, escala, margen_css=16):
    im = Image.open(png_path).convert("RGB")
    r, g, b = (int(color_fondo_hex[i:i + 2], 16) for i in (0, 2, 4))
    fondo = Image.new("RGB", im.size, (r, g, b))
    bbox = ImageChops.difference(im, fondo).getbbox()
    if bbox is None:
        return im.width / escala, im.height / escala  # página en blanco -- no debería pasar
    margen = margen_css * escala
    x0, y0, x1, y1 = bbox
    caja = (
        max(0, x0 - margen), max(0, y0 - margen),
        min(im.width, x1 + margen), min(im.height, y1 + margen),
    )
    im.crop(caja).save(png_path)
    return (caja[2] - caja[0]) / escala, (caja[3] - caja[1]) / escala


def renderizar_html_a_pdf(html_path, pdf_path, ancho_css, alto_css, color_fondo="EFECE4"):
    """PDF de una sola página del tamaño exacto del contenido (ancho_css x alto_css, en px
    CSS -- la salida de renderizar_html_a_png) -- sin esto, Chrome usa Carta/A4 por defecto
    y corta el reporte a mitad de tarjeta cada ~1100px. Inyecta un @page antes de imprimir,
    en una copia temporal del HTML (no modifica html_path)."""
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    estilo_impresion = (
        "<style>@media print {"
        f" @page {{ size: {ancho_css:.0f}px {alto_css:.0f}px; margin: 0; }}"
        " body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }"
        " }</style>"
    )
    html_impresion = html.replace("</head>", estilo_impresion + "</head>")

    fd, tmp_path = tempfile.mkstemp(suffix=".html")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(html_impresion)
        uri = "file:///" + os.path.abspath(tmp_path).replace("\\", "/")
        _run_chrome([
            f"--print-to-pdf={os.path.abspath(pdf_path)}",
            "--no-pdf-header-footer",
            uri,
        ])
    finally:
        os.remove(tmp_path)
