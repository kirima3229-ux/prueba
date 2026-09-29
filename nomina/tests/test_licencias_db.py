from datetime import date
from decimal import Decimal as D

import pytest
from django.urls import reverse

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.licencias import servicios
from apps.licencias.models import BonoNavidad, ErrorInmutable, MovimientoLicencia, saldo
from apps.parametros.models import ParametrosAnuales, ReglaBonoNavidad, ReglaLicencia

from .conftest import crear_empleado


@pytest.fixture
def empleados(compania):
    compania.numero_empleados = 30
    compania.save()
    ley4 = crear_empleado(compania, numero="1", ssn="234567890", nombre="Ana", fecha_empleo=date(2024, 1, 15))
    anterior = crear_empleado(compania, numero="2", ssn="345678901", nombre="Luis", fecha_empleo=date(2010, 3, 1))
    return ley4, anterior


@pytest.mark.django_db
def test_reglas_iniciales_cargadas():
    p = ParametrosAnuales.objects.get(anio=2026)
    assert p.reglas_licencia.count() == 11 and p.reglas_bono.count() == 2
    assert ReglaLicencia.objects.filter(parametros=p, regimen="ley4", tipo="vacaciones", tamano="grande").count() == 4
    ley4 = ReglaBonoNavidad.objects.get(parametros=p, regimen="ley4")
    assert ley4.horas_minimas == D("1350") and ley4.umbral_empleados == 20
    assert p.estado == "por_verificar"


@pytest.mark.django_db
def test_acumulacion_mensual(compania, empleados, preparador):
    ley4, anterior = empleados
    vista = servicios.acumular_mes(compania, 2026, 9, {ley4.pk: D("160"), anterior.pk: D("120")}, preparador)
    assert MovimientoLicencia.objects.count() == 0  # la vista previa no guarda
    por_empleado = {f.empleado.pk: f for f in vista.filas}
    assert por_empleado[ley4.pk].vacaciones.horas == D("6.00")      # ¾ día (2.7 años)
    assert por_empleado[anterior.pk].vacaciones.horas == D("10.00")  # 1.25 días
    assert por_empleado[anterior.pk].enfermedad.horas == D("8.00")

    servicios.acumular_mes(compania, 2026, 9, {ley4.pk: D("160"), anterior.pk: D("120")}, preparador, guardar=True)
    assert saldo(ley4, "vacaciones") == D("6.00") and saldo(ley4, "enfermedad") == D("8.00")
    # Repetir el mismo mes no duplica.
    otra = servicios.acumular_mes(compania, 2026, 9, {ley4.pk: D("160")}, preparador, guardar=True)
    assert otra.filas[0].ya_acumulado
    assert saldo(ley4, "vacaciones") == D("6.00")


@pytest.mark.django_db
def test_menos_de_130_horas_no_acumula(compania, empleados, preparador):
    ley4, _ = empleados
    servicios.acumular_mes(compania, 2026, 9, {ley4.pk: D("100")}, preparador, guardar=True)
    assert saldo(ley4, "vacaciones") == D("0") and saldo(ley4, "enfermedad") == D("0")


@pytest.mark.django_db
def test_tope_de_enfermedad(compania, empleados, preparador):
    ley4, _ = empleados
    servicios.registrar_movimiento(empleado=ley4, tipo="enfermedad", clase="saldo_inicial", horas=D("116"),
                                   fecha=date(2026, 1, 1), descripcion="Balance anterior", usuario=preparador)
    servicios.acumular_mes(compania, 2026, 9, {ley4.pk: D("160")}, preparador, guardar=True)
    assert saldo(ley4, "enfermedad") == D("120.00")  # tope 15 días × 8 h


@pytest.mark.django_db
def test_movimientos_uso_y_ajuste(compania, empleados, preparador):
    ley4, _ = empleados
    servicios.registrar_movimiento(empleado=ley4, tipo="vacaciones", clase="saldo_inicial", horas=D("40"),
                                   fecha=date(2026, 1, 1), descripcion="", usuario=preparador)
    servicios.registrar_movimiento(empleado=ley4, tipo="vacaciones", clase="uso", horas=D("16"),
                                   fecha=date(2026, 2, 1), descripcion="2 días", usuario=preparador)
    assert saldo(ley4, "vacaciones") == D("24")
    with pytest.raises(servicios.ErrorLicencia, match="balance suficiente"):
        servicios.registrar_movimiento(empleado=ley4, tipo="vacaciones", clase="uso", horas=D("30"),
                                       fecha=date(2026, 2, 2), descripcion="", usuario=preparador)
    with pytest.raises(servicios.ErrorLicencia, match="motivo"):
        servicios.registrar_movimiento(empleado=ley4, tipo="vacaciones", clase="ajuste", horas=D("-4"),
                                       fecha=date(2026, 2, 2), descripcion="", usuario=preparador)
    mov = servicios.registrar_movimiento(empleado=ley4, tipo="vacaciones", clase="ajuste", horas=D("-4"),
                                         fecha=date(2026, 2, 2), descripcion="Corrección", usuario=preparador)
    assert saldo(ley4, "vacaciones") == D("20")
    with pytest.raises(ErrorInmutable):
        mov.save()
    with pytest.raises(ErrorInmutable):
        mov.delete()


