from datetime import date
from decimal import Decimal as D

import pytest
from django.urls import reverse

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.calculo import cargar
from apps.companias.models import ClasificacionCFSE, TasaCFSE, TasasCompania
from apps.parametros.models import ConceptoDeduccion, ConceptoIngreso, ParametrosAnuales, SalarioMinimo

from .conftest import crear_empleado


@pytest.mark.django_db
def test_valores_iniciales_cargados_por_verificar():
    p = ParametrosAnuales.objects.get(anio=2026)
    assert p.ss_tope == D("184500") and ParametrosAnuales.objects.get(anio=2025).ss_tope == D("176100")
    assert p.tramos.count() == 5 and p.reglas_horas_extra.count() == 2
    assert p.estado == "por_verificar"
    assert SalarioMinimo.objects.count() == 2
    assert ConceptoIngreso.objects.filter(codigo="reembolso", tributable_pr=False).exists()
    assert ConceptoDeduccion.objects.filter(codigo="plan_medico", antes_de_pr=True, antes_de_fica=True).exists()
    assert not ParametrosAnuales.objects.filter(estado="verificado").exists()


@pytest.mark.django_db
def test_cargar_parametros_y_salario_minimo_por_fecha():
    p = cargar.parametros(date(2026, 3, 1))
    assert p.anio == 2026 and len(p.tramos) == 5 and set(p.horas_extra) == {"anterior", "ley4"}
    assert p.salario_minimo == D("10.50") and not p.verificado
    assert cargar.salario_minimo_en(date(2024, 6, 30)).tarifa_hora == D("9.50")
    assert cargar.salario_minimo_en(date(2024, 7, 1)).tarifa_hora == D("10.50")
    assert cargar.salario_minimo_en(date(2023, 1, 1)) is None
    with pytest.raises(cargar.ConfiguracionFaltante):
        cargar.parametros(date(2030, 1, 1))


def _datos_anio(p):
    datos = {campo: getattr(p, campo) for campo in (
        "ss_tasa_empleado", "ss_tasa_patrono", "ss_tope", "medicare_tasa_empleado", "medicare_tasa_patrono",
        "medicare_adicional_tasa", "medicare_adicional_umbral", "futa_tasa", "futa_tope", "desempleo_tope",
        "sinot_tope", "choferil_empleado_semanal", "choferil_patrono_semanal", "exencion_personal_individuo",
        "exencion_personal_casado", "exencion_dependiente", "exencion_dependiente_custodia", "exencion_veterano")}
    tramos = list(p.tramos.all())
    datos.update({"tramos-TOTAL_FORMS": len(tramos), "tramos-INITIAL_FORMS": len(tramos),
                  "tramos-MIN_NUM_FORMS": 0, "tramos-MAX_NUM_FORMS": 1000})
    for i, t in enumerate(tramos):
        datos.update({f"tramos-{i}-id": t.pk, f"tramos-{i}-parametros": p.pk, f"tramos-{i}-desde": t.desde,
                      f"tramos-{i}-hasta": t.hasta or "", f"tramos-{i}-cuota_fija": t.cuota_fija, f"tramos-{i}-tasa": t.tasa})
    reglas = list(p.reglas_horas_extra.all())
    datos.update({"reglas-TOTAL_FORMS": len(reglas), "reglas-INITIAL_FORMS": len(reglas),
                  "reglas-MIN_NUM_FORMS": 0, "reglas-MAX_NUM_FORMS": 1000})
    for i, r in enumerate(reglas):
        datos.update({f"reglas-{i}-id": r.pk, f"reglas-{i}-parametros": p.pk, f"reglas-{i}-regimen": r.regimen,
                      f"reglas-{i}-diario": r.diario, f"reglas-{i}-semanal": r.semanal,
                      f"reglas-{i}-septimo_dia": r.septimo_dia, f"reglas-{i}-periodo_alimentos": r.periodo_alimentos})
    datos.update({"horas_por_dia": p.horas_por_dia, "limite_patrono_pequeno_licencias": p.limite_patrono_pequeno_licencias,
                  "tope_vacaciones_meses": p.tope_vacaciones_meses, "tope_enfermedad_dias": p.tope_enfermedad_dias})
    for prefijo, filas, campos in (
        ("licencias", list(p.reglas_licencia.all()),
         ("tipo", "regimen", "tamano", "anios_desde", "anios_hasta", "horas_minimas_mes", "dias_por_mes")),
        ("mesada", list(p.reglas_mesada.all()),
         ("regimen", "anios_desde", "anios_hasta", "meses_sueldo", "semanas_por_anio", "tope_meses")),
        ("bono", list(p.reglas_bono.all()),
         ("regimen", "mes_inicio_periodo", "horas_minimas", "umbral_empleados", "porcentaje_grande", "tope_grande",
          "porcentaje_pequeno", "tope_pequeno", "tope_salario")),
    ):
        datos.update({f"{prefijo}-TOTAL_FORMS": len(filas), f"{prefijo}-INITIAL_FORMS": len(filas),
                      f"{prefijo}-MIN_NUM_FORMS": 0, f"{prefijo}-MAX_NUM_FORMS": 1000})
        for i, fila in enumerate(filas):
            datos[f"{prefijo}-{i}-id"] = fila.pk
            datos[f"{prefijo}-{i}-parametros"] = p.pk
            for campo in campos:
                valor = getattr(fila, campo)
                datos[f"{prefijo}-{i}-{campo}"] = "" if valor is None else valor
    return datos


