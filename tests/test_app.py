import sys
from pathlib import Path

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from lib import datos, modelo  # noqa: E402


def _serie():
    d = datos.cargar_mensual()
    return d["Cilantro"]


def test_datos_completos():
    d = datos.cargar_mensual()
    assert d.index.is_monotonic_increasing and d.index.is_unique
    assert d.index.min() == pd.Timestamp("2013-01-01")
    assert d["Cilantro"].notna().all()


def test_retroprueba_no_usa_el_futuro():
    s = _serie()
    rp = modelo.retroprueba(s)
    corte = pd.Timestamp("2022-06-01")
    alterada = s.copy()
    alterada[alterada.index > corte] *= 5
    rp2 = modelo.retroprueba(alterada)
    a = rp[(rp["origen"] == corte)].set_index("h")["modelo"]
    b = rp2[(rp2["origen"] == corte)].set_index("h")["modelo"]
    assert len(a) == 3
    assert np.allclose(a.to_numpy(), b.to_numpy())


def test_pronostico_coherente():
    s = _serie()
    pr = modelo.pronosticar(s, "Cilantro")
    t = pr.tabla
    assert list(t["h"]) == [1, 2, 3]
    assert (t["bajo"] < t["pronostico"]).all() and (t["pronostico"] < t["alto"]).all()
    assert ((t["prob_baja"] + t["prob_sube"]) <= 1.0001).all()


def test_mes_provisional_desde_semanal():
    m, s = datos.cargar_mensual(), datos.cargar_semanal()
    c, prov = datos.completar_con_semanal(m, s)
    assert len(c) == len(m) + len(prov)
    for mes in prov:
        assert mes > m.index.max()


def test_lector_servicio_web():
    xml = (
        "<r><return><artiNombre>Cilantro</artiNombre><fechaMesIni>2026-09-01T00:00:00-05:00</fechaMesIni>"
        "<fuenNombre>Bogot&#225;, D.C., Corabastos</fuenNombre><promedioKg>7000</promedioKg></return>"
        "<return><artiNombre>Cilantro</artiNombre><fechaMesIni>2026-09-01T00:00:00-05:00</fechaMesIni>"
        "<fuenNombre>Medell&#237;n, CMA</fuenNombre><promedioKg>1</promedioKg></return></r>"
    )
    largo = datos.leer_respuesta(xml, "fechaMesIni")
    assert len(largo) == 1 and largo["precio"].iloc[0] == 7000
    actual = datos.cargar_mensual()
    unido = datos.fusionar(actual, datos._ancho(largo, list(actual.columns)))
    assert len(unido) == len(actual) + 1 and unido.loc["2026-09-01", "Cilantro"] == 7000


def test_app_todas_las_secciones():
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=120).run()
    assert not at.exception
    for seccion in ["Producto", "Aciertos", "Datos", "Resumen"]:
        at.sidebar.radio[0].set_value(seccion).run()
        assert not at.exception, seccion
        assert at.title[0].value == seccion
