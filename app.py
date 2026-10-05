"""Nutrienti - Predicción de precios de hortalizas (versión beta).

Secciones: Resumen, Producto, Aciertos, Clima y Datos.
Fuente de precios: SIPSA (DANE), mercado Corabastos, precio promedio por kilo.
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from lib import clima, datos, modelo

AZUL = "#2a78d6"      # precio observado
NARANJA = "#eb6834"   # pronóstico
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
EJE_PESOS = "'$' + replace(format(datum.value, ',.0f'), /,/g, '.')"
EJE_MES = "['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'][month(datum.value)] + ' ' + year(datum.value)"

st.set_page_config(page_title="Predicción de precios - Nutrienti", page_icon="🥬", layout="wide")


# ---------- utilidades de formato ----------
def pesos(x: float) -> str:
    return "sin dato" if pd.isna(x) else "$" + f"{x:,.0f}".replace(",", ".")


def pct(x: float, signo: bool = True) -> str:
    if pd.isna(x):
        return "sin dato"
    return (f"{x * 100:+.0f}" if signo else f"{x * 100:.0f}") + " %"


def mes_txt(f: pd.Timestamp) -> str:
    return f"{MESES[f.month - 1]} {f.year}"


# ---------- datos y cálculos (en caché) ----------
@st.cache_data(show_spinner=False)
def leer_datos(sello: float):
    mensual = datos.cargar_mensual()
    semanal = datos.cargar_semanal()
    completo, provisionales = datos.completar_con_semanal(mensual, semanal)
    return mensual, semanal, completo, provisionales


@st.cache_data(show_spinner="Calculando pronósticos y aciertos...")
def calcular(completo: pd.DataFrame):
    salida = {}
    for p in completo.columns:
        rp = modelo.retroprueba(completo[p])
        if rp.empty:
            continue
        pr = modelo.pronosticar(completo[p], p, rp)
        if pr is None:
            continue
        salida[p] = {"rp": rp, "metricas": modelo.metricas(rp), "pronostico": pr}
    return salida


def sello_archivos() -> float:
    return max(datos.ARCHIVO_MENSUAL.stat().st_mtime, datos.ARCHIVO_SEMANAL.stat().st_mtime)


mensual, semanal, completo, provisionales = leer_datos(sello_archivos())
resultados = calcular(completo)
productos = list(resultados)

st.sidebar.title("Predicción de precios")
st.sidebar.caption("Corabastos, precio promedio por kilo (SIPSA - DANE). Versión beta.")
seccion = st.sidebar.radio("Sección", ["Resumen", "Producto", "Aciertos", "Clima", "Datos"], key="seccion")
st.sidebar.divider()
st.sidebar.caption(
    f"Mensual publicado hasta {mes_txt(mensual.index.max())}. "
    f"Semanal hasta la semana del {semanal.index.max():%d/%m/%Y}."
)


def nota_provisional():
    if provisionales:
        lista = ", ".join(mes_txt(m) for m in provisionales)
        st.info(
            f"El DANE aún no publica el dato mensual de {lista}. "
            "Para ese mes la app usa el promedio de los precios semanales, y se reemplaza cuando salga el oficial."
        )


def supera(m: pd.DataFrame, h: int = 1) -> bool:
    fila = m.loc[m["h"] == h]
    return bool(len(fila)) and float(fila["mejora"].iloc[0]) > 0.02


# ---------- sección: Resumen ----------
def ver_resumen():
    st.title("Resumen")
    st.write("Qué se espera para el próximo mes en cada producto, frente al último precio conocido.")
    nota_provisional()
    filas = []
    for p in productos:
        pr = resultados[p]["pronostico"]
        t = pr.tabla.iloc[0]
        filas.append({
            "Producto": p,
            "Señal": modelo.senal(t["prob_baja"], t["prob_sube"]),
            "Último precio": f"{pesos(pr.ultimo)} ({mes_txt(pr.origen)})",
            "Frente a su último año": pct(pr.ultimo / pr.nivel_12m - 1),
            "Pronóstico": f"{pesos(t['pronostico'])} ({mes_txt(t['mes'])})",
            "Cambio esperado": pct(t["cambio"]),
            "Rango probable": f"{pesos(t['bajo'])} a {pesos(t['alto'])}",
            "Prob. de bajar más de 10 %": pct(t["prob_baja"], signo=False),
            "Prob. de subir más de 10 %": pct(t["prob_sube"], signo=False),
            "Fiabilidad": "Supera la regla simple" if supera(resultados[p]["metricas"]) else "No supera la regla simple",
        })
    tabla = pd.DataFrame(filas)
    bajan = tabla.loc[tabla["Señal"] == "Baja probable", "Producto"].tolist()
    suben = tabla.loc[tabla["Señal"] == "Sube probable", "Producto"].tolist()
    c1, c2, c3 = st.columns(3)
    c1.metric("Con baja probable", len(bajan), help="Probabilidad de 60 % o más de bajar más de 10 %.")
    c2.metric("Con alza probable", len(suben), help="Probabilidad de 60 % o más de subir más de 10 %.")
    c3.metric("Sin señal clara", len(tabla) - len(bajan) - len(suben))
    if bajan:
        st.success("Baja probable: " + ", ".join(bajan) + ". Son los candidatos a oferta del próximo mes.")
    if suben:
        st.warning("Alza probable: " + ", ".join(suben) + ".")
    st.dataframe(tabla, hide_index=True, width="stretch")
    st.caption(
        "El rango probable cubre 8 de cada 10 casos según los errores que el modelo tuvo en el pasado. "
        "La señal solo aparece cuando la probabilidad llega a 60 %. "
        "La fiabilidad compara el modelo con la regla simple de suponer que el precio queda igual al último mes."
    )


# ---------- sección: Producto ----------
def grafico_historia(p: str, anios: int | None):
    pr = resultados[p]["pronostico"]
    s = completo[p].dropna()
    if anios:
        s = s[s.index >= s.index.max() - pd.DateOffset(years=anios)]
    obs = pd.DataFrame({"mes": s.index, "precio": s.to_numpy(), "serie": "Precio observado"})
    obs["texto"] = obs["precio"].map(pesos)
    obs["mes_txt"] = obs["mes"].map(mes_txt)
    obs["detalle"] = ""
    t = pr.tabla
    pro = pd.DataFrame({"mes": t["mes"], "precio": t["pronostico"], "serie": "Pronóstico", "bajo": t["bajo"], "alto": t["alto"]})
    ancla = pd.DataFrame({"mes": [pr.origen], "precio": [pr.ultimo], "serie": ["Pronóstico"], "bajo": [pr.ultimo], "alto": [pr.ultimo]})
    pro = pd.concat([ancla, pro], ignore_index=True)
    pro["texto"] = pro["precio"].map(pesos)
    pro["mes_txt"] = pro["mes"].map(mes_txt)
    pro["detalle"] = [""] + [f"{pesos(a)} a {pesos(b)}" for a, b in zip(t["bajo"], t["alto"])]
    color = alt.Color(
        "serie:N",
        scale=alt.Scale(domain=["Precio observado", "Pronóstico"], range=[AZUL, NARANJA]),
        legend=alt.Legend(title=None, orient="top"),
    )
    eje_y = alt.Y("precio:Q", title="Pesos por kilo", axis=alt.Axis(labelExpr=EJE_PESOS), scale=alt.Scale(zero=False))
    eje_x = alt.X("mes:T", title=None, axis=alt.Axis(labelExpr=EJE_MES, labelAngle=0, tickCount=8))
    tip = [alt.Tooltip("mes_txt:N", title="Mes"), alt.Tooltip("serie:N", title="Serie"),
           alt.Tooltip("texto:N", title="Precio"), alt.Tooltip("detalle:N", title="Rango probable")]
    banda = alt.Chart(pro).mark_area(opacity=0.18, color=NARANJA).encode(x=eje_x, y=alt.Y("bajo:Q", title="Pesos por kilo"), y2="alto:Q")
    linea = alt.Chart(obs).mark_line(strokeWidth=2).encode(x=eje_x, y=eje_y, color=color)
    puntos = alt.Chart(obs).mark_point(size=60, opacity=0).encode(x=eje_x, y=eje_y, tooltip=tip)
    lin_p = alt.Chart(pro).mark_line(strokeWidth=2, strokeDash=[5, 4]).encode(x=eje_x, y=eje_y, color=color)
    pts_p = alt.Chart(pro.iloc[1:]).mark_point(size=70, filled=True).encode(x=eje_x, y=eje_y, color=color, tooltip=tip)
    return (banda + linea + puntos + lin_p + pts_p).properties(height=360)


def grafico_estacionalidad(p: str):
    e = modelo.estacionalidad(completo[p])
    e["nombre"] = e["mes"].map(lambda m: MESES[m - 1])
    e["cambio"] = e["indice"] - 1
    e["texto"] = e["cambio"].map(pct)
    barras = alt.Chart(e).mark_bar(color=AZUL, cornerRadiusEnd=4, size=26).encode(
        x=alt.X("nombre:N", sort=MESES, title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("cambio:Q", title="Frente al promedio del año", axis=alt.Axis(format="+.0%")),
        tooltip=[alt.Tooltip("nombre:N", title="Mes"), alt.Tooltip("texto:N", title="Frente al promedio"),
                 alt.Tooltip("anios:Q", title="Años con dato")],
    )
    cero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(strokeWidth=1, opacity=0.5).encode(y="y:Q")
    return (barras + cero).properties(height=260)


def grafico_semanal(p: str):
    s = semanal[p].dropna()
    d = pd.DataFrame({"semana": s.index, "precio": s.to_numpy()})
    d["texto"] = d["precio"].map(pesos)
    base = alt.Chart(d).encode(
        x=alt.X("semana:T", title=None, axis=alt.Axis(labelExpr=EJE_MES, labelAngle=0, tickCount=6)),
        y=alt.Y("precio:Q", title="Pesos por kilo", axis=alt.Axis(labelExpr=EJE_PESOS), scale=alt.Scale(zero=False)),
        tooltip=[alt.Tooltip("semana:T", title="Semana del", format="%d/%m/%Y"), alt.Tooltip("texto:N", title="Precio")],
    )
    return (base.mark_line(strokeWidth=2, color=AZUL) + base.mark_point(size=60, opacity=0)).properties(height=260)


def ver_producto():
    st.title("Producto")
    p = st.selectbox("Producto", productos, key="producto")
    pr = resultados[p]["pronostico"]
    t = pr.tabla
    nota_provisional()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"Último precio ({mes_txt(pr.origen)})", pesos(pr.ultimo))
    c2.metric("Frente a su último año", pct(pr.ultimo / pr.nivel_12m - 1), help=f"Promedio de los últimos 12 meses: {pesos(pr.nivel_12m)}.")
    c3.metric(f"Pronóstico {mes_txt(t['mes'].iloc[0])}", pesos(t["pronostico"].iloc[0]), pct(t["cambio"].iloc[0]), delta_color="off")
    c4.metric("Señal", modelo.senal(t["prob_baja"].iloc[0], t["prob_sube"].iloc[0]))
    if not supera(resultados[p]["metricas"]):
        st.warning("En este producto el modelo no ha superado a la regla simple de \"igual al último mes\". Tome el pronóstico como orientación.")

    opciones = {"3 años": 3, "5 años": 5, "Todo (desde 2013)": None}
    periodo = st.radio("Periodo", list(opciones), horizontal=True, key="periodo")
    st.altair_chart(grafico_historia(p, opciones[periodo]), width="stretch")
    st.caption("La franja naranja es el rango donde cayó el precio 8 de cada 10 veces en pronósticos pasados.")

    st.subheader("Pronóstico a tres meses")
    st.dataframe(pd.DataFrame({
        "Mes": t["mes"].map(mes_txt),
        "Pronóstico": t["pronostico"].map(pesos),
        "Rango probable": [f"{pesos(a)} a {pesos(b)}" for a, b in zip(t["bajo"], t["alto"])],
        "Cambio frente al último precio": t["cambio"].map(pct),
        "Prob. de bajar más de 10 %": t["prob_baja"].map(lambda v: pct(v, signo=False)),
        "Prob. de subir más de 10 %": t["prob_sube"].map(lambda v: pct(v, signo=False)),
    }), hide_index=True, width="stretch")

    a, b = st.columns(2)
    with a:
        st.subheader("Época del año")
        st.altair_chart(grafico_estacionalidad(p), width="stretch")
        st.caption("Cuánto más caro o barato suele estar cada mes frente al promedio del año, con datos desde 2013.")
    with b:
        st.subheader("Últimas semanas")
        if p in semanal.columns and semanal[p].notna().sum() > 1:
            st.altair_chart(grafico_semanal(p), width="stretch")
            s = semanal[p].dropna()
            st.caption(f"Semana del {s.index[-1]:%d/%m/%Y}: {pesos(s.iloc[-1])}, {pct(s.iloc[-1] / s.iloc[-2] - 1)} frente a la semana anterior.")
        else:
            st.write("No hay serie semanal para este producto.")


# ---------- sección: Aciertos ----------
def grafico_aciertos(p: str, h: int):
    rp = resultados[p]["rp"]
    g = rp[rp["h"] == h]
    d = pd.concat([
        pd.DataFrame({"mes": g["mes"], "precio": g["real"], "serie": "Precio real"}),
        pd.DataFrame({"mes": g["mes"], "precio": g["modelo"], "serie": "Pronóstico del modelo"}),
    ])
    d["texto"] = d["precio"].map(pesos)
    d["mes_txt"] = d["mes"].map(mes_txt)
    color = alt.Color("serie:N", scale=alt.Scale(domain=["Precio real", "Pronóstico del modelo"], range=[AZUL, NARANJA]),
                      legend=alt.Legend(title=None, orient="top"))
    base = alt.Chart(d).encode(
        x=alt.X("mes:T", title=None, axis=alt.Axis(format="%Y", labelAngle=0, tickCount="year")),
        y=alt.Y("precio:Q", title="Pesos por kilo", axis=alt.Axis(labelExpr=EJE_PESOS), scale=alt.Scale(zero=False)),
    )
    lineas = base.mark_line(strokeWidth=2).encode(color=color)
    puntos = base.mark_point(size=60, opacity=0).encode(
        tooltip=[alt.Tooltip("mes_txt:N", title="Mes"), alt.Tooltip("serie:N", title="Serie"), alt.Tooltip("texto:N", title="Precio")])
    return (lineas + puntos).properties(height=340)


def ver_aciertos():
    st.title("Aciertos")
    st.write(
        "Para saber si el modelo sirve, se simula el pasado: en cada mes desde 2018 se pronostica usando solo "
        "lo que se conocía hasta ese momento, y se compara con lo que ocurrió."
    )
    h = st.radio("Anticipación", [1, 2, 3], format_func=lambda x: f"{x} mes" if x == 1 else f"{x} meses", horizontal=True, key="horizonte")
    filas = []
    for p in productos:
        m = resultados[p]["metricas"]
        f = m.loc[m["h"] == h]
        if f.empty:
            continue
        f = f.iloc[0]
        filas.append({
            "Producto": p,
            "Veredicto": "Supera la regla simple" if f["mejora"] > 0.02 else "No la supera",
            "Meses evaluados": int(f["meses"]),
            "Error típico del modelo": pct(f["error_modelo"], signo=False),
            "Error típico de la regla simple": pct(f["error_simple"], signo=False),
            "Mejora frente a la regla simple": pct(f["mejora"]),
            "Acierto de dirección": pct(f["acierto_direccion"], signo=False),
        })
    st.dataframe(pd.DataFrame(filas), hide_index=True, width="stretch")
    st.caption(
        "Regla simple: suponer que el precio queda igual al último mes conocido. "
        "Error típico: la mitad de los meses el error fue menor que ese porcentaje. "
        "Acierto de dirección: de los meses en que el precio se movió más de 10 %, en cuántos el modelo acertó si subía o bajaba."
    )
    p = st.selectbox("Ver un producto", productos, key="producto_aciertos")
    st.altair_chart(grafico_aciertos(p, h), width="stretch")


# ---------- sección: Clima ----------
@st.cache_data(ttl=6 * 3600, show_spinner="Consultando el clima en Open-Meteo...")
def leer_clima(dia: str):
    reciente, punto = clima.descargar_reciente()
    historico = clima.descargar_historico()
    return reciente, punto, historico


def fecha_txt(f) -> str:
    return f"{f.day} de {MESES[f.month - 1]}"


def mm(x: float) -> str:
    return "sin dato" if pd.isna(x) else f"{x:.0f} mm"


def grafico_lluvia_diaria(reciente: pd.DataFrame, hoy):
    desde = pd.Timestamp(hoy) - pd.Timedelta(days=30)
    d = reciente.loc[desde:, ["lluvia"]].dropna().rename_axis("fecha").reset_index()
    d["serie"] = d["fecha"].map(lambda f: "Pronóstico" if f.date() >= hoy else "Observado")
    d["dia"] = d["fecha"].map(fecha_txt)
    d["texto"] = d["lluvia"].map(lambda v: f"{v:.1f} mm".replace(".", ","))
    return alt.Chart(d).mark_bar(cornerRadiusEnd=3).encode(
        x=alt.X("fecha:T", title=None, axis=alt.Axis(format="%d/%m", labelAngle=0, tickCount=10)),
        y=alt.Y("lluvia:Q", title="Lluvia (mm por día)"),
        color=alt.Color("serie:N", scale=alt.Scale(domain=["Observado", "Pronóstico"], range=[AZUL, NARANJA]),
                        legend=alt.Legend(title=None, orient="top")),
        tooltip=[alt.Tooltip("dia:N", title="Día"), alt.Tooltip("serie:N", title="Tipo"), alt.Tooltip("texto:N", title="Lluvia")],
    ).properties(height=300)


def grafico_lluvia_mensual(tabla: pd.DataFrame):
    d = tabla.copy()
    d["mes_txt"] = d["mes"].map(mes_txt)
    d["lluvia_txt"] = d["lluvia"].map(mm)
    d["normal_txt"] = d["normal"].map(mm)
    d["serie"] = "Lluvia del mes"
    d["serie_normal"] = "Normal para ese mes"
    eje_x = alt.X("yearmonth(mes):O", title=None, axis=alt.Axis(labelExpr=EJE_MES, labelAngle=0, labelOverlap=True))
    tip = [alt.Tooltip("mes_txt:N", title="Mes"), alt.Tooltip("lluvia_txt:N", title="Lluvia"), alt.Tooltip("normal_txt:N", title="Normal")]
    escala = alt.Scale(domain=["Lluvia del mes", "Normal para ese mes"], range=[AZUL, "#52514e"])
    barras = alt.Chart(d).mark_bar(cornerRadiusEnd=3).encode(
        x=eje_x, y=alt.Y("lluvia:Q", title="Lluvia (mm por mes)"),
        color=alt.Color("serie:N", scale=escala, legend=alt.Legend(title=None, orient="top")), tooltip=tip)
    marcas = alt.Chart(d).mark_tick(thickness=3, size=22).encode(
        x=eje_x, y="normal:Q", color=alt.Color("serie_normal:N", scale=escala), tooltip=tip)
    return (barras + marcas).properties(height=300)


def frase_comparacion(c: dict) -> str:
    if pd.isna(c["normal"]):
        return "No hay años anteriores para comparar."
    return f"Lo normal para esas fechas es {mm(c['normal'])} (promedio de {c['anios']} años, desde 2017)."


def ver_clima():
    st.title("Clima")
    st.write(f"Lluvia y temperatura en {clima.LUGAR}, donde están las fincas. Fuente: Open-Meteo.")
    hoy = clima.hoy_bogota()
    try:
        reciente, punto, historico = leer_clima(hoy.isoformat())
    except Exception as e:  # sin conexión o el servicio no responde
        st.error(f"No se pudo consultar el clima en este momento: {e}")
        return
    r = clima.resumen(reciente, historico, hoy)
    u, p = r["ultimos_30"], r["proximos"]

    c1, c2, c3 = st.columns(3)
    c1.metric("Lluvia de los últimos 30 días", mm(u["total"]), pct(u["diferencia"]) + " frente a lo normal", delta_color="off")
    c2.metric(f"Lluvia pronosticada, próximos {r['dias_pronostico']} días", mm(p["total"]), pct(p["diferencia"]) + " frente a lo normal", delta_color="off")
    etiqueta_min = "Mínima más baja pronosticada" + (f" ({fecha_txt(r['dia_tmin'])})" if r["dia_tmin"] else "")
    c3.metric(etiqueta_min, "sin dato" if pd.isna(r["tmin_prevista"]) else f"{r['tmin_prevista']:.1f} °C".replace(".", ","))
    st.caption(f"Últimos 30 días: {frase_comparacion(u)} Próximos {r['dias_pronostico']} días: {frase_comparacion(p)}")

    if r["dias_helada"]:
        st.warning("Riesgo de helada: se pronostica una mínima de 2 °C o menos el " + ", ".join(fecha_txt(f) for f in r["dias_helada"]) + ".")
    if r["dias_lluvia_fuerte"]:
        st.warning("Lluvia fuerte (20 mm o más en un día) pronosticada el " + ", ".join(fecha_txt(f) for f in r["dias_lluvia_fuerte"]) + ".")
    if not r["dias_helada"] and not r["dias_lluvia_fuerte"]:
        st.info("Sin alertas de helada ni de lluvia fuerte en el pronóstico.")

    st.subheader("Lluvia diaria: últimos 30 días y pronóstico")
    st.altair_chart(grafico_lluvia_diaria(reciente, hoy), width="stretch")
    st.caption("El pronóstico pierde precisión después de la primera semana; tome los días lejanos y su comparación con lo normal como tendencia.")

    st.subheader("Lluvia por mes frente a lo normal")
    st.altair_chart(grafico_lluvia_mensual(clima.mensual_vs_normal(reciente, historico, hoy)), width="stretch")
    st.caption("La marca gris es el promedio de ese mismo mes en los demás años desde 2017.")

    st.subheader("Qué significa para los precios")
    st.write(
        "Por ahora, nada firme. Se comparó la lluvia de los tres meses anteriores con el precio en Corabastos usando "
        "tres fuentes de lluvia distintas, y no coinciden: con una fuente la acelga y el perejil subían después de meses "
        "lluviosos, pero con las otras dos esa relación casi desaparece. Por eso el pronóstico de precios no usa el clima. "
        "Esta sección sirve para vigilar las fincas: heladas, exceso de lluvia y sequía."
    )
    if punto.get("altura") is not None:
        st.caption(
            f"Punto consultado: latitud {punto['latitud']:.2f}, longitud {punto['longitud']:.2f}, altura {punto['altura']:.0f} m. "
            "Los datos son una estimación para una celda de unos 9 km, no la medición de una estación."
        )



# ---------- sección: Datos ----------
def ver_datos():
    st.title("Datos")
    st.write(
        "Precios mayoristas de SIPSA (DANE) para el mercado Bogotá, D.C., Corabastos: precio promedio por kilo."
    )
    st.dataframe(pd.DataFrame([
        {"Serie": "Mensual", "Desde": mes_txt(mensual.index.min()), "Hasta": mes_txt(mensual.index.max()),
         "Registros": len(mensual), "Origen": "Series históricas del DANE y servicio web de SIPSA"},
        {"Serie": "Semanal", "Desde": f"{semanal.index.min():%d/%m/%Y}", "Hasta": f"{semanal.index.max():%d/%m/%Y}",
         "Registros": len(semanal), "Origen": "Servicio web de SIPSA (último año)"},
    ]), hide_index=True, width="stretch")

    st.subheader("Actualizar desde el DANE")
    st.write("Consulta el servicio web de SIPSA y agrega las fechas nuevas. Cada descarga pesa unos 60 MB y puede tardar varios minutos.")
    a, b = st.columns(2)
    for col, tipo in ((a, "semanal"), (b, "mensual")):
        if col.button(f"Actualizar serie {tipo}", key=f"actualizar_{tipo}"):
            try:
                with st.spinner("Descargando del DANE..."):
                    _, agregadas = datos.actualizar(tipo)
                st.cache_data.clear()
                st.success(f"Se agregaron {agregadas} fechas nuevas a la serie {tipo}." if agregadas else f"La serie {tipo} ya estaba al día.")
            except Exception as e:  # la app no debe caerse si el DANE no responde
                st.error(f"No se pudo actualizar: {e}")
    st.caption("En Streamlit Cloud los archivos actualizados se pierden cuando la app se reinicia; para conservarlos hay que subirlos al repositorio.")

    st.subheader("Descargar")
    c, d = st.columns(2)
    c.download_button("Serie mensual (CSV)", datos.ARCHIVO_MENSUAL.read_bytes(), "sipsa_corabastos_mensual.csv", "text/csv")
    d.download_button("Serie semanal (CSV)", datos.ARCHIVO_SEMANAL.read_bytes(), "sipsa_corabastos_semanal.csv", "text/csv")

    st.subheader("Cómo funciona el pronóstico")
    st.write(
        "El modelo combina tres cosas: el nivel del producto en los últimos 12 meses, la época del año y qué tan lejos "
        "está hoy el precio de ese nivel. No usa clima. Los rangos y probabilidades salen de los errores "
        "que el modelo cometió al simular el pasado."
    )


{"Resumen": ver_resumen, "Producto": ver_producto, "Aciertos": ver_aciertos, "Clima": ver_clima, "Datos": ver_datos}[seccion]()