@pytest.mark.django_db
def test_verificar_y_cambiar_parametros(cliente_admin, admin):
    p = ParametrosAnuales.objects.get(anio=2026)
    url = reverse("parametros:anio", args=[2026])
    respuesta = cliente_admin.post(url, {**_datos_anio(p), "marcar_verificado": "on"})
    assert respuesta.status_code == 302, respuesta.content.decode()[:500]
    p.refresh_from_db()
    assert p.estado == "verificado" and p.verificado_por == admin
    # Cambiar un tramo sin confirmar vuelve a POR VERIFICAR y queda en la bitácora.
    datos = _datos_anio(p)
    datos["tramos-1-tasa"] = "7.5"
    cliente_admin.post(url, datos)
    p.refresh_from_db()
    assert p.estado == "por_verificar"
    registro = RegistroAuditoria.objects.filter(accion=Accion.CONFIGURACION_MODIFICADA).latest("id")
    assert "tramos" in registro.cambios


@pytest.mark.django_db
def test_copiar_anio(cliente_admin):
    origen = ParametrosAnuales.objects.get(anio=2026)
    cliente_admin.post(reverse("parametros:copiar"), {"origen": origen.pk, "anio": 2027})
    nuevo = ParametrosAnuales.objects.get(anio=2027)
    assert nuevo.estado == "por_verificar" and nuevo.ss_tope == origen.ss_tope
    assert nuevo.tramos.count() == 5 and nuevo.reglas_horas_extra.count() == 2
    assert origen.tramos.count() == 5  # el origen no cambia


@pytest.mark.django_db
def test_configuracion_solo_admin(cliente_preparador):
    for url in (reverse("parametros:inicio"), reverse("parametros:anio", args=[2026]),
                reverse("parametros:minimo_nuevo"), reverse("parametros:ingreso_nuevo")):
        assert cliente_preparador.get(url).status_code == 403


@pytest.mark.django_db
def test_concepto_del_sistema_no_cambia_codigo(cliente_admin):
    c = ConceptoIngreso.objects.get(codigo="regular")
    cliente_admin.post(reverse("parametros:ingreso_editar", args=[c.pk]), {
        "codigo": "otro", "nombre": "Salario regular", "tributable_pr": "on", "tributable_ss": "on",
        "tributable_medicare": "on", "tributable_futa": "on", "tributable_desempleo": "on",
        "tributable_sinot": "on", "tributable_cfse": "on", "activo": "on", "marcar_verificado": "on"})
    c.refresh_from_db()
    assert c.codigo == "regular" and c.estado == "verificado"


@pytest.fixture
def compania_con_tasas(compania):
    TasasCompania.objects.create(compania=compania, anio=2026, suta_tasa=D("2.4"), aportacion_especial_tasa=D("1"),
                                 sinot_empleado_tasa=D("0.3"), sinot_patrono_tasa=D("0.3"))
    return compania


@pytest.mark.django_db
def test_tasa_cfse(cliente_admin, compania_con_tasas):
    cls = ClasificacionCFSE.objects.create(compania=compania_con_tasas, codigo="9079")
    cliente_admin.post(reverse("companias:tasa_cfse_nueva", args=[compania_con_tasas.pk, cls.pk]),
                       {"anio": 2026, "tasa_por_100": "3.5"})
    assert TasaCFSE.objects.get(clasificacion=cls, anio=2026).tasa_por_100 == D("3.5")
    empleado = crear_empleado(compania_con_tasas, clasificacion_cfse=cls)
    assert cargar.tasas_compania(compania_con_tasas, empleado, 2026).cfse_por_100 == D("3.5")


@pytest.mark.django_db
def test_simulador_de_punta_a_punta(cliente_preparador, compania_con_tasas):
    empleado = crear_empleado(compania_con_tasas, tarifa="12")
    respuesta = cliente_preparador.post(reverse("calculo:simulador"), {
        "empleado": empleado.pk, "fecha_pago": "2026-09-25", "horas_regulares": "40",
        "deduccion_0": "plan_medico", "deduccion_0_monto": "50"})
    r = respuesta.context["resultado"]
    assert r is not None, respuesta.context["error"]
    assert r.bruto == D("480.00") and r.tributables["pr"] == D("430.00")
    html = respuesta.content.decode()
    assert "POR VERIFICAR" in html and "Retención de contribución sobre ingresos" in html


@pytest.mark.django_db
def test_simulador_sin_tasas_de_la_compania(cliente_preparador, compania):
    empleado = crear_empleado(compania)
    respuesta = cliente_preparador.post(reverse("calculo:simulador"), {
        "empleado": empleado.pk, "fecha_pago": "2026-09-25", "horas_regulares": "40"})
    assert "no tiene tasas" in respuesta.content.decode()


@pytest.mark.django_db
def test_simulador_no_permite_empleados_ajenos(cliente_preparador, compania, otra_compania):
    ajeno = crear_empleado(otra_compania, numero="9", ssn="345678901")
    respuesta = cliente_preparador.post(reverse("calculo:simulador"), {
        "empleado": ajeno.pk, "fecha_pago": "2026-09-25", "horas_regulares": "40"})
    assert respuesta.context["resultado"] is None
    assert "empleado" in respuesta.context["form"].errors


@pytest.mark.django_db
def test_minimo_con_propinas_llega_al_motor():
    minimo = SalarioMinimo.objects.get(vigente_desde=date(2024, 7, 1))
    assert cargar.parametros(date(2026, 3, 1)).salario_minimo_propinas == D("2.13")
    minimo.tarifa_propinas = D("3.00")
    minimo.save()
    assert cargar.parametros(date(2026, 3, 1)).salario_minimo_propinas == D("3.00")


@pytest.mark.django_db
def test_minimo_propinas_inicial_2_13():
    assert SalarioMinimo.objects.get(vigente_desde=date(2024, 7, 1)).tarifa_propinas == D("2.13")
