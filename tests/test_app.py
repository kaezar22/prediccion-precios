import sys
from pathlib import Path

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from lib import clima, datos, modelo  # noqa: E402


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
    for seccion in ["Producto", "Aciertos", "Clima", "Datos", "Resumen"]:
        at.sidebar.radio[0].set_value(seccion).run()
        assert not at.exception, seccion
        assert at.title[0].value == seccion


def _clima_de_prueba():
    import datetime as dt
    hoy = dt.date(2026, 10, 5)
    idx = pd.date_range("2017-01-01", "2026-10-04")
    historico = pd.DataFrame({"lluvia": 2.0, "tmax": 19.0, "tmin": 8.0}, index=idx)
    rec = pd.date_range("2026-07-05", "2026-10-20")
    reciente = pd.DataFrame({"lluvia": 2.0, "tmax": 19.0, "tmin": 8.0}, index=rec)
    reciente.loc["2026-10-05":, "lluvia"] = 4.0
    reciente.loc["2026-10-12", ["lluvia", "tmin"]] = [25.0, 1.0]
    return hoy, reciente, historico


def test_clima_resumen():
    hoy, reciente, historico = _clima_de_prueba()
    r = clima.resumen(reciente, historico, hoy)
    assert round(r["ultimos_30"]["total"]) == 60 and round(r["ultimos_30"]["normal"]) == 60
    assert r["ultimos_30"]["anios"] == 9
    assert r["dias_pronostico"] == 16 and round(r["proximos"]["normal"]) == 32
    assert round(r["proximos"]["total"]) == 15 * 4 + 25
    assert [f.isoformat() for f in r["dias_helada"]] == ["2026-10-12"]
    assert [f.isoformat() for f in r["dias_lluvia_fuerte"]] == ["2026-10-12"]


def test_clima_mensual_solo_meses_completos():
    hoy, reciente, historico = _clima_de_prueba()
    m = clima.mensual_vs_normal(reciente, historico, hoy)
    assert len(m) == 24 and m["mes"].max() == pd.Timestamp("2026-09-01")
    assert round(m["lluvia"].iloc[-1]) == 60 and round(m["normal"].iloc[-1]) == 60


def test_app_clima_con_datos(monkeypatch):
    hoy, reciente, historico = _clima_de_prueba()
    monkeypatch.setattr(clima, "hoy_bogota", lambda: hoy)
    monkeypatch.setattr(clima, "descargar_reciente", lambda: (reciente, {"latitud": 4.82, "longitud": -74.16, "altura": 2580.0}))
    monkeypatch.setattr(clima, "descargar_historico", lambda hasta=None: historico)
    import streamlit as st
    st.cache_data.clear()
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=120).run()
    at.sidebar.radio[0].set_value("Clima").run()
    assert not at.exception
    assert len(at.metric) == 3 and not at.error
    assert any("helada" in w.value for w in at.warning)


def test_app_clima_sin_conexion(monkeypatch):
    def falla(*a, **k):
        raise RuntimeError("sin red")
    monkeypatch.setattr(clima, "_pedir", falla)
    import streamlit as st
    st.cache_data.clear()
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=120).run()
    at.sidebar.radio[0].set_value("Clima").run()
    assert not at.exception
    assert len(at.error) == 1
