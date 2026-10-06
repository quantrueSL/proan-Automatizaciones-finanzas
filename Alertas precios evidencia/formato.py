"""Pequeñas funciones de formato de textos, fechas e importes (las usan alertas.py, pdf.py y el correo)."""
import numpy as np
import pandas as pd

import config


def nz(v, defecto=0):
    """NaN, None o vacío -> defecto."""
    return defecto if v is None or (isinstance(v, float) and np.isnan(v)) or v == "" else v


def limpia(t):
    """El CFDI y algunos nombres llegan con la Ñ dañada (carácter de sustitución U+FFFD)."""
    return str(t).replace("�", "Ñ") if nz(t, None) is not None else ""


_MAYUS = {"KG", "CN", "SA", "CV", "RL", "MZ", "TFF", "SAPI", "S/P", "C/P", "HEB", "OXXO", "II", "III"}
_MINUS = {"de", "del", "la", "las", "los", "y", "en", "el", "con", "c/", "s/", "a"}


def titulo(t, frase=False):
    """Pasa a minúsculas el texto en mayúsculas de SAP, respetando siglas, unidades y números."""
    t = limpia(t)
    if not t.isupper():
        return t
    out = []
    for i, w in enumerate(t.split()):
        lw = w.lower()
        if w.strip(".,") in _MAYUS or any(ch.isdigit() for ch in w):
            out.append(w)
        elif i and (frase or lw in _MINUS):
            out.append(lw)
        else:
            out.append(lw.capitalize())
    return " ".join(out)


def mxn(v, dec=0, signo=False):
    s = f"{abs(v):,.{dec}f}"
    if signo:
        return ("-$" if v < 0 else "+$") + s
    return ("-$" if v < 0 else "$") + s


def kg(v):
    return f"{v:,.0f} kg" if v >= 10 else f"{v:,.1f} kg"


def fecha_corta(d):
    d = pd.Timestamp(d)
    return f"{d.day:02d}-{d.month:02d}-{d.year}"


def fecha_larga(d):
    d = pd.Timestamp(d)
    return f"{d.day} de {config.MESES[d.month - 1]} de {d.year}"