@pytest.mark.django_db
def test_pantallas_de_licencias(cliente_preparador, cliente_lectura, compania, empleados):
    ley4, anterior = empleados
    respuesta = cliente_preparador.post(reverse("licencias:acumular"), {
        "anio": 2026, "mes": 9, f"horas_{ley4.pk}": "160", f"horas_{anterior.pk}": "", "accion": "guardar"})
    assert respuesta.status_code == 302
    assert saldo(ley4, "vacaciones") == D("6.00") and saldo(anterior, "vacaciones") == D("0")
    assert RegistroAuditoria.objects.filter(accion=Accion.LICENCIAS_ACUMULADAS).exists()

    cliente_preparador.post(reverse("licencias:empleado", args=[ley4.pk]), {
        "tipo": "vacaciones", "clase": "uso", "horas": "4", "fecha": "2026-10-01", "descripcion": "Medio día"})
    assert saldo(ley4, "vacaciones") == D("2.00")
    assert RegistroAuditoria.objects.filter(accion=Accion.LICENCIA_MOVIMIENTO).exists()

    html = cliente_lectura.get(reverse("licencias:balances")).content.decode()
    assert "Ana" in html and "2.00" in html
    assert cliente_lectura.get(reverse("licencias:acumular")).status_code == 403
    cliente_lectura.post(reverse("licencias:empleado", args=[ley4.pk]), {
        "tipo": "vacaciones", "clase": "uso", "horas": "1", "fecha": "2026-10-01"})
    assert saldo(ley4, "vacaciones") == D("2.00")  # solo lectura no registra


@pytest.mark.django_db
def test_bono_de_navidad(compania, empleados, preparador):
    ley4, anterior = empleados
    datos = {ley4.pk: (D("2080"), D("20000")), anterior.pk: (D("2080"), D("25000"))}
    filas, periodo, _ = servicios.calcular_bonos(compania, 2026, datos, preparador)
    assert periodo == (date(2025, 10, 1), date(2026, 9, 30))
    montos = {f.empleado.pk: f.resultado.monto for f in filas}
    assert montos[ley4.pk] == D("400.00")      # 2% × 20,000 (más de 20 empleados)
    assert montos[anterior.pk] == D("600.00")  # 6% × 10,000
    assert BonoNavidad.objects.count() == 0
    servicios.calcular_bonos(compania, 2026, datos, preparador, guardar=True)
    assert BonoNavidad.objects.get(empleado=ley4, anio=2026).monto == D("400.00")
    # Recalcular reemplaza el cálculo (no duplica).
    servicios.calcular_bonos(compania, 2026, {ley4.pk: (D("1000"), D("9000"))}, preparador, guardar=True)
    b = BonoNavidad.objects.get(empleado=ley4, anio=2026)
    assert not b.elegible and b.monto == D("0")


@pytest.mark.django_db
def test_bono_patrono_pequeno(compania, empleados, preparador):
    compania.numero_empleados = 10
    compania.save()
    ley4, anterior = empleados
    filas, _, _ = servicios.calcular_bonos(
        compania, 2026, {ley4.pk: (D("2080"), D("40000")), anterior.pk: (D("2080"), D("40000"))}, preparador
    )
    montos = {f.empleado.pk: f.resultado.monto for f in filas}
    assert montos[ley4.pk] == D("300.00") and montos[anterior.pk] == D("300.00")


@pytest.mark.django_db
def test_pantalla_bono(cliente_preparador, compania, empleados):
    ley4, anterior = empleados
    respuesta = cliente_preparador.post(reverse("licencias:bono"), {
        "anio": 2026, f"horas_{ley4.pk}": "2080", f"salario_{ley4.pk}": "20,000",
        f"horas_{anterior.pk}": "", f"salario_{anterior.pk}": "", "accion": "guardar"})
    assert respuesta.status_code == 302
    assert BonoNavidad.objects.get(empleado=ley4).monto == D("400.00")
    assert not BonoNavidad.objects.filter(empleado=anterior).exists()
    assert RegistroAuditoria.objects.filter(accion=Accion.BONO_CALCULADO).exists()
    excel = cliente_preparador.get(reverse("licencias:bono"), {"anio": 2026, "formato": "xlsx"})
    assert excel.status_code == 200 and "bono_navidad_2026" in excel["Content-Disposition"]
    errores = cliente_preparador.post(reverse("licencias:bono"), {
        "anio": 2026, f"horas_{ley4.pk}": "abc", f"salario_{ley4.pk}": "1", "accion": "vista_previa"})
    assert "no es un número válido" in errores.content.decode()


@pytest.mark.django_db
def test_copiar_anio_incluye_reglas_nuevas(cliente_admin):
    origen = ParametrosAnuales.objects.get(anio=2026)
    cliente_admin.post(reverse("parametros:copiar"), {"origen": origen.pk, "anio": 2027})
    nuevo = ParametrosAnuales.objects.get(anio=2027)
    assert nuevo.reglas_licencia.count() == 11 and nuevo.reglas_bono.count() == 2
