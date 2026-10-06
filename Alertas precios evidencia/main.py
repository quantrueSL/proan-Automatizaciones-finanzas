"""Punto de entrada del Cloud Run Job: genera el PDF de evidencia y lo envía, en la misma ejecución.

Equivale a correr, en este orden:
    python generar_evidencia.py
    python enviar_evidencia.py
Cada uno se sigue pudiendo ejecutar suelto en local.
"""
import enviar_evidencia
import generar_evidencia


def main():
    generar_evidencia.main()
    enviar_evidencia.main([])


if __name__ == "__main__":
    main()
