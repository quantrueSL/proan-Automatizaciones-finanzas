"""Punto de entrada único para Cloud Run Job: genera el PDF y lo envía por correo en la
misma ejecución. Equivale a correr, en este orden:

    python generar_reporte.py
    python enviar_reporte.py

Mismo patrón que "Reportes diarios contables/main.py".
"""

import generar_reporte
import enviar_reporte


def main():
    generar_reporte.main()
    enviar_reporte.main()


if __name__ == "__main__":
    main()
