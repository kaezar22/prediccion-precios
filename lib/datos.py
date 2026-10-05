"""Carga y actualización de los precios de SIPSA (DANE) para Corabastos."""
from __future__ import annotations

import html
import re
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
ARCHIVO_MENSUAL = RAIZ / "data" / "sipsa_corabastos_mensual.csv"
ARCHIVO_SEMANAL = RAIZ / "data" / "sipsa_corabastos_semanal.csv"

MERCADO = "Bogotá, D.C., Corabastos"
URL_SERVICIO = "https://appweb.dane.gov.co/sipsaWS/SrvSipsaUpraBeanService"
SOBRE = (
    "<soap:Envelope xmlns:soap='http://www.w3.org/2003/05/soap-envelope' "
    "xmlns:ser='http://servicios.sipsa.co.gov.dane/'><soap:Body><ser:{metodo}/></soap:Body></soap:Envelope>"
)
MIN_SEMANAS_MES = 3   # semanas necesarias para estimar un mes aún no publicado


def cargar_mensual(ruta: Path = ARCHIVO_MENSUAL) -> pd.DataFrame:
    return pd.read_csv(ruta, parse_dates=["Mes"]).set_index("Mes").sort_index()


def cargar_semanal(ruta: Path = ARCHIVO_SEMANAL) -> pd.DataFrame:
    return pd.read_csv(ruta, parse_dates=["Semana"]).set_index("Semana").sort_index()


def completar_con_semanal(mensual: pd.DataFrame, semanal: pd.DataFrame) -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    """Añade los meses que el DANE aún no publica, estimados con el promedio semanal.

    Una semana se asigna al mes en que empieza. Devuelve la tabla completada y la
    lista de meses estimados (provisionales).
    """
    ultimo = mensual.index.max()
    por_mes = semanal.copy()
    por_mes.index = por_mes.index.to_period("M").to_timestamp()
    conteo = por_mes.groupby(level=0).count()
    promedio = por_mes.groupby(level=0).mean()
    nuevos = [m for m in promedio.index if m > ultimo]
    # Solo meses consecutivos al último publicado.
    provisionales: list[pd.Timestamp] = []
    esperado = ultimo + pd.DateOffset(months=1)
    for m in sorted(nuevos):
        if m != esperado:
            break
        provisionales.append(m)
        esperado = m + pd.DateOffset(months=1)
    if not provisionales:
        return mensual, []
    comunes = [c for c in mensual.columns if c in semanal.columns]
    extra = promedio.loc[provisionales, comunes].where(conteo.loc[provisionales, comunes] >= MIN_SEMANAS_MES)
    extra = extra.round(0)
    extra = extra.dropna(how="all")
    if extra.empty:
        return mensual, []
    out = pd.concat([mensual, extra.reindex(columns=mensual.columns)])
    out.index.name = mensual.index.name
    return out, list(extra.index)


def leer_respuesta(xml: str, campo_fecha: str) -> pd.DataFrame:
    """Convierte la respuesta del servicio web en una tabla larga (solo Corabastos)."""
    filas = []
    for bloque in re.findall(r"<return>(.*?)</return>", xml, flags=re.S):
        d = dict(re.findall(r"<(\w+)>(.*?)</\1>", bloque, flags=re.S))
        if html.unescape(d.get("fuenNombre", "")) != MERCADO:
            continue
        try:
            filas.append({
                "fecha": pd.Timestamp(d[campo_fecha][:10]),
                "producto": html.unescape(d["artiNombre"]),
                "precio": float(d["promedioKg"]),
            })
        except (KeyError, ValueError):
            continue
    return pd.DataFrame(filas, columns=["fecha", "producto", "precio"])


def _ancho(largo: pd.DataFrame, productos: list[str]) -> pd.DataFrame:
    largo = largo[largo["producto"].isin(productos)]
    # Si el DANE repite un registro, se toma el primero publicado.
    ancho = largo.groupby(["fecha", "producto"])["precio"].first().unstack("producto")
    return ancho.reindex(columns=productos).round(0)


def _descargar(metodo: str, tiempo: int = 600) -> str:
    import requests

    r = requests.post(
        URL_SERVICIO,
        data=SOBRE.format(metodo=metodo).encode("utf-8"),
        headers={"Content-Type": "application/soap+xml; charset=utf-8"},
        timeout=tiempo,
    )
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text


def fusionar(actual: pd.DataFrame, nuevo: pd.DataFrame) -> pd.DataFrame:
    """Une lo descargado con lo guardado: lo nuevo solo rellena fechas que no existían."""
    faltantes = nuevo.loc[~nuevo.index.isin(actual.index)]
    out = pd.concat([actual, faltantes]).sort_index()
    out.index.name = actual.index.name
    return out


def actualizar(tipo: str) -> tuple[pd.DataFrame, int]:
    """Consulta el servicio web del DANE y agrega las fechas nuevas al archivo local.

    tipo: "mensual" o "semanal". Devuelve la tabla actualizada y cuántas fechas se añadieron.
    """
    if tipo == "mensual":
        actual, ruta, metodo, campo = cargar_mensual(), ARCHIVO_MENSUAL, "promediosSipsaMesMadr", "fechaMesIni"
    else:
        actual, ruta, metodo, campo = cargar_semanal(), ARCHIVO_SEMANAL, "promediosSipsaSemanaMadr", "fechaIni"
    nuevo = _ancho(leer_respuesta(_descargar(metodo), campo), list(actual.columns))
    unido = fusionar(actual, nuevo)
    agregadas = len(unido) - len(actual)
    if agregadas:
        unido.to_csv(ruta, date_format="%Y-%m-%d", float_format="%.0f")
    return unido, agregadas
