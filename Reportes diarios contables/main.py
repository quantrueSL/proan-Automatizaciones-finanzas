"""Punto de entrada único para Cloud Run Job: genera el PDF y lo envía por correo en la
misma ejecución (un Job corre un solo proceso, no dos comandos encadenados a mano como en
uso local). Equivale a correr, en este orden:

    python generar_reporte.py
    python enviar_reporte.py

Reutiliza esos dos scripts tal cual -- ninguno cambia su lógica por existir este archivo,
cada uno se sigue pudiendo ejecutar suelto en local igual que siempre.
"""

import generar_reporte
import enviar_reporte


def main():
    generar_reporte.main()
    enviar_reporte.main()


if __name__ == "__main__":
    main()
