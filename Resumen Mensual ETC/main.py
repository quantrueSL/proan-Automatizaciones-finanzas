"""Punto de entrada único para Cloud Run Job: genera el reporte (HTML + PNG + PDF) y lo
envía por correo en la misma ejecución. A diferencia de los otros reportes de este repo,
no hay dos scripts separados (generar_reporte.py / enviar_reporte.py) -- enviar_reporte.py
ya llama a resumen_mensual_etc.generar_reporte_completo() internamente, así que main.py
solo necesita invocar el envío. Mismo patrón de main.py que los demás reportes, adaptado."""

import enviar_reporte


def main():
    enviar_reporte.main()


if __name__ == "__main__":
    main()
